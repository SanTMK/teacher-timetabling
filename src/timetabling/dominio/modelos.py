"""Creado con Claude. Modelos del dominio del timetabling escolar.

Las horas se representan como minutos desde medianoche (``int``). Este módulo no
depende de la base de datos, la interfaz ni Excel.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

DIAS_SEMANA: tuple[str, ...] = ("L", "M", "X", "J", "V")
NOMBRES_DIAS: dict[str, str] = {
    "L": "Lunes",
    "M": "Martes",
    "X": "Miércoles",
    "J": "Jueves",
    "V": "Viernes",
    "S": "Sábado",
    "D": "Domingo",
}
DIAS_VALIDOS: tuple[str, ...] = tuple(NOMBRES_DIAS)
MINUTOS_DIA = 24 * 60


def a_minutos(hora: str) -> int:
    """Convierte ``"HH:MM"`` a minutos desde medianoche."""
    coincidencia = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", hora)
    if not coincidencia:
        raise ValueError(f"Hora inválida: {hora!r}; use el formato HH:MM")
    horas, minutos = int(coincidencia[1]), int(coincidencia[2])
    if horas > 24 or minutos > 59 or (horas == 24 and minutos > 0):
        raise ValueError(f"Hora fuera de rango: {hora!r}")
    return horas * 60 + minutos


def a_hhmm(minutos: int) -> str:
    """Convierte minutos desde medianoche a ``"HH:MM"``."""
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


class BloqueDoble(StrEnum):
    NO = "no"
    PREFERIDO = "preferido"
    OBLIGATORIO = "obligatorio"


class TipoDisponibilidad(StrEnum):
    DISPONIBLE = "disponible"
    PREFERIBLE_NO = "preferible_no"


class EstadoSolucion(StrEnum):
    OPTIMO = "OPTIMO"
    FACTIBLE = "FACTIBLE"
    INFACTIBLE = "INFACTIBLE"
    SIN_SOLUCION_EN_TIEMPO = "SIN_SOLUCION_EN_TIEMPO"
    CANCELADO = "CANCELADO"


class _Base(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


def _validar_rango(inicio: int, fin: int, que: str) -> None:
    if not (0 <= inicio < fin <= MINUTOS_DIA):
        raise ValueError(
            f"{que}: la hora de inicio ({a_hhmm(inicio)}) debe ser menor que la de fin "
            f"({a_hhmm(fin)})"
        )


def _validar_nombre(valor: str) -> str:
    valor = valor.strip()
    if not valor:
        raise ValueError("El nombre no puede estar vacío")
    return valor


class Pesos(_Base):
    """Pesos de las restricciones blandas B1–B8."""

    huecos_profesor: int = Field(10, ge=0)
    distribucion_semanal: int = Field(8, ge=0)
    exigente_tarde: int = Field(3, ge=0)
    preferible_no: int = Field(6, ge=0)
    dias_profesor: int = Field(2, ge=0)
    desequilibrio_carga: int = Field(1, ge=0)
    titular_preescolar: int = Field(5, ge=0)
    bloque_doble_preferido: int = Field(4, ge=0)


NOMBRES_PENALIZACIONES: dict[str, str] = {
    "huecos_profesor": "B1 Huecos de profesores",
    "distribucion_semanal": "B2 Mala distribución semanal",
    "exigente_tarde": "B3 Asignatura exigente después de media jornada",
    "preferible_no": "B4 Clase en franja «preferible no»",
    "dias_profesor": "B5 Días con clase por profesor",
    "desequilibrio_carga": "B6 Desequilibrio de carga",
    "titular_preescolar": "B7 Preescolar sin su titular",
    "bloque_doble_preferido": "B8 Horas no emparejadas (bloque doble preferido)",
}


class Configuracion(_Base):
    nombre_escuela: str = "Mi escuela"
    margen_traslado_min: int = Field(0, ge=0, le=120)
    tiempo_limite_s: int = Field(300, ge=1)
    hilos: int = Field(8, ge=1, le=64)
    pesos: Pesos = Field(default_factory=Pesos)

    _nombre = field_validator("nombre_escuela")(_validar_nombre)


class Receso(_Base):
    id: int | None = None
    nivel_id: int | None = None
    nombre: str = "Receso"
    inicio: int
    fin: int

    _nombre = field_validator("nombre")(_validar_nombre)

    @model_validator(mode="after")
    def _rango(self) -> Receso:
        _validar_rango(self.inicio, self.fin, f"Receso «{self.nombre}»")
        return self


class Nivel(_Base):
    id: int | None = None
    nombre: str
    duracion_min: int = Field(ge=5, le=240)
    inicio_jornada: int
    fin_jornada: int
    dias: list[str] = Field(default_factory=lambda: list(DIAS_SEMANA))
    recesos: list[Receso] = Field(default_factory=list)
    sin_huecos_alumnos: bool = False

    _nombre = field_validator("nombre")(_validar_nombre)

    @field_validator("dias")
    @classmethod
    def _dias(cls, dias: list[str]) -> list[str]:
        if not dias:
            raise ValueError("El nivel debe tener al menos un día lectivo")
        for dia in dias:
            if dia not in DIAS_VALIDOS:
                raise ValueError(f"Día inválido: {dia!r}")
        if len(set(dias)) != len(dias):
            raise ValueError("Hay días repetidos")
        return sorted(dias, key=DIAS_VALIDOS.index)

    @field_validator("fin_jornada")
    @classmethod
    def _rango(cls, fin: int, info: ValidationInfo) -> int:
        inicio = info.data.get("inicio_jornada")
        if inicio is not None:
            _validar_rango(inicio, fin, "Jornada")
        return fin

    @property
    def es_preescolar(self) -> bool:
        return self.nombre.strip().lower() == "preescolar"


class Grado(_Base):
    id: int | None = None
    nivel_id: int
    nombre: str

    _nombre = field_validator("nombre")(_validar_nombre)


class Grupo(_Base):
    id: int | None = None
    grado_id: int
    seccion: str
    estudiantes: int = Field(0, ge=0)
    titular_id: int | None = None

    _seccion = field_validator("seccion")(_validar_nombre)


class Asignatura(_Base):
    id: int | None = None
    nombre: str
    espacio_requerido: str | None = None
    max_horas_dia: int = Field(2, ge=1, le=12)
    bloque_doble: BloqueDoble = BloqueDoble.NO
    exigente: bool = False
    color: str = "#CCCCCC"

    _nombre = field_validator("nombre")(_validar_nombre)

    @field_validator("espacio_requerido")
    @classmethod
    def _espacio(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        valor = valor.strip()
        return valor or None

    @field_validator("color")
    @classmethod
    def _color(cls, valor: str) -> str:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", valor):
            raise ValueError(f"Color inválido: {valor!r}; use el formato #RRGGBB")
        return valor.upper()


class PlanEstudios(_Base):
    grado_id: int
    asignatura_id: int
    horas_semanales: int = Field(ge=0, le=100)


class Disponibilidad(_Base):
    id: int | None = None
    dia: str
    inicio: int
    fin: int
    tipo: TipoDisponibilidad = TipoDisponibilidad.DISPONIBLE

    @field_validator("dia")
    @classmethod
    def _dia(cls, dia: str) -> str:
        if dia not in DIAS_VALIDOS:
            raise ValueError(f"Día inválido: {dia!r}")
        return dia

    @model_validator(mode="after")
    def _rango(self) -> Disponibilidad:
        _validar_rango(self.inicio, self.fin, "Disponibilidad")
        return self


class Profesor(_Base):
    id: int | None = None
    nombre: str
    asignaturas: set[int] = Field(default_factory=set)
    grados: set[int] = Field(default_factory=set)
    disponibilidad: list[Disponibilidad] = Field(default_factory=list)
    carga_max_semanal_min: int = Field(2400, ge=0)
    carga_max_diaria_min: int = Field(480, ge=0)
    max_consecutivas: int = Field(4, ge=1)

    _nombre = field_validator("nombre")(_validar_nombre)


class Espacio(_Base):
    id: int | None = None
    nombre: str
    tipo: str
    cantidad: int = Field(1, ge=0)

    _nombre = field_validator("nombre")(_validar_nombre)
    _tipo = field_validator("tipo")(_validar_nombre)


class AsignacionFija(_Base):
    id: int | None = None
    grupo_id: int
    asignatura_id: int
    profesor_id: int | None = None
    dia: str
    indice_franja: int = Field(ge=0)


class Franja(_Base):
    """Franja horaria generada (no se guarda). ``receso_antes`` indica que entre esta
    franja y la anterior del mismo día hay un receso o un intervalo libre."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nivel_id: int
    dia: str
    indice: int
    inicio: int
    fin: int
    receso_antes: bool = False

    @property
    def id(self) -> str:
        return clave_franja(self.nivel_id, self.dia, self.indice)

    @property
    def duracion(self) -> int:
        return self.fin - self.inicio


def clave_franja(nivel_id: int, dia: str, indice: int) -> str:
    return f"{nivel_id}:{dia}:{indice}"


class Asignacion(_Base):
    solucion_id: int | None = None
    grupo_id: int
    asignatura_id: int
    profesor_id: int
    nivel_id: int
    dia: str
    indice: int

    @property
    def franja_id(self) -> str:
        return clave_franja(self.nivel_id, self.dia, self.indice)


class Solucion(_Base):
    id: int | None = None
    fecha: datetime = Field(default_factory=lambda: datetime.now().replace(microsecond=0))
    estado: EstadoSolucion
    tiempo_s: float = 0.0
    penalizaciones: dict[str, int] = Field(default_factory=dict)
    nota: str = ""
    asignaciones: list[Asignacion] = Field(default_factory=list)


class DatosEscuela(_Base):
    """Todos los datos de un proyecto, tal como los consume el núcleo."""

    configuracion: Configuracion = Field(default_factory=Configuracion)
    niveles: list[Nivel] = Field(default_factory=list)
    grados: list[Grado] = Field(default_factory=list)
    grupos: list[Grupo] = Field(default_factory=list)
    asignaturas: list[Asignatura] = Field(default_factory=list)
    plan: list[PlanEstudios] = Field(default_factory=list)
    profesores: list[Profesor] = Field(default_factory=list)
    espacios: list[Espacio] = Field(default_factory=list)
    asignaciones_fijas: list[AsignacionFija] = Field(default_factory=list)

    # --- Búsquedas de conveniencia -------------------------------------------------

    def nivel(self, nivel_id: int) -> Nivel:
        return next(n for n in self.niveles if n.id == nivel_id)

    def grado(self, grado_id: int) -> Grado:
        return next(g for g in self.grados if g.id == grado_id)

    def grupo(self, grupo_id: int) -> Grupo:
        return next(g for g in self.grupos if g.id == grupo_id)

    def asignatura(self, asignatura_id: int) -> Asignatura:
        return next(a for a in self.asignaturas if a.id == asignatura_id)

    def profesor(self, profesor_id: int) -> Profesor:
        return next(p for p in self.profesores if p.id == profesor_id)

    def nivel_de_grupo(self, grupo: Grupo) -> Nivel:
        return self.nivel(self.grado(grupo.grado_id).nivel_id)

    def nombre_grupo(self, grupo: Grupo) -> str:
        return f"{self.grado(grupo.grado_id).nombre}{grupo.seccion}"

    def plan_de_grado(self, grado_id: int) -> dict[int, int]:
        """Asignatura → horas semanales (solo las mayores que cero)."""
        return {
            p.asignatura_id: p.horas_semanales
            for p in self.plan
            if p.grado_id == grado_id and p.horas_semanales > 0
        }

    def capacidad_espacios(self) -> dict[str, int]:
        """Tipo de espacio → cantidad total disponible."""
        capacidad: dict[str, int] = {}
        for espacio in self.espacios:
            capacidad[espacio.tipo] = capacidad.get(espacio.tipo, 0) + espacio.cantidad
        return capacidad
