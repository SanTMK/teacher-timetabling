"""Creado con Claude. Pruebas de integración del modelo, el resolver y la CLI."""

import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from timetabling.cli import app
from timetabling.dominio.modelos import AsignacionFija, DatosEscuela, EstadoSolucion
from timetabling.ejemplo import Tamano, construir_datos
from timetabling.nucleo.resolver import Progreso, Resolutor, resolver
from timetabling.nucleo.validacion import hay_errores, validar
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.repositorio import Repositorio


def test_minima_se_resuelve_y_verifica(minima: DatosEscuela) -> None:
    resultado = resolver(minima)
    assert resultado.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE)
    assert len(resultado.asignaciones) == 8
    assert verificar(minima, resultado.asignaciones) == []


def test_asignacion_fija_se_respeta(minima: DatosEscuela) -> None:
    minima.asignaciones_fijas = [
        AsignacionFija(grupo_id=1, asignatura_id=2, profesor_id=3, dia="M", indice_franja=2)
    ]
    resultado = resolver(minima)
    assert verificar(minima, resultado.asignaciones) == []
    assert any(
        a.grupo_id == 1
        and a.asignatura_id == 2
        and a.profesor_id == 3
        and a.dia == "M"
        and a.indice == 2
        for a in resultado.asignaciones
    )


def test_infactible_por_carga(minima: DatosEscuela) -> None:
    for profesor in minima.profesores:
        profesor.carga_max_semanal_min = 60
    resultado = resolver(minima)
    assert resultado.estado == EstadoSolucion.INFACTIBLE
    assert resultado.asignaciones == []


def test_ejemplo_pequeno_de_punta_a_punta() -> None:
    datos = construir_datos(Tamano.PEQUENO)
    assert not hay_errores(validar(datos))
    progresos: list[Progreso] = []
    resultado = resolver(datos, tiempo_limite_s=10, al_progresar=progresos.append)
    assert resultado.tiene_solucion
    assert progresos
    assert verificar(datos, resultado.asignaciones) == []


def test_cancelar_conserva_estado() -> None:
    datos = construir_datos(Tamano.PEQUENO)
    resolutor = Resolutor(datos, tiempo_limite_s=60)
    resolutor.cancelar()
    resultado = resolutor.resolver()
    assert resultado.estado == EstadoSolucion.CANCELADO


def test_cancelar_desde_otro_hilo() -> None:
    datos = construir_datos(Tamano.MEDIANO)
    resolutor = Resolutor(datos, tiempo_limite_s=120)
    threading.Timer(3.0, resolutor.cancelar).start()
    resultado = resolutor.resolver()
    assert resultado.tiempo_s < 60
    if resultado.asignaciones:
        assert verificar(datos, resultado.asignaciones) == []


def test_cli_ejemplo_validar_generar(tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    runner = CliRunner()
    r = runner.invoke(app, ["ejemplo", str(ruta)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["validar", str(ruta)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["generar", str(ruta), "--tiempo-limite", "10"])
    assert r.exit_code == 0, r.output
    assert "verificada y guardada" in r.output
    with Repositorio.abrir(ruta) as repo:
        soluciones = repo.listar_soluciones()
        assert len(soluciones) == 1
        solucion = repo.cargar_solucion(soluciones[0].id)
        assert verificar(repo.cargar_datos(), solucion.asignaciones) == []


@pytest.mark.lento
def test_ejemplo_mediano_de_punta_a_punta() -> None:
    datos = construir_datos(Tamano.MEDIANO)
    assert not hay_errores(validar(datos))
    resultado = resolver(datos, tiempo_limite_s=60)
    assert resultado.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE)
    assert verificar(datos, resultado.asignaciones) == []
    assert set(resultado.penalizaciones) <= set(datos.configuracion.pesos.model_dump())
