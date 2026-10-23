"""Creado con Claude. Cada validación global produce un mensaje claro con datos defectuosos."""

from timetabling.dominio.modelos import (
    AsignacionFija,
    BloqueDoble,
    DatosEscuela,
    Disponibilidad,
    Espacio,
    Grado,
    Profesor,
    a_minutos,
)
from timetabling.ejemplo import Tamano, construir_datos
from timetabling.nucleo.validacion import Problema, Severidad, hay_errores, validar


def _mensajes(datos: DatosEscuela, severidad: Severidad | None = None) -> list[str]:
    return [p.mensaje for p in validar(datos) if severidad is None or p.severidad == severidad]


def test_datos_correctos_sin_problemas(minima: DatosEscuela) -> None:
    assert validar(minima) == []
    for tamano in Tamano:
        assert not hay_errores(validar(construir_datos(tamano)))


def test_1_asignatura_sin_profesor(minima: DatosEscuela) -> None:
    minima.profesor(2).asignaturas = set()
    minima.profesor(3).asignaturas = {1}
    problemas = [p for p in validar(minima) if p.severidad == Severidad.ERROR]
    assert len(problemas) == 1
    assert problemas[0].entidad == "plan"
    assert "Ningún profesor está habilitado para dar Español en 1°" in problemas[0].mensaje


def test_2_horas_no_caben(minima: DatosEscuela) -> None:
    minima.plan[0].horas_semanales = 5  # 5 + 2 > 6 franjas
    assert any(
        "suma 7 horas-clase, pero su nivel solo tiene 6 franjas" in m for m in _mensajes(minima)
    )


def test_3_capacidad_docente(minima: DatosEscuela) -> None:
    for profesor in minima.profesores:
        profesor.carga_max_semanal_min = 60
    mensajes = _mensajes(minima, Severidad.ERROR)
    assert (
        "Matemáticas en primaria requiere 240 min/semana; los profesores habilitados suman 120"
        in (mensajes)
    )


def test_3_formato_de_miles() -> None:
    datos = construir_datos(Tamano.MEDIANO)
    ingles = next(a for a in datos.asignaturas if a.nombre == "Inglés")
    for p in datos.profesores:
        if ingles.id in p.asignaturas:
            p.carga_max_semanal_min = 300
    assert any("Inglés en secundaria requiere 2.400 min/semana" in m for m in _mensajes(datos))


def test_4_rango_que_no_cubre_franjas(minima: DatosEscuela) -> None:
    minima.profesor(1).disponibilidad.append(
        Disponibilidad(dia="L", inicio=a_minutos("12:00"), fin=a_minutos("12:30"))
    )
    problemas = [p for p in validar(minima) if p.severidad == Severidad.ADVERTENCIA]
    assert len(problemas) == 1 and "Lunes 12:00–12:30" in problemas[0].mensaje
    assert not hay_errores(validar(minima))


def test_5_espacios_insuficientes(minima: DatosEscuela) -> None:
    minima.asignatura(1).espacio_requerido = "laboratorio"
    assert any("solo hay 0 espacio(s) × 6 franjas" in m for m in _mensajes(minima))
    minima.espacios = [Espacio(nombre="Lab", tipo="laboratorio", cantidad=1)]
    assert validar(minima) == []


def test_6_fijas_incoherentes(minima: DatosEscuela) -> None:
    minima.asignaciones_fijas = [
        AsignacionFija(grupo_id=1, asignatura_id=1, profesor_id=2, dia="L", indice_franja=0),
        AsignacionFija(grupo_id=1, asignatura_id=2, dia="L", indice_franja=9),
        AsignacionFija(grupo_id=1, asignatura_id=2, profesor_id=3, dia="M", indice_franja=0),
        AsignacionFija(grupo_id=2, asignatura_id=1, profesor_id=3, dia="M", indice_franja=0),
    ]
    mensajes = _mensajes(minima, Severidad.ERROR)
    assert "Bruno no está habilitado para Matemáticas en 1°" in mensajes
    assert any("La franja 10 del Lunes no existe" in m for m in mensajes)
    assert any("Choca con la fija #3: el profesor estaría en dos lugares" in m for m in mensajes)


def test_6_fija_fuera_de_disponibilidad(minima: DatosEscuela) -> None:
    minima.profesor(1).disponibilidad = [
        Disponibilidad(dia="M", inicio=a_minutos("08:00"), fin=a_minutos("11:00"))
    ]
    minima.asignaciones_fijas = [
        AsignacionFija(grupo_id=1, asignatura_id=1, profesor_id=1, dia="L", indice_franja=0)
    ]
    assert "Ana no está disponible el Lunes 08:00" in _mensajes(minima)


def test_7_maximo_diario_insuficiente(minima: DatosEscuela) -> None:
    minima.asignatura(1).max_horas_dia = 1
    minima.plan[0].horas_semanales = 3
    assert any("con un máximo de 1 por día y 2 días solo caben 2" in m for m in _mensajes(minima))


def test_bloque_doble_con_maximo_uno(minima: DatosEscuela) -> None:
    minima.asignatura(1).max_horas_dia = 1
    minima.asignatura(1).bloque_doble = BloqueDoble.OBLIGATORIO
    assert "Matemáticas exige bloque doble, pero su máximo diario es 1 hora" in _mensajes(minima)


def test_8_incompletos(minima: DatosEscuela) -> None:
    minima.grados.append(Grado(id=2, nivel_id=1, nombre="2°"))
    minima.profesores.append(Profesor(id=9, nombre="Nadie"))
    problemas: list[Problema] = validar(minima)
    assert all(p.severidad == Severidad.ADVERTENCIA for p in problemas)
    mensajes = [p.mensaje for p in problemas]
    assert "El grado 2° no tiene grupos" in mensajes
    assert "Nadie no tiene asignaturas" in mensajes
    assert "Nadie no tiene disponibilidad" in mensajes
