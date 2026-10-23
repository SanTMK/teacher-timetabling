"""Creado con Claude. Datos mínimos compartidos por las pruebas del núcleo."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from timetabling.dominio.modelos import (
    Asignatura,
    Configuracion,
    DatosEscuela,
    Disponibilidad,
    Grado,
    Grupo,
    Nivel,
    PlanEstudios,
    Profesor,
    a_minutos,
)


def escuela_minima() -> DatosEscuela:
    """Un nivel (L, M; 08:00–11:00, franjas de 60 min), un grado con dos grupos,
    Matemáticas (2 h) y Español (2 h), tres profesores."""
    todo = [
        Disponibilidad(dia=d, inicio=a_minutos("08:00"), fin=a_minutos("11:00")) for d in ("L", "M")
    ]
    return DatosEscuela(
        configuracion=Configuracion(nombre_escuela="Mínima", tiempo_limite_s=20, hilos=4),
        niveles=[
            Nivel(
                id=1,
                nombre="Primaria",
                duracion_min=60,
                inicio_jornada=a_minutos("08:00"),
                fin_jornada=a_minutos("11:00"),
                dias=["L", "M"],
            )
        ],
        grados=[Grado(id=1, nivel_id=1, nombre="1°")],
        grupos=[Grupo(id=1, grado_id=1, seccion="A"), Grupo(id=2, grado_id=1, seccion="B")],
        asignaturas=[
            Asignatura(id=1, nombre="Matemáticas", max_horas_dia=2),
            Asignatura(id=2, nombre="Español", max_horas_dia=2),
        ],
        plan=[
            PlanEstudios(grado_id=1, asignatura_id=1, horas_semanales=2),
            PlanEstudios(grado_id=1, asignatura_id=2, horas_semanales=2),
        ],
        profesores=[
            Profesor(id=1, nombre="Ana", asignaturas={1}, grados={1}, disponibilidad=todo),
            Profesor(id=2, nombre="Bruno", asignaturas={2}, grados={1}, disponibilidad=todo),
            Profesor(id=3, nombre="Carmen", asignaturas={1, 2}, grados={1}, disponibilidad=todo),
        ],
    )


@pytest.fixture
def minima() -> DatosEscuela:
    return escuela_minima()
