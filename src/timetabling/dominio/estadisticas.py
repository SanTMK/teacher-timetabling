"""Creado con Claude. Estadísticas de una solución: carga docente y penalización total."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from timetabling.dominio.modelos import Asignacion, DatosEscuela, Franja, Pesos


@dataclass(frozen=True)
class CargaProfesor:
    profesor_id: int
    nombre: str
    minutos: int
    maximo: int
    dias: int
    huecos: int

    @property
    def porcentaje(self) -> float:
        return 100.0 * self.minutos / self.maximo if self.maximo else 0.0


def carga_docente(
    datos: DatosEscuela, franjas: list[Franja], asignaciones: list[Asignacion]
) -> list[CargaProfesor]:
    """Carga de cada profesor. Los huecos se cuentan por nivel y día: franjas libres entre la
    primera y la última clase (igual que la penalización B1)."""
    duracion = {(f.nivel_id, f.dia, f.indice): f.fin - f.inicio for f in franjas}
    minutos: dict[int, int] = defaultdict(int)
    dias: dict[int, set[str]] = defaultdict(set)
    indices: dict[tuple[int, int, str], list[int]] = defaultdict(list)
    for a in asignaciones:
        minutos[a.profesor_id] += duracion.get((a.nivel_id, a.dia, a.indice), 0)
        dias[a.profesor_id].add(a.dia)
        indices[(a.profesor_id, a.nivel_id, a.dia)].append(a.indice)
    huecos: dict[int, int] = defaultdict(int)
    for (p, _n, _d), lista in indices.items():
        huecos[p] += max(lista) - min(lista) + 1 - len(set(lista))
    return [
        CargaProfesor(
            profesor_id=p.id,
            nombre=p.nombre,
            minutos=minutos[p.id],
            maximo=p.carga_max_semanal_min,
            dias=len(dias[p.id]),
            huecos=huecos[p.id],
        )
        for p in datos.profesores
        if p.id is not None
    ]


def penalizacion_total(penalizaciones: dict[str, int], pesos: Pesos) -> int:
    valores = pesos.model_dump()
    return sum(valores.get(nombre, 0) * valor for nombre, valor in penalizaciones.items())
