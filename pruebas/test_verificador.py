"""Creado con Claude. El verificador detecta cada restricción dura violada, una por una."""

from timetabling.dominio.modelos import (
    Asignacion,
    AsignacionFija,
    BloqueDoble,
    DatosEscuela,
    Disponibilidad,
    Espacio,
    a_minutos,
)
from timetabling.nucleo.verificador import verificar


def _a(g: int, a: int, p: int, dia: str, i: int) -> Asignacion:
    return Asignacion(grupo_id=g, asignatura_id=a, profesor_id=p, nivel_id=1, dia=dia, indice=i)


def solucion_valida() -> list[Asignacion]:
    # Franjas: 08-09 (0), 09-10 (1), 10-11 (2), lunes y martes.
    return [
        _a(1, 1, 1, "L", 0),
        _a(1, 1, 1, "M", 0),  # 1A Matemáticas con Ana
        _a(1, 2, 2, "L", 1),
        _a(1, 2, 2, "M", 1),  # 1A Español con Bruno
        _a(2, 1, 3, "L", 1),
        _a(2, 1, 3, "M", 1),  # 1B Matemáticas con Carmen
        _a(2, 2, 2, "L", 0),
        _a(2, 2, 2, "M", 0),  # 1B Español con Bruno
    ]


def _codigos(datos: DatosEscuela, asignaciones: list[Asignacion]) -> set[str]:
    return {v.codigo for v in verificar(datos, asignaciones)}


def test_solucion_valida_sin_violaciones(minima: DatosEscuela) -> None:
    assert verificar(minima, solucion_valida()) == []


def test_d1_horas_faltantes(minima: DatosEscuela) -> None:
    assert "D1" in _codigos(minima, solucion_valida()[1:])


def test_d1_franja_inexistente(minima: DatosEscuela) -> None:
    sol = solucion_valida()
    sol[0] = _a(1, 1, 1, "L", 7)
    assert "D1" in _codigos(minima, sol)


def test_d2_dos_clases_misma_franja(minima: DatosEscuela) -> None:
    sol = solucion_valida()
    sol[2] = _a(1, 2, 2, "L", 0)  # Español de 1A choca con Matemáticas de 1A
    assert "D2" in _codigos(minima, sol)


def test_d3_profesor_en_dos_lugares(minima: DatosEscuela) -> None:
    sol = solucion_valida()
    sol[2] = _a(1, 2, 2, "L", 0)  # Bruno a las 8 en 1A y en 1B
    assert "D3" in _codigos(minima, sol)


def test_d4_profesor_no_habilitado(minima: DatosEscuela) -> None:
    sol = solucion_valida()
    sol[0:2] = [_a(1, 1, 2, "L", 0), _a(1, 1, 2, "M", 0)]  # Bruno no da Matemáticas
    assert "D4" in _codigos(minima, sol)


def test_d5_fuera_de_disponibilidad(minima: DatosEscuela) -> None:
    ana = minima.profesor(1)
    ana.disponibilidad = [
        Disponibilidad(dia="L", inicio=a_minutos("08:00"), fin=a_minutos("08:30")),
        Disponibilidad(dia="M", inicio=a_minutos("08:00"), fin=a_minutos("11:00")),
    ]
    assert _codigos(minima, solucion_valida()) == {"D5"}


def test_d6_dos_profesores_misma_asignatura(minima: DatosEscuela) -> None:
    sol = solucion_valida()
    sol[1] = _a(1, 1, 3, "M", 0)  # Matemáticas de 1A: Ana el lunes, Carmen el martes
    assert "D6" in _codigos(minima, sol)


def test_d7_carga_semanal_y_diaria(minima: DatosEscuela) -> None:
    minima.profesor(2).carga_max_semanal_min = 180
    minima.profesor(2).carga_max_diaria_min = 60
    violaciones = verificar(minima, solucion_valida())
    assert {v.codigo for v in violaciones} == {"D7"}
    assert len(violaciones) == 3  # semanal + lunes + martes


def test_d13_fija_no_respetada(minima: DatosEscuela) -> None:
    minima.asignaciones_fijas = [
        AsignacionFija(grupo_id=1, asignatura_id=1, profesor_id=1, dia="L", indice_franja=2)
    ]
    assert _codigos(minima, solucion_valida()) == {"D13"}
    minima.asignaciones_fijas = [
        AsignacionFija(grupo_id=1, asignatura_id=1, dia="L", indice_franja=0)
    ]
    assert verificar(minima, solucion_valida()) == []


def test_d8_demasiadas_consecutivas(minima: DatosEscuela) -> None:
    minima.profesor(2).max_consecutivas = 1  # Bruno: 1B a las 8 y 1A a las 9
    assert _codigos(minima, solucion_valida()) == {"D8"}


def test_d9_capacidad_de_espacios(minima: DatosEscuela) -> None:
    minima.asignatura(1).espacio_requerido = "taller"
    minima.asignatura(2).espacio_requerido = "taller"
    minima.espacios = [Espacio(nombre="Taller", tipo="taller", cantidad=1)]
    assert _codigos(minima, solucion_valida()) == {"D9"}
    minima.espacios[0].cantidad = 2
    assert verificar(minima, solucion_valida()) == []


def test_d10_maximo_diario_y_consecutivas(minima: DatosEscuela) -> None:
    sol = solucion_valida()
    sol[1] = _a(1, 1, 1, "L", 2)  # Matemáticas de 1A a las 8 y a las 10
    assert _codigos(minima, sol) == {"D10"}  # máximo 2, pero no consecutivas
    minima.asignatura(1).max_horas_dia = 1
    assert _codigos(minima, sol) == {"D10"}


def test_d11_bloque_doble_obligatorio(minima: DatosEscuela) -> None:
    minima.asignatura(1).bloque_doble = BloqueDoble.OBLIGATORIO
    assert _codigos(minima, solucion_valida()) == {"D11"}


def test_d12_huecos_de_alumnos(minima: DatosEscuela) -> None:
    minima.niveles[0].sin_huecos_alumnos = True
    assert verificar(minima, solucion_valida()) == []
    sol = solucion_valida()
    sol[2] = _a(1, 2, 2, "L", 2)  # 1A: 8:00 y 10:00, hueco a las 9
    assert _codigos(minima, sol) == {"D12"}
