"""Creado con Claude. Diferencias entre dos horarios (p. ej. el vigente y un reajuste).

Cada clase se identifica por grupo, asignatura, profesor y franja. Las clases que solo
están en uno de los dos horarios se emparejan dentro de cada (grupo, asignatura) para
describir el cambio de la forma más natural:

1. misma hora, otro profesor → «cambio de profesor»;
2. mismo profesor, otra hora → «cambio de hora»;
3. lo demás, por orden → «cambio de hora y profesor».

Lo que no se puede emparejar queda como clase quitada o agregada.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from timetabling.dominio.modelos import (
    DIAS_VALIDOS,
    NOMBRES_DIAS,
    Asignacion,
    DatosEscuela,
    Franja,
    a_hhmm,
)

ClaveClase = tuple[int, int, int, int, str, int]  # grupo, asignatura, profesor, nivel, día, índice


class TipoCambio(StrEnum):
    PROFESOR = "Cambio de profesor"
    HORA = "Cambio de hora"
    HORA_Y_PROFESOR = "Cambio de hora y profesor"
    QUITADA = "Clase quitada"
    AGREGADA = "Clase agregada"


@dataclass(frozen=True)
class Cambio:
    grupo_id: int
    asignatura_id: int
    antes: Asignacion | None
    despues: Asignacion | None

    @property
    def tipo(self) -> TipoCambio:
        if self.antes is None:
            return TipoCambio.AGREGADA
        if self.despues is None:
            return TipoCambio.QUITADA
        misma_hora = _hora(self.antes) == _hora(self.despues)
        if misma_hora:
            return TipoCambio.PROFESOR
        if self.antes.profesor_id == self.despues.profesor_id:
            return TipoCambio.HORA
        return TipoCambio.HORA_Y_PROFESOR

    @property
    def profesores(self) -> set[int]:
        """Profesores afectados: el de antes y el de después."""
        return {a.profesor_id for a in (self.antes, self.despues) if a is not None}


def clave(a: Asignacion) -> ClaveClase:
    return (a.grupo_id, a.asignatura_id, a.profesor_id, a.nivel_id, a.dia, a.indice)


def _hora(a: Asignacion) -> tuple[int, str, int]:
    return (a.nivel_id, a.dia, a.indice)


def _orden(a: Asignacion) -> tuple[int, int, int]:
    dia = DIAS_VALIDOS.index(a.dia) if a.dia in DIAS_VALIDOS else len(DIAS_VALIDOS)
    return (dia, a.indice, a.profesor_id)


def comparar(antes: list[Asignacion], despues: list[Asignacion]) -> list[Cambio]:
    """Cambios para pasar de ``antes`` a ``despues``, ordenados por grupo y asignatura."""
    claves_antes = {clave(a) for a in antes}
    claves_despues = {clave(a) for a in despues}
    quitadas: dict[tuple[int, int], list[Asignacion]] = defaultdict(list)
    agregadas: dict[tuple[int, int], list[Asignacion]] = defaultdict(list)
    for a in antes:
        if clave(a) not in claves_despues:
            quitadas[(a.grupo_id, a.asignatura_id)].append(a)
    for a in despues:
        if clave(a) not in claves_antes:
            agregadas[(a.grupo_id, a.asignatura_id)].append(a)

    cambios: list[Cambio] = []
    for ga in sorted(set(quitadas) | set(agregadas)):
        viejas = sorted(quitadas.get(ga, []), key=_orden)
        nuevas = sorted(agregadas.get(ga, []), key=_orden)
        pares: list[tuple[Asignacion | None, Asignacion | None]] = []
        for criterio in (_hora, lambda a: a.profesor_id):
            for vieja in list(viejas):
                nueva = next((n for n in nuevas if criterio(n) == criterio(vieja)), None)
                if nueva is not None:
                    pares.append((vieja, nueva))
                    viejas.remove(vieja)
                    nuevas.remove(nueva)
        pares += list(zip(viejas, nuevas, strict=False))
        n = min(len(viejas), len(nuevas))
        pares += [(v, None) for v in viejas[n:]] + [(None, a) for a in nuevas[n:]]
        pares.sort(key=lambda par: _orden(par[0] or par[1]))  # type: ignore[arg-type]
        cambios += [Cambio(ga[0], ga[1], v, a) for v, a in pares]
    return cambios


def claves_cambiadas(antes: list[Asignacion], despues: list[Asignacion]) -> set[ClaveClase]:
    """Clases de ``despues`` que no estaban igual en ``antes`` (para resaltarlas)."""
    claves_antes = {clave(a) for a in antes}
    return {clave(a) for a in despues if clave(a) not in claves_antes}


def profesores_afectados(cambios: list[Cambio]) -> set[int]:
    return set().union(*(c.profesores for c in cambios)) if cambios else set()


ENCABEZADOS_CAMBIOS = ["Grupo", "Asignatura", "Cambio", "Antes", "Después"]


def filas_cambios(
    datos: DatosEscuela, franjas: list[Franja], cambios: list[Cambio]
) -> list[list[str]]:
    """Cambios en texto legible, con las columnas de ``ENCABEZADOS_CAMBIOS``."""
    por_clave = {f.id: f for f in franjas}

    def describir(a: Asignacion | None) -> str:
        if a is None:
            return "—"
        dia = NOMBRES_DIAS.get(a.dia, a.dia)
        franja = por_clave.get(a.franja_id)
        hora = a_hhmm(franja.inicio) if franja else f"hora {a.indice + 1}"
        profesor = next((p.nombre for p in datos.profesores if p.id == a.profesor_id), "?")
        return f"{dia} {hora} · {profesor}"

    grupos = {g.id: datos.nombre_grupo(g) for g in datos.grupos}
    asignaturas = {a.id: a.nombre for a in datos.asignaturas}
    return [
        [
            grupos.get(c.grupo_id, "?"),
            asignaturas.get(c.asignatura_id, "?"),
            c.tipo.value,
            describir(c.antes),
            describir(c.despues),
        ]
        for c in cambios
    ]
