"""Creado con Claude. Casos infactibles construidos a propósito y su diagnóstico."""

from timetabling.dominio.modelos import AsignacionFija, DatosEscuela, EstadoSolucion
from timetabling.nucleo.diagnostico import diagnosticar
from timetabling.nucleo.resolver import resolver


def test_fijas_que_chocan_por_profesor(minima: DatosEscuela) -> None:
    # Carmen fijada a la misma hora en 1A y en 1B.
    minima.asignaciones_fijas = [
        AsignacionFija(grupo_id=1, asignatura_id=1, profesor_id=3, dia="L", indice_franja=0),
        AsignacionFija(grupo_id=2, asignatura_id=2, profesor_id=3, dia="L", indice_franja=0),
    ]
    assert resolver(minima).estado == EstadoSolucion.INFACTIBLE
    conflictos = diagnosticar(minima)
    claves = {c.clave for c in conflictos}
    assert claves == {("fija", 0), ("fija", 1), ("profesor", 3)}
    assert any("Carmen no puede estar en dos clases a la vez" in c.mensaje for c in conflictos)


def test_carga_insuficiente(minima: DatosEscuela) -> None:
    # Bruno es el único que da Español además de Carmen; ambos con tope de 1 hora.
    minima.profesor(2).carga_max_semanal_min = 60
    minima.profesor(3).carga_max_semanal_min = 60
    conflictos = diagnosticar(minima)
    claves = {c.clave for c in conflictos}
    assert ("carga", 2) in claves and ("carga", 3) in claves
    assert len(claves) <= 5
    assert all(c.mensaje for c in conflictos)


def test_maximo_diario_imposible(minima: DatosEscuela) -> None:
    # 2 días lectivos, máximo 1 hora diaria, pero 3 horas semanales de Matemáticas.
    minima.asignatura(1).max_horas_dia = 1
    minima.plan[0].horas_semanales = 3
    conflictos = diagnosticar(minima)
    assert {c.clave[0] for c in conflictos} <= {"curricular", "diaria"}
    assert any(c.clave[0] == "diaria" for c in conflictos)
    assert any("máximo 1 hora por día" in c.mensaje for c in conflictos)


def test_factible_no_devuelve_conflictos(minima: DatosEscuela) -> None:
    assert diagnosticar(minima) == []
