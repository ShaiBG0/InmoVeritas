"""
app.py - InmoVeritas (interfaz web)
Ejecutar:  python -m uvicorn app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from fastapi import FastAPI, File, Form, Request, UploadFile  # noqa: E402
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from services import case_service, rules_service  # noqa: E402
from services.file_validator import MB, process_uploads  # noqa: E402


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).split("#", 1)[0].strip())
    except ValueError:
        return default


MAX_FILE_MB = _int("MAX_FILE_MB", 25)
MAX_FILES = _int("MAX_FILES_PER_CASE", 40)
MAX_ZIP_UNCOMPRESSED_MB = _int("MAX_ZIP_UNCOMPRESSED_MB", 300)
MAX_ZIP_CONTAINER_MB = _int("MAX_ZIP_CONTAINER_MB", 200)

PROJECT_LABELS = {"store": "Tienda comercial", "cedis": "Centro de Distribución (CEDIS)"}
FILE_STATUS = {
    "valido": ("Aceptado", "ok"),
    "invalido": ("Rechazado", "err"),
    "duplicado": ("Repetido", "warn"),
}
ANALYSIS_LABELS = {"pendiente_agentes": "Recibido · análisis pendiente"}


def human_size(n: int) -> str:
    if n >= MB:
        return f"{n / MB:.1f} MB"
    return f"{max(1, round(n / 1024))} KB" if n else "0 KB"


app = FastAPI(title="InmoVeritas")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))
templates.env.filters["filesize"] = human_size
templates.env.globals.update(
    PROJECT_LABELS=PROJECT_LABELS, FILE_STATUS=FILE_STATUS, ANALYSIS_LABELS=ANALYSIS_LABELS,
    MAX_FILE_MB=MAX_FILE_MB,
)


def _message(request: Request, title: str, text: str, status: int = 200, back: str = ""):
    return templates.TemplateResponse(
        request, "mensaje.html", {"title": title, "text": text, "back": back}, status_code=status
    )


# ============================ PANEL DEL ABOGADO ============================
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/panel")


@app.get("/panel", response_class=HTMLResponse)
def panel(request: Request, nuevo: str = ""):
    cases = case_service.list_cases()
    good = [c for c in cases if not c.get("error")]
    broken = len(cases) - len(good)
    stats = {
        "total": len(good),
        "pending": sum(1 for c in good if c["analysis_status"] == "pendiente_agentes"),
        "with_rejected": sum(1 for c in good if c["invalid"] > 0),
        "valid_files": sum(c["valid"] for c in good),
    }
    security = [
        {"label": "Cifrado AES-256-GCM", "state": "ok" if good or not broken else "err",
         "text": (f"Activo en {len(good)} expediente(s): llave y metadatos comprobados al abrirlos"
                  if good else "Sin expedientes que comprobar todavía")},
        {"label": "Almacenamiento", "state": "ok", "text": "Local, solo en este equipo (carpeta storage/)"},
        {"label": "Verificación en dos pasos (MFA)", "state": "off", "text": "Aún no implementada"},
        {"label": "Análisis multiagente", "state": "off", "text": "Aún no conectado"},
        {"label": "Purgar / Destruir expediente", "state": "off", "text": "Aún no implementado"},
    ]
    try:
        rules_info = rules_service.get_version_info()
        provisional = rules_service.provisional_items()
    except rules_service.RulesError as e:
        rules_info, provisional = None, [str(e)]
    links = case_service.list_links()
    if nuevo and not case_service.get_link(nuevo):
        nuevo = ""
    return templates.TemplateResponse(request, "dashboard.html", {
        "cases": good, "broken": broken, "stats": stats, "security": security,
        "rules_info": rules_info, "provisional": provisional, "links": links,
        "new_token": nuevo, "base_url": str(request.base_url),
    })


@app.post("/panel/enlaces")
def create_link(label: str = Form(...)):
    token = case_service.create_link(label or "Sin referencia")
    return RedirectResponse(f"/panel?nuevo={token}", status_code=303)


@app.get("/panel/caso/{case_id}", response_class=HTMLResponse)
def case_detail(request: Request, case_id: str):
    meta = case_service.load_meta(case_id)
    if not meta:
        return _message(request, "Expediente no encontrado",
                        "No existe o no se pudo abrir (llave o datos dañados).",
                        status=404, back="/panel")
    return templates.TemplateResponse(request, "case_detail.html", {
        "meta": meta, "s": case_service.summarize(meta),
        "checks": case_service.verify_case_encryption(case_id, meta),
    })


# ============================ FORMULARIO PÚBLICO ============================
@app.get("/recibir/{token}", response_class=HTMLResponse)
def intake_form(request: Request, token: str, ref: str = ""):
    link = case_service.get_link(token)
    if not link:
        return _message(request, "Enlace no válido",
                        "Este enlace no existe. Pide uno nuevo a quien te lo compartió.", status=404)
    existing = case_service.get_case_for_token(ref, token) if ref else None
    return templates.TemplateResponse(request, "intake.html", {
        "token": token, "link_label": link["label"], "error": "",
        "ref": existing["case_id"] if existing else "",
        "project_type": existing["project_type"] if existing else "",
    })


@app.post("/recibir/{token}", response_class=HTMLResponse)
async def intake_submit(
    request: Request, token: str,
    project_type: str = Form(""), applicant: str = Form(""), ref: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    link = case_service.get_link(token)
    if not link:
        return _message(request, "Enlace no válido",
                        "Este enlace no existe. Pide uno nuevo a quien te lo compartió.", status=404)
    existing = case_service.get_case_for_token(ref, token) if ref else None
    if existing:
        project_type = existing["project_type"]

    def back_with_error(msg: str):
        return templates.TemplateResponse(request, "intake.html", {
            "token": token, "link_label": link["label"], "error": msg,
            "ref": existing["case_id"] if existing else "", "project_type": project_type,
        })

    if project_type not in PROJECT_LABELS:
        return back_with_error("Elige si el inmueble es para una tienda comercial o un CEDIS.")

    raw = []
    for f in files:
        if f.filename:
            raw.append((f.filename, await f.read()))
    if not raw:
        return back_with_error("No seleccionaste ningún archivo. Adjunta al menos un documento.")

    results = process_uploads(
        raw, max_file_bytes=MAX_FILE_MB * MB, max_files=MAX_FILES,
        max_zip_uncompressed=MAX_ZIP_UNCOMPRESSED_MB * MB, max_zip_container=MAX_ZIP_CONTAINER_MB * MB,
    )
    case_id = ""
    if any(r.status == "valido" for r in results):
        case_id = case_service.save_case(token, link["label"], project_type, applicant, results,
                                         existing["case_id"] if existing else "")
    return templates.TemplateResponse(request, "intake_result.html", {
        "token": token, "case_id": case_id, "results": results,
        "n_ok": sum(r.status == "valido" for r in results),
        "n_bad": sum(r.status == "invalido" for r in results),
        "n_dup": sum(r.status == "duplicado" for r in results),
    })