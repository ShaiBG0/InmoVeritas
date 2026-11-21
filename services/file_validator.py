"""
services/file_validator.py
Validación técnica de archivos (NO es validación legal):
extensión, firma binaria (magic bytes), tamaño, integridad, ZIP seguro y duplicados.
"""
from __future__ import annotations

import hashlib
import io
import os
import zipfile
from dataclasses import dataclass
from typing import Optional

from PIL import Image

try:  # HEIC opcional
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:
    HEIF_OK = False

MB = 1024 * 1024

EXT_TO_KIND = {
    "pdf": "pdf", "jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp",
    "tiff": "tiff", "tif": "tiff", "heic": "heic", "heif": "heic", "zip": "zip",
}


def _sig_heic(b: bytes) -> bool:
    return len(b) >= 12 and b[4:8] == b"ftyp" and b[8:12] in (
        b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heif",
    )


SIGNATURES = {
    "pdf": lambda b: b.startswith(b"%PDF-"),
    "jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
    "tiff": lambda b: b[:4] in (b"II*\x00", b"MM\x00*"),
    "heic": _sig_heic,
    "zip": lambda b: b.startswith(b"PK\x03\x04"),
}


@dataclass
class FileResult:
    name: str
    kind: Optional[str]
    size: int
    sha256: str
    status: str            # "valido" | "invalido" | "duplicado"
    reason: str = ""
    fix: str = ""
    origin: str = ""       # nombre del ZIP de donde salió, si aplica
    data: bytes = b""      # solo se conserva si es válido


def _mk(name, data, status, kind=None, reason="", fix="") -> FileResult:
    return FileResult(
        name=name, kind=kind, size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        status=status, reason=reason, fix=fix,
        data=data if status == "valido" else b"",
    )


def _check_integrity(kind: str, data: bytes) -> Optional[str]:
    """None si está bien; si no, texto con el problema."""
    try:
        if kind == "pdf":
            if b"%%EOF" not in data[-4096:]:
                return "El PDF parece incompleto o dañado (le falta el final del archivo)."
        elif kind == "zip":
            if not zipfile.is_zipfile(io.BytesIO(data)):
                return "El ZIP está dañado."
        elif kind == "heic":
            if HEIF_OK:
                with Image.open(io.BytesIO(data)) as im:
                    im.verify()
        else:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
    except Exception:
        return "El archivo está dañado o no se puede abrir."
    return None


def validate_file(name: str, data: bytes, max_bytes: int) -> FileResult:
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if ext not in EXT_TO_KIND:
        return _mk(name, data, "invalido", None,
                   f"El formato «.{ext or 'sin extensión'}» no está permitido.",
                   "Envía el documento como PDF, imagen (JPG, PNG, WEBP, TIFF, HEIC) o ZIP.")
    kind = EXT_TO_KIND[ext]
    if len(data) == 0:
        return _mk(name, data, "invalido", kind, "El archivo está vacío.",
                   "Vuelve a generarlo o escanearlo y envíalo de nuevo.")
    if len(data) > max_bytes:
        return _mk(name, data, "invalido", kind,
                   f"Pesa {len(data) / MB:.1f} MB y el máximo es {max_bytes // MB} MB.",
                   "Reduce su tamaño o envíalo en partes.")
    if not SIGNATURES[kind](data):
        return _mk(name, data, "invalido", kind,
                   f"El contenido real no coincide con la extensión .{ext}.",
                   "Comprueba que sea realmente ese tipo de archivo; vuelve a exportarlo o escanearlo.")
    problem = _check_integrity(kind, data)
    if problem:
        return _mk(name, data, "invalido", kind, problem,
                   "Vuelve a generar o escanear el documento y envíalo de nuevo.")
    return _mk(name, data, "valido", kind)


def _is_junk(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    base = parts[-1]
    return "__MACOSX" in parts or base.startswith("._") or base in (".DS_Store", "Thumbs.db")


def expand_zip(zip_name, data, max_files, max_uncompressed, max_file_bytes) -> list[FileResult]:
    """Lee el ZIP en memoria (nunca escribe rutas del ZIP en disco)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return [_mk(zip_name, data, "invalido", "zip", "El ZIP está dañado y no se puede abrir.",
                    "Vuelve a comprimir los documentos y envíalo de nuevo.")]
    out: list[FileResult] = []
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and not _is_junk(i.filename)]
        if not infos:
            return [_mk(zip_name, data, "invalido", "zip", "El ZIP no contiene archivos.",
                        "Comprime tus documentos dentro del ZIP.")]
        if len(infos) > max_files:
            return [_mk(zip_name, data, "invalido", "zip",
                        f"El ZIP trae {len(infos)} archivos y el máximo es {max_files}.",
                        "Divídelo en varios ZIP más pequeños.")]
        total = sum(i.file_size for i in infos)
        comp = sum(i.compress_size for i in infos) or 1
        if total > max_uncompressed:
            return [_mk(zip_name, data, "invalido", "zip",
                        f"Descomprimido pesaría {total / MB:.0f} MB (máximo {max_uncompressed // MB} MB).",
                        "Divídelo en varios ZIP más pequeños.")]
        if total > 50 * MB and total / comp > 200:
            return [_mk(zip_name, data, "invalido", "zip",
                        "El ZIP tiene una compresión sospechosa (posible ZIP bomb).",
                        "Vuelve a comprimir tus documentos normalmente.")]
        for i in infos:
            path = i.filename.replace("\\", "/")
            parts = path.split("/")
            base = parts[-1]
            if path.startswith("/") or ".." in parts or (len(parts[0]) > 1 and parts[0][1] == ":"):
                out.append(_mk(base or path, b"", "invalido", None,
                               "El ZIP contiene una ruta peligrosa.",
                               "Vuelve a comprimir sin rutas especiales."))
                continue
            if i.flag_bits & 0x1:
                out.append(_mk(base, b"", "invalido", None, "El archivo está protegido con contraseña.",
                               "Envíalo sin contraseña."))
                continue
            if i.file_size > max_file_bytes:
                out.append(_mk(base, b"", "invalido", None,
                               f"Pesa más de {max_file_bytes // MB} MB.", "Reduce su tamaño."))
                continue
            try:
                inner = zf.read(i)
            except Exception:
                out.append(_mk(base, b"", "invalido", None, "No se pudo leer dentro del ZIP (dañado).",
                               "Vuelve a comprimir el documento."))
                continue
            if os.path.splitext(base)[1].lower() == ".zip":
                out.append(_mk(base, inner, "invalido", "zip", "No se permiten ZIP dentro de un ZIP.",
                               "Saca los documentos y comprímelos en un solo ZIP."))
                continue
            r = validate_file(base, inner, max_file_bytes)
            r.origin = zip_name
            out.append(r)
    return out


def process_uploads(files, max_file_bytes=25 * MB, max_files=40,
                    max_zip_uncompressed=300 * MB, max_zip_container=200 * MB) -> list[FileResult]:
    """files: lista de (nombre, bytes). Devuelve un FileResult por archivo."""
    out: list[FileResult] = []
    for name, data in files:
        name = os.path.basename(name.replace("\\", "/")) or "sin_nombre"
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        limit = max_zip_container if ext == "zip" else max_file_bytes
        r = validate_file(name, data, limit)
        if r.status == "valido" and r.kind == "zip":
            out.extend(expand_zip(name, data, max_files, max_zip_uncompressed, max_file_bytes))
        else:
            out.append(r)

    seen: dict[str, str] = {}
    count = 0
    for r in out:
        if r.status != "valido":
            continue
        if r.sha256 in seen:
            r.status, r.data = "duplicado", b""
            r.reason = f"Tiene el mismo contenido que «{seen[r.sha256]}». Se conserva una sola copia."
            r.fix = "No necesitas volver a enviarlo."
        elif count >= max_files:
            r.status, r.data = "invalido", b""
            r.reason = f"Se superó el máximo de {max_files} archivos por envío."
            r.fix = "Envía el resto en un segundo envío."
        else:
            seen[r.sha256] = r.name
            count += 1
    return out