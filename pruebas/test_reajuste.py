"""Creado con Claude. Horario vigente, reajuste con cambios mínimos (B9) y comparación."""

from collections import Counter
from pathlib import Path

from timetabling.dominio.comparacion import (
    TipoCambio,
    claves_cambiadas,
    comparar,
    filas_cambios,
    profesores_afectados,
)
from timetabling.dominio.modelos import (
    Asignacion,
    DatosEscuela,
    EstadoSolucion,
    Solucion,
)
from timetabling.ejemplo import Tamano, construir_datos
from timetabling.exportacion.excel import exportar_excel
from timetabling.nucleo.franjas import generar_franjas
from timetabling.nucleo.resolver import resolver
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.repositorio import Repositorio


def _a(g: int, a: int, p: int, dia: str, i: int) -> Asignacion:
    return Asignacion(grupo_id=g, asignatura_id=a, profesor_id=p, nivel_id=1, dia=dia, indice=i)


# --- Comparación -------------------------------------------------------------------


def test_comparar_clasifica_los_cambios() -> None:
    antes = [_a(1, 1, 1, "L", 0), _a(1, 1, 1, "L", 1), _a(1, 2, 2, "M", 0), _a(2, 2, 2, "L", 2)]
    despues = [
        _a(1, 1, 3, "L", 0),  # mismo lugar, otro profesor
        _a(1, 1, 1, "M", 2),  # mismo profesor, otra hora
        _a(1, 2, 3, "L", 2),  # otra hora y otro profesor
        _a(2, 2, 2, "L", 2),  # sin cambios
        _a(2, 1, 1, "M", 1),  # nueva
    ]
    cambios = comparar(antes, despues)
    tipos = sorted(c.tipo for c in cambios)
    assert tipos == sorted(
        [TipoCambio.PROFESOR, TipoCambio.HORA, TipoCambio.HORA_Y_PROFESOR, TipoCambio.AGREGADA]
    )
    assert profesores_afectados(cambios) == {1, 2, 3}
    assert len(claves_cambiadas(antes, despues)) == 4
    assert comparar(antes, antes) == []
    quitada = comparar(antes, antes[1:])
    assert [c.tipo for c in quitada] == [TipoCambio.QUITADA]


def test_filas_cambios_legibles(minima: DatosEscuela) -> None:
    franjas = generar_franjas(minima)
    cambios = comparar([_a(1, 1, 1, "L", 0)], [_a(1, 1, 3, "L", 0)])
    assert filas_cambios(minima, franjas, cambios) == [
        ["1°A", "Matemáticas", "Cambio de profesor", "Lunes 08:00 · Ana", "Lunes 08:00 · Carmen"]
    ]


# --- Persistencia --------------------------------------------------------------------


def test_solucion_vigente(tmp_path: Path, minima: DatosEscuela) -> None:
    with Repositorio.crear(tmp_path / "p.horario") as repo:
        repo.reemplazar_datos(minima)
        s1 = repo.guardar_solucion(Solucion(estado=EstadoSolucion.OPTIMO))
        s2 = repo.guardar_solucion(Solucion(estado=EstadoSolucion.OPTIMO))
        assert repo.solucion_vigente_id() is None
        repo.marcar_vigente(s1.id)
        assert repo.solucion_vigente_id() == s1.id
        repo.marcar_vigente(s2.id)  # solo una a la vez
        assert repo.solucion_vigente_id() == s2.id
        assert [s.vigente for s in repo.listar_soluciones()] == [True, False]
        repo.eliminar_solucion(s2.id)
        assert repo.solucion_vigente_id() is None


# --- Resolución ----------------------------------------------------------------------


def test_reajuste_sin_cambios_en_los_datos_conserva_el_horario(minima: DatosEscuela) -> None:
    base = resolver(minima).asignaciones
    reajuste = resolver(minima, base=base)
    assert verificar(minima, reajuste.asignaciones) == []
    assert comparar(base, reajuste.asignaciones) == []
    assert reajuste.penalizaciones.get("cambios_vigente") == 0


def test_reajuste_tras_cambio_de_personal_mueve_poco() -> None:
    """Una profesora se va y llega una sustituta con la misma disponibilidad: el reajuste
    solo cambia el profesor de esas clases, sin mover nada más."""
    datos = construir_datos(Tamano.PEQUENO)
    datos.configuracion.hilos = 4
    base = resolver(datos, tiempo_limite_s=10).asignaciones
    assert base

    conteo = Counter(a.profesor_id for a in base)
    sale_id = max(conteo, key=lambda p: conteo[p])
    sale = next(p for p in datos.profesores if p.id == sale_id)
    entra = sale.model_copy(update={"id": 999, "nombre": "Sustituta"})
    datos.profesores = [entra if p.id == sale_id else p for p in datos.profesores]
    for grupo in datos.grupos:
        if grupo.titular_id == sale_id:
            grupo.titular_id = entra.id

    reajuste = resolver(datos, tiempo_limite_s=15, base=base)
    assert reajuste.asignaciones, reajuste.estado
    assert verificar(datos, reajuste.asignaciones) == []
    cambios = comparar(base, reajuste.asignaciones)
    assert len(cambios) == conteo[sale_id]
    assert {c.tipo for c in cambios} == {TipoCambio.PROFESOR}
    assert profesores_afectados(cambios) == {sale_id, entra.id}
    assert reajuste.penalizaciones["cambios_vigente"] == conteo[sale_id]

    # Generar desde cero, en cambio, reacomoda buena parte del horario.
    desde_cero = resolver(datos, tiempo_limite_s=10).asignaciones
    assert len(comparar(base, desde_cero)) > len(cambios)


def test_exportar_hoja_de_cambios(tmp_path: Path, minima: DatosEscuela) -> None:
    import openpyxl

    base = resolver(minima).asignaciones
    nueva = [a.model_copy(update={"profesor_id": 3}) if a.asignatura_id == 1 else a for a in base]
    solucion = Solucion(estado=EstadoSolucion.OPTIMO, asignaciones=nueva)
    franjas = generar_franjas(minima)
    destino = exportar_excel(
        minima, solucion, franjas, tmp_path / "h.xlsx", cambios=comparar(base, nueva)
    )
    hoja = openpyxl.load_workbook(destino)["Cambios"]
    assert hoja.cell(1, 1).value == "Grupo"
    assert hoja.max_row - 1 == sum(a.asignatura_id == 1 and a.profesor_id != 3 for a in base)
