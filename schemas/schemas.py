from pydantic import BaseModel, Field as PField
from typing import Literal, Optional

DocType = Literal["escrituras","predial","alineamiento_numero_oficial","uso_suelo","desconocido"]

class Evidence(BaseModel):
    doc_id: str
    page: int
    fragment: str
    verified: Optional[bool] = None        # lo llena el Auditor
    verification_note: str = ""

class Fld(BaseModel):                       # un dato extraído
    value: Optional[str] = None
    page: Optional[int] = None
    fragment: Optional[str] = None
    confidence: float = 0.0

class ClassificationOut(BaseModel):
    doc_type: DocType
    confidence: float
    reason: str

class EscriturasOut(BaseModel):
    propietario: Fld; direccion: Fld; superficie_terreno: Fld
    datos_relevantes: Fld; identificadores: Fld

class PredialOut(BaseModel):
    propietario: Fld; direccion: Fld; cuenta_predial: Fld
    superficie: Fld; ejercicio_fiscal: Fld

class AlineamientoOut(BaseModel):
    direccion: Fld; numero_oficial: Fld; identificacion_predio: Fld
    alineamiento: Fld; fecha_emision: Fld; vigencia: Fld; autoridad: Fld

class UsoSueloOut(BaseModel):
    direccion: Fld; uso_autorizado: Fld; actividades_permitidas: Fld
    restricciones: Fld; superficie: Fld; fecha_emision: Fld
    vigencia: Fld; autoridad: Fld
    compatibilidad_tienda: Literal["compatible","no_compatible","pendiente"]
    compatibilidad_cedis: Literal["compatible","no_compatible","pendiente"]
    justificacion: str

class Finding(BaseModel):
    id: str
    description: str
    kind: Literal["requisito","faltante","inconsistencia","legibilidad","riesgo"]
    severity: Literal["alta","media","baja","info"]
    status: Literal["cumple","no_cumple","pendiente"]
    doc_id: Optional[str] = None
    page: Optional[int] = None
    fragment: Optional[str] = None
    found_value: Optional[str] = None
    compare_value: Optional[str] = None
    rule_ref: Optional[str] = None
    agent: str
    confidence: float = 0.0
    audit_status: Literal["verificado","no_verificado","pendiente"] = "pendiente"
    evidences: list[Evidence] = []

class Recommendation(BaseModel):
    decision: Literal["Cumple","Requiere revisión","No cumple"]
    explanation: str
    confidence: float
    met: list[str]; unmet: list[str]; missing_docs: list[str]
    inconsistencies: list[str]