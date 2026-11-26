"""Esquemas de entrada (Pydantic). Toda entrada externa se valida aquí antes de tocar la BD."""
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import config

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
VARIABLES = tuple(config.RANGOS_FISICOS)
Texto80 = Annotated[str, Field(min_length=1, max_length=80)]


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginIn(Base):
    email: str = Field(max_length=120)
    clave: str = Field(min_length=1, max_length=128)


class UsuarioIn(Base):
    nombre: Texto80
    email: str = Field(max_length=120)
    clave: Optional[str] = Field(default=None, max_length=128)
    rol: str
    activo: bool = True

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        v = v.lower()
        if not EMAIL_RE.match(v):
            raise ValueError("correo con formato inválido")
        return v

    @field_validator("rol")
    @classmethod
    def _rol(cls, v):
        if v not in ("Administrador", "Supervisor", "Encargado"):
            raise ValueError("rol inexistente")
        return v


class SistemaIn(Base):
    nombre: Texto80
    ubicacion: Optional[str] = Field(default=None, max_length=120)
    activo: bool = True


class CultivoIn(Base):
    id_sistema: int
    nombre: Texto80
    especie: Optional[str] = Field(default=None, max_length=80)
    fecha_inicio: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    activo: bool = True
    id_encargado: Optional[int] = None


class AsignacionIn(Base):
    id_encargado: Optional[int] = None


class ConfiguracionIn(Base):
    max_intentos: int = Field(ge=3, le=10)
    bloqueo_minutos: int = Field(ge=1, le=1440)


class DispositivoIn(Base):
    id_sistema: int
    codigo: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_\-]+$")
    nombre: Texto80
    tipo: Optional[str] = Field(default="controlador", max_length=40)
    activo: bool = True
    variables: Optional[List[str]] = None  # al crear: sensores a registrar

    @field_validator("variables")
    @classmethod
    def _vars(cls, v):
        if v is None:
            return v
        malas = [x for x in v if x not in VARIABLES]
        if malas:
            raise ValueError(f"variables no soportadas: {malas}")
        return list(dict.fromkeys(v))


class SensorIn(Base):
    id_dispositivo: int
    variable: str
    unidad: Optional[str] = Field(default=None, max_length=20)
    activo: bool = True

    @field_validator("variable")
    @classmethod
    def _v(cls, v):
        if v not in VARIABLES:
            raise ValueError(f"variable no soportada; use una de {list(VARIABLES)}")
        return v

    @model_validator(mode="after")
    def _unidad(self):
        if not self.unidad:
            self.unidad = config.UNIDADES[self.variable]
        return self


class UmbralIn(Base):
    id_sistema: int
    variable: str
    minimo: float = Field(allow_inf_nan=False)
    maximo: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _rango(self):
        if self.variable not in VARIABLES:
            raise ValueError(f"variable no soportada; use una de {list(VARIABLES)}")
        if not self.minimo < self.maximo:
            raise ValueError("el mínimo debe ser menor que el máximo")
        lo, hi = config.RANGOS_FISICOS[self.variable]
        if self.minimo < lo or self.maximo > hi:
            raise ValueError(f"el umbral debe estar dentro del rango físico {lo}–{hi}")
        return self


class MedicionIn(Base):
    variable: str
    valor: float = Field(allow_inf_nan=False)
    marca_tiempo: Optional[datetime] = None

    @field_validator("valor", mode="before")
    @classmethod
    def _valor_numerico(cls, v):
        if isinstance(v, (str, bool)) or v is None:
            raise ValueError("el valor debe ser numérico")
        return v

    @field_validator("variable")
    @classmethod
    def _var(cls, v):
        if v not in VARIABLES:
            raise ValueError(f"variable no soportada; use una de {list(VARIABLES)}")
        return v

    @model_validator(mode="after")
    def _plausible(self):
        lo, hi = config.RANGOS_FISICOS[self.variable]
        if not lo <= self.valor <= hi:
            raise ValueError(f"valor fuera del rango físico posible para {self.variable} ({lo} a {hi})")
        ts = self.marca_tiempo
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts = ts.astimezone(timezone.utc).replace(microsecond=0)
            ahora = datetime.now(timezone.utc)
            if ts > ahora + timedelta(seconds=60):
                raise ValueError("la marca de tiempo está en el futuro")
            if ts < ahora - timedelta(days=365):
                raise ValueError("la marca de tiempo tiene más de un año de antigüedad")
            self.marca_tiempo = ts
        return self


class LoteIn(Base):
    mediciones: List[MedicionIn]

    @field_validator("mediciones")
    @classmethod
    def _tam(cls, v):
        if not v:
            raise ValueError("el lote está vacío")
        if len(v) > config.MAX_LOTE:
            raise ValueError(f"el lote supera el máximo de {config.MAX_LOTE} mediciones")
        return v


class AlertaPatch(Base):
    estado: str
    causa: Optional[str] = Field(default=None, max_length=255)

    @field_validator("estado")
    @classmethod
    def _e(cls, v):
        if v not in ("En proceso", "Resuelta"):
            raise ValueError("estado destino debe ser 'En proceso' o 'Resuelta'")
        return v


class BitacoraIn(Base):
    id_cultivo: int
    accion: str = Field(min_length=1, max_length=60)
    detalle: Optional[str] = Field(default=None, max_length=500)


def mensajes(e: ValidationError):
    out = []
    for err in e.errors():
        campo = ".".join(str(x) for x in err["loc"]) or "cuerpo"
        msg = err["msg"].replace("Value error, ", "")
        out.append({"campo": campo, "mensaje": msg})
    return out
