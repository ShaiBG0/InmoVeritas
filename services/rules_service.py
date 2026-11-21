"""
services/rules_service.py
Carga, valida, versiona y actualiza el archivo externo config/rules_config.yaml.
Ningún agente debe tener reglas escritas en su código: todos las piden aquí.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ValidationError, field_validator

# ----------------------------------------------------------------------
# Rutas (se calculan a partir de la ubicación de este archivo)
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
RULES_PATH = BASE_DIR / "config" / "rules_config.yaml"
HISTORY_PATH = BASE_DIR / "config" / "rules_history.json"
BACKUPS_DIR = BASE_DIR / "config" / "backups"

ALLOWED_DOC_TYPES = {
    "escrituras",
    "predial",
    "alineamiento_numero_oficial",
    "uso_suelo",
}
ALLOWED_PROJECT_TYPES = {"store", "cedis"}


class RulesError(Exception):
    """Se lanza cuando el archivo de reglas no existe o es inválido."""


# ----------------------------------------------------------------------
# Modelos que describen cómo DEBE verse el YAML
# ----------------------------------------------------------------------
class Documents(BaseModel):
    required: list[str]

    @field_validator("required")
    @classmethod
    def _check_required(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Debe haber al menos un documento obligatorio")
        desconocidos = [x for x in v if x not in ALLOWED_DOC_TYPES]
        if desconocidos:
            raise ValueError(
                f"Tipos de documento desconocidos: {desconocidos}. "
                f"Permitidos: {sorted(ALLOWED_DOC_TYPES)}"
            )
        return v


class PredialRule(BaseModel):
    enabled: bool = True
    min_year: Optional[int] = None
    source: str = ""
    official: bool = False
    requires_committee_confirmation: bool = True

    @field_validator("min_year")
    @classmethod
    def _check_year(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1900 <= v <= 2100):
            raise ValueError("min_year debe estar entre 1900 y 2100")
        return v


class LandUseProfile(BaseModel):
    allowed_categories: list[str] = []
    keywords_hint: list[str] = []
    restrictions: list[str] = []


class LandUse(BaseModel):
    store: LandUseProfile
    cedis: LandUseProfile


class Tolerances(BaseModel):
    surface_difference: Optional[float] = None


class Validation(BaseModel):
    require_evidence: bool = True
    unknown_data_status: str = "pending"
    missing_data_status: str = "requires_review"


class RecommendationCriteria(BaseModel):
    no_cumple_if: list[str] = []
    requires_review_if: list[str] = []


class Rules(BaseModel):
    documents: Documents
    predial: PredialRule
    property_types: list[str]
    land_use: LandUse
    tolerances: Tolerances
    validation: Validation
    recommendation: RecommendationCriteria

    @field_validator("property_types")
    @classmethod
    def _check_types(cls, v: list[str]) -> list[str]:
        desconocidos = [x for x in v if x not in ALLOWED_PROJECT_TYPES]
        if desconocidos or not v:
            raise ValueError(
                f"property_types inválido. Permitidos: {sorted(ALLOWED_PROJECT_TYPES)}"
            )
        return v


class RulesFile(BaseModel):
    version: str
    updated_at: str
    rules: Rules


# ----------------------------------------------------------------------
# Validación
# ----------------------------------------------------------------------
def parse_and_validate(raw: bytes) -> tuple[Optional[RulesFile], list[str]]:
    """
    Recibe el contenido del YAML en bytes.
    Devuelve (reglas, []) si es válido, o (None, [lista de errores en español]).
    """
    try:
        text = raw.decode("utf-8-sig")  # acepta UTF-8 con o sin BOM
    except UnicodeDecodeError:
        return None, [
            "El archivo no está guardado en UTF-8. "
            "Guárdalo con codificación UTF-8 y vuelve a intentar."
        ]

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return None, [f"El YAML tiene errores de sintaxis: {e}"]

    if not isinstance(data, dict):
        return None, [
            "El YAML debe contener las claves 'version', 'updated_at' y 'rules'."
        ]

    try:
        parsed = RulesFile.model_validate(data)
    except ValidationError as e:
        errores = []
        for err in e.errors():
            ruta = ".".join(str(p) for p in err["loc"])
            errores.append(f"{ruta}: {err['msg']}")
        return None, errores

    return parsed, []


# ----------------------------------------------------------------------
# Historial de versiones aplicadas
# ----------------------------------------------------------------------
def _read_history() -> list[dict]:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def _append_history(version: str, sha256: str, note: str = "") -> None:
    history = _read_history()
    if history and history[-1]["sha256"] == sha256:
        return  # no cambió nada, no se registra de nuevo
    history.append(
        {
            "version": version,
            "sha256": sha256,
            "applied_at": datetime.now().isoformat(timespec="seconds"),
            "note": note,
        }
    )
    HISTORY_PATH.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ----------------------------------------------------------------------
# Carga con caché
# ----------------------------------------------------------------------
_cache: dict = {"rules": None, "sha256": None, "loaded_at": None}


def reload() -> RulesFile:
    """Lee el YAML del disco, lo valida y actualiza la caché."""
    if not RULES_PATH.exists():
        raise RulesError(f"No existe el archivo de reglas: {RULES_PATH}")

    raw = RULES_PATH.read_bytes()
    parsed, errors = parse_and_validate(raw)
    if errors:
        raise RulesError(
            "El archivo de reglas es inválido:\n  - " + "\n  - ".join(errors)
        )

    sha = hashlib.sha256(raw).hexdigest()
    _cache.update(
        rules=parsed,
        sha256=sha,
        loaded_at=datetime.now().isoformat(timespec="seconds"),
    )
    _append_history(parsed.version, sha, note="Carga desde disco")
    return parsed


def get_rules() -> RulesFile:
    """Devuelve las reglas vigentes (usa caché; carga si es la primera vez)."""
    if _cache["rules"] is None:
        reload()
    return _cache["rules"]


def get_version_info() -> dict:
    """
    Referencia de la configuración usada. Cada análisis debe guardar este
    diccionario para poder demostrar con qué reglas se evaluó.
    """
    rules = get_rules()
    return {
        "version": rules.version,
        "updated_at": rules.updated_at,
        "sha256": _cache["sha256"],
        "loaded_at": _cache["loaded_at"],
    }


# ----------------------------------------------------------------------
# Actualización segura desde el panel del abogado
# ----------------------------------------------------------------------
def save_new(raw: bytes, note: str = "") -> tuple[bool, list[str]]:
    """
    Reemplaza el archivo de reglas SOLO si el nuevo es válido.
    Guarda copia de respaldo del anterior y registra la actualización.
    Devuelve (True, []) o (False, [errores]).
    """
    parsed, errors = parse_and_validate(raw)
    if errors:
        return False, errors

    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    if RULES_PATH.exists():
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(RULES_PATH, BACKUPS_DIR / f"rules_config_{sello}.yaml")

    RULES_PATH.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    _append_history(parsed.version, sha, note=note or "Actualización manual")
    reload()
    return True, []


# ----------------------------------------------------------------------
# Transparencia: qué reglas son provisionales o están sin definir
# ----------------------------------------------------------------------
def provisional_items() -> list[str]:
    """Lista de elementos que NO deben presentarse como requisito oficial."""
    r = get_rules().rules
    items: list[str] = []

    if r.predial.enabled and not r.predial.official:
        items.append(
            f"Predial: año mínimo {r.predial.min_year} es provisional "
            f"(fuente: {r.predial.source}). Requiere confirmación del comité."
        )
    if r.tolerances.surface_difference is None:
        items.append(
            "Tolerancia de superficie sin definir: toda diferencia irá a revisión."
        )
    if not r.land_use.store.allowed_categories:
        items.append("Uso de suelo para TIENDA: sin categorías oficiales cargadas.")
    if not r.land_use.cedis.allowed_categories:
        items.append("Uso de suelo para CEDIS: sin categorías oficiales cargadas.")
    return items


# ----------------------------------------------------------------------
# Prueba rápida desde terminal:  python -m services.rules_service
# ----------------------------------------------------------------------
if __name__ == "__main__":
    info = get_version_info()
    print("Reglas cargadas correctamente.")
    for k, v in info.items():
        print(f"  {k}: {v}")
    print("Reglas provisionales o pendientes de confirmar:")
    for item in provisional_items():
        print("  -", item)