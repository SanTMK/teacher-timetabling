"""Creado con Claude. Profesor fijo por grupo: persistencia, solver, verificación, validación,
pantalla e importación desde el cuadro de maestros."""

import sqlite3
from pathlib import Path

import openpyxl
import pytest
from pytestqt.qtbot import QtBot

from timetabling.dominio.modelos import (
    Asignacion,
    AsignacionFija,
    DatosEscuela,
    DocenteAsignado,
    EstadoSolucion,
)
from timetabling.importacion.maestros_excel import (
    importar,
    leer_celda,
    leer_libro,
    nombre_maestro,
)
from timetabling.nucleo.resolver import resolver
from timetabling.nucleo.validacion import Severidad, validar
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.repositorio import Repositorio


def test_solver_respeta_profesor_asignado(minima: DatosEscuela) -> None:
    # Ana y Carmen pueden dar Matemáticas a 1A; se fija a Carmen.
    minima.docentes_asignados = [DocenteAsignado(grupo_id=1, asignatura_id=1, profesor_id=3)]
    resultado = resolver(minima)
    assert resultado.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE)
    assert verificar(minima, resultado.asignaciones) == []
    assert {
        a.profesor_id for a in resultado.asignaciones if a.grupo_id == 1 and a.asignatura_id == 1
    } == {3}


def test_asignado_sin_disponibilidad_es_infactible(minima: DatosEscuela) -> None:
    minima.profesor(3).disponibilidad = []
    minima.docentes_asignados = [DocenteAsignado(grupo_id=1, asignatura_id=1, profesor_id=3)]
    assert resolver(minima).estado == EstadoSolucion.INFACTIBLE


def test_verificador_d14(minima: DatosEscuela) -> None:
    minima.docentes_asignados = [DocenteAsignado(grupo_id=1, asignatura_id=1, profesor_id=3)]
    sol = [
        Asignacion(grupo_id=1, asignatura_id=1, profesor_id=1, nivel_id=1, dia=d, indice=0)
        for d in ("L", "M")
    ]
    assert "D14" in {v.codigo for v in verificar(minima, sol)}


def test_validacion_profesor_asignado(minima: DatosEscuela) -> None:
    # Bruno no está habilitado para Matemáticas.
    minima.docentes_asignados = [DocenteAsignado(grupo_id=1, asignatura_id=1, profesor_id=2)]
    errores = [p for p in validar(minima) if p.severidad == Severidad.ERROR]
    assert any("no está habilitado" in p.mensaje for p in errores)

    # Choque con una clase fija de otro profesor.
    minima.docentes_asignados = [DocenteAsignado(grupo_id=1, asignatura_id=1, profesor_id=3)]
    minima.asignaciones_fijas = [
        AsignacionFija(grupo_id=1, asignatura_id=1, profesor_id=1, dia="L", indice_franja=0)
    ]
    assert any("clase fija" in p.mensaje for p in validar(minima))

    # Carga asignada mayor que la carga máxima.
    minima.asignaciones_fijas = []
    minima.docentes_asignados = [
        DocenteAsignado(grupo_id=1, asignatura_id=1, profesor_id=3),
        DocenteAsignado(grupo_id=2, asignatura_id=1, profesor_id=3),
    ]
    minima.profesor(3).carga_max_semanal_min = 180
    assert any("carga máxima" in p.mensaje for p in validar(minima))


def test_persistencia_y_migracion(tmp_path: Path, minima: DatosEscuela) -> None:
    ruta = tmp_path / "escuela.horario"
    minima.docentes_asignados = [DocenteAsignado(grupo_id=1, asignatura_id=1, profesor_id=3)]
    with Repositorio.crear(ruta) as repo:
        repo.reemplazar_datos(minima)
        assert repo.cargar_datos().docentes_asignados == minima.docentes_asignados
        repo.asignar_docente(DocenteAsignado(grupo_id=1, asignatura_id=1, profesor_id=1))
        assert repo.listar_docentes_asignados()[0].profesor_id == 1
        assert repo.afectados_por_eliminar("profesores", 1)["clases asignadas"] == 1
        repo.quitar_docente(1, 1)
        assert repo.listar_docentes_asignados() == []

    # Un proyecto de la versión 2 recibe la tabla al abrirse.
    conexion = sqlite3.connect(ruta)
    conexion.execute("DROP TABLE docentes_asignados")
    conexion.execute("UPDATE esquema_version SET version = 2")
    conexion.commit()
    conexion.close()
    with Repositorio.abrir(ruta) as repo:
        assert repo.listar_docentes_asignados() == []


def test_pantalla_profesores_por_grupo(qtbot: QtBot, tmp_path: Path, minima: DatosEscuela) -> None:
    from PySide6.QtCore import QSettings

    from timetabling.gui.app import VentanaPrincipal
    from timetabling.gui.pantallas.docentes import PantallaDocentes

    ruta = tmp_path / "escuela.horario"
    with Repositorio.crear(ruta) as repo:
        repo.reemplazar_datos(minima)
    ventana = VentanaPrincipal(QSettings(str(tmp_path / "a.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(ventana)
    ventana.abrir_proyecto(ruta)
    pantalla = ventana.mostrar("docentes")
    assert isinstance(pantalla, PantallaDocentes)
    assert pantalla.tabla.rowCount() == 2
    assert [n for _, n in pantalla.candidatos(1, 1)] == ["Ana", "Carmen"]
    pantalla.asignar(1, 1, 3)
    assert "0 de 4" not in pantalla.resumen.text()
    with Repositorio.abrir(ruta) as repo:
        assert repo.listar_docentes_asignados() == [
            DocenteAsignado(grupo_id=1, asignatura_id=1, profesor_id=3)
        ]
    pantalla.asignar(1, 1, None)
    with Repositorio.abrir(ruta) as repo:
        assert repo.listar_docentes_asignados() == []


# --- Importación del cuadro de maestros ---------------------------------------------


def test_leer_celda_y_nombres() -> None:
    celda = leer_celda("ESPAÑOL 3A")
    assert celda is not None and celda.asignatura == "ESPAÑOL" and celda.grupos == ["3A"]
    celda = leer_celda("Math Ppa")
    assert celda is not None and celda.grupos == ["PPA"] and celda.asignatura == "Math"
    celda = leer_celda("8A (8:00-8:45)")
    assert celda is not None and celda.asignatura is None and celda.grupos == ["8A"]
    celda = leer_celda("GYM1B")
    assert celda is not None and celda.grupos == ["1B"] and celda.asignatura == "Gym"
    celda = leer_celda("Grammar/Vocabulary")
    assert celda is not None and celda.asignatura == "Grammar/Vocabulary" and celda.grupos == []
    assert leer_celda("Lunch") is None
    assert nombre_maestro("MS. MINSY") == nombre_maestro("Ms.Minsy") == "Ms. Minsy"


def _bloque(
    hoja: openpyxl.worksheet.worksheet.Worksheet,
    fila: int,
    nombre: str,
    celdas: list[list[str | None]],
) -> None:
    hoja.cell(fila, 4, nombre)
    for k, dia in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]):
        hoja.cell(fila + 1, 2 + k, dia)
    for i, valores in enumerate(celdas):
        hoja.cell(fila + 2 + i, 1, f"{8 + i}:00-{8 + i}:50")
        for k, valor in enumerate(valores):
            if valor:
                hoja.cell(fila + 2 + i, 2 + k, valor)


@pytest.fixture
def proyecto(tmp_path: Path, minima: DatosEscuela) -> Path:
    minima.profesores = []
    minima.grados[0].nombre = "Primero"
    ruta = tmp_path / "escuela.horario"
    with Repositorio.crear(ruta) as repo:
        repo.reemplazar_datos(minima)
    return ruta


def test_importar_maestros(tmp_path: Path, proyecto: Path) -> None:
    libro = openpyxl.Workbook()
    hoja = libro.active
    _bloque(
        hoja,
        1,
        "MS. ANA",
        [
            ["Matemáticas 1A", "MATEMÁTICAS 1B", None, None, None],
            ["Matemáticas 1A", "Matemáticas 1B", "Lunch", None, None],
        ],
    )
    _bloque(
        hoja,
        6,
        "Mr. Bruno",
        [["1A", "1A", None, None, None], ["1B", "1B", "ENTRENAMIENTO", None, None]],
    )
    excel = tmp_path / "maestros.xlsx"
    libro.save(excel)

    with Repositorio.abrir(proyecto) as repo:
        informe = importar(repo, leer_libro(excel))
        datos = repo.cargar_datos()

    assert sorted(informe.profesores_nuevos) == ["Mr. Bruno", "Ms. Ana"]
    ana = next(p for p in datos.profesores if p.nombre == "Ms. Ana")
    bruno = next(p for p in datos.profesores if p.nombre == "Mr. Bruno")
    assert ana.asignaturas == {1} and ana.grados == {1}
    # Bruno solo anota el grupo: se deduce Español (la única de 2 h sin maestro).
    assert bruno.asignaturas == {2}
    assert datos.docente_asignado(1, 1) == ana.id
    assert datos.docente_asignado(2, 2) == bruno.id
    assert any("ENTRENAMIENTO" in a for a in informe.avisos)
    assert ana.disponibilidad  # disponible toda la jornada por defecto
    assert not [p for p in validar(datos) if p.severidad == Severidad.ERROR]

    # Reimportar no duplica.
    with Repositorio.abrir(proyecto) as repo:
        importar(repo, leer_libro(excel))
        de_nuevo = repo.cargar_datos()
    assert len(de_nuevo.profesores) == 2
    assert de_nuevo.docentes_asignados == datos.docentes_asignados
