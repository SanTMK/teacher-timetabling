"""Creado con Claude. Pruebas de la importación del cuadro de horarios en Excel."""

from pathlib import Path

import openpyxl
import pytest

from timetabling.dominio.modelos import Asignatura, Grado, Nivel, Receso, a_minutos
from timetabling.importacion.horarios_excel import (
    importar,
    leer_hoja,
    leer_libro,
    nombre_asignatura,
)
from timetabling.persistencia.repositorio import Repositorio

DIAS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _hoja_dos_grupos() -> list[list[object]]:
    """Hoja con 1A y 1B al estilo del cuadro real (hora a la izquierda de cada bloque)."""
    vacia = [None] * 14
    filas = [list(vacia) for _ in range(12)]
    filas[1][6], filas[1][13] = "1A", "1B"
    for k, dia in enumerate(DIAS):
        filas[2][2 + k] = dia
        filas[2][9 + k] = dia
    horas = ["8:00-8:45", "8:45-9:30", "9:30-9:50", "12:40-1:20", "2:00-2:40"]
    contenido_a = [
        ["Math ", "Tecnologia", "Reading", "Math", None],
        ["Español", "Technology", "Valores", "Math", "Science  LAB"],
        ["Recess", None, None, None, None],
        ["Character", "Carácter", "Gym", "GYM", "Español"],
        ["Tutoria Math", None, "Reading Tutoring", None, None],
    ]
    contenido_b = [
        ["Math", "Math", "Reading", "Math", None],
        ["Español", "Tecnology", "Values", "Español", None],
        ["Recess", None, None, None, None],
        ["Carácter", None, "Gym", None, "Español"],
        [None, None, None, None, None],
    ]
    for i, hora in enumerate(horas):
        fila = filas[3 + i]
        fila[1], fila[8] = hora, hora
        for k in range(5):
            fila[2 + k] = contenido_a[i][k]
            fila[9 + k] = contenido_b[i][k]
    filas[9][1] = "Horarios de Examen es Alumnos"
    filas[10][2:7] = ["Math", "Math", "Math", "Math", "Math"]
    return filas


def test_nombres_unificados() -> None:
    assert nombre_asignatura("Tecnologia") == "Tecnología"
    assert nombre_asignatura("Tecnology ") == "Tecnología"
    assert nombre_asignatura("Character") == "Carácter"
    assert nombre_asignatura("Science  LAB") == "Science Lab"
    assert nombre_asignatura("GYM") == "Gym"
    assert nombre_asignatura("Valores") == "Values"
    assert nombre_asignatura("Math ") == "Math"


def test_leer_hoja_cuenta_sesiones_sin_recesos_tutorias_ni_examenes() -> None:
    hoja = leer_hoja("1st", _hoja_dos_grupos())
    assert [g.seccion for g in hoja.grupos] == ["A", "B"]
    a, b = hoja.grupos
    assert a.conteo() == {
        "Math": 3,
        "Tecnología": 2,
        "Reading": 1,
        "Español": 2,
        "Values": 1,
        "Science Lab": 1,
        "Carácter": 2,
        "Gym": 2,
    }
    assert a.tutorias == 2
    assert b.conteo()["Math"] == 3
    assert b.conteo()["Español"] == 3
    # 12:40-1:20 se lee como tarde.
    assert {(s.inicio, s.fin) for s in a.sesiones} >= {(a_minutos("12:40"), a_minutos("13:20"))}
    assert a.maximo_diario()["Math"] == 2


@pytest.fixture
def proyecto(tmp_path: Path) -> Path:
    ruta = tmp_path / "escuela.horario"
    with Repositorio.crear(ruta) as repo:
        nivel = repo.guardar_nivel(
            Nivel(
                nombre="Primaria",
                duracion_min=45,
                inicio_jornada=a_minutos("08:00"),
                fin_jornada=a_minutos("14:00"),
                recesos=[Receso(inicio=a_minutos("09:30"), fin=a_minutos("09:50"))],
            )
        )
        assert nivel.id is not None
        repo.guardar_grado(Grado(nivel_id=nivel.id, nombre="Primero"))
        repo.guardar_asignatura(Asignatura(nombre="Tecnologia", color="#123456"))
    return ruta


def test_importar_crea_asignaturas_grupos_y_plan(tmp_path: Path, proyecto: Path) -> None:
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "1st"
    for fila in _hoja_dos_grupos():
        hoja.append(fila)
    otra = libro.create_sheet("9th")
    otra.append([None, None, "Monday"])
    otra.append([None, "8:00-8:45", "Math"])
    excel = tmp_path / "cuadro.xlsx"
    libro.save(excel)

    with Repositorio.abrir(proyecto) as repo:
        informe = importar(repo, leer_libro(excel))
        datos = repo.cargar_datos()

    assert informe.asignaturas_renombradas == [("Tecnologia", "Tecnología")]
    tecnologia = next(a for a in datos.asignaturas if a.nombre == "Tecnología")
    assert tecnologia.color == "#123456"  # se conserva la existente
    assert len(datos.asignaturas) == 8
    assert sorted(g.seccion for g in datos.grupos) == ["A", "B"]
    plan = {datos.asignatura(a).nombre: h for a, h in datos.plan_de_grado(1).items()}
    # Empates entre grupos: se toma el mayor y se avisa.
    assert plan["Español"] == 3
    assert plan["Tecnología"] == 2
    assert plan["Science Lab"] == 1
    assert any("Español" in aviso for aviso in informe.avisos)
    assert any("«9th»" in aviso for aviso in informe.avisos)
    # La clase de 12:40-1:20 no coincide con las franjas de 45 min del nivel.
    assert any("12:40-13:20" in aviso for aviso in informe.avisos)

    # Reimportar no duplica nada.
    with Repositorio.abrir(proyecto) as repo:
        importar(repo, leer_libro(excel))
        de_nuevo = repo.cargar_datos()
    assert len(de_nuevo.asignaturas) == len(datos.asignaturas)
    assert len(de_nuevo.grupos) == len(datos.grupos)
    assert de_nuevo.plan == datos.plan
