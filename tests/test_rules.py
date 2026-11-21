import yaml

from services.rules_service import RULES_PATH, parse_and_validate


def _datos_reales() -> dict:
    """Carga el YAML real como diccionario para poder modificarlo."""
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8-sig"))


def _a_bytes(datos: dict) -> bytes:
    return yaml.safe_dump(datos, allow_unicode=True).encode("utf-8")


def test_archivo_real_es_valido():
    parsed, errors = parse_and_validate(RULES_PATH.read_bytes())
    assert errors == []
    assert parsed.rules.predial.min_year == 2020
    assert parsed.rules.tolerances.surface_difference is None


def test_yaml_con_sintaxis_rota():
    parsed, errors = parse_and_validate(b"rules: [sin cerrar")
    assert parsed is None
    assert errors


def test_falta_la_seccion_rules():
    raw = b"version: '1'\nupdated_at: '2026-01-01'\nrules: {}\n"
    parsed, errors = parse_and_validate(raw)
    assert parsed is None
    assert errors


def test_documento_inventado_es_rechazado():
    datos = _datos_reales()
    datos["rules"]["documents"]["required"].append("documento_inventado")
    parsed, errors = parse_and_validate(_a_bytes(datos))
    assert parsed is None
    assert any("desconocidos" in e for e in errors)


def test_cambiar_anio_predial_no_requiere_tocar_codigo():
    datos = _datos_reales()
    datos["rules"]["predial"]["min_year"] = 2022
    parsed, errors = parse_and_validate(_a_bytes(datos))
    assert errors == []
    assert parsed.rules.predial.min_year == 2022