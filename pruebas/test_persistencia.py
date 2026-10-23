"""Creado con Claude. Pruebas del repositorio SQLite, migraciones y proyecto de ejemplo."""

import sqlite3
from pathlib import Path

import pytest

from timetabling.dominio.modelos import (
    Asignacion,
    AsignacionFija,
    Configuracion,
    EstadoSolucion,
    Pesos,
    PlanEstudios,
    Solucion,
)
from timetabling.ejemplo import Tamano, construir_datos, crear_proyecto_ejemplo
from timetabling.persistencia import migraciones
from timetabling.persistencia.repositorio import Repositorio


@pytest.mark.parametrize("tamano", list(Tamano))
def test_ejemplo_ida_y_vuelta_identico(tmp_path: Path, tamano: Tamano) -> None:
    ruta = tmp_path / "escuela.horario"
    creados = crear_proyecto_ejemplo(ruta, tamano)
    with Repositorio.abrir(ruta) as repo:
        cargados = repo.cargar_datos()
    assert cargados == creados
    # Coincide con lo construido en memoria (salvo los ids que asigna la base).
    original = construir_datos(tamano)
    assert len(cargados.grupos) == len(original.grupos)
    assert len(cargados.profesores) == len(original.profesores)
    assert [p.asignaturas for p in cargados.profesores] == [
        p.asignaturas for p in original.profesores
    ]

    def orden(p: PlanEstudios) -> tuple[int, int]:
        return (p.grado_id, p.asignatura_id)

    assert cargados.plan == sorted(original.plan, key=orden)
    assert cargados.configuracion == original.configuracion
    for n_cargado, n_original in zip(cargados.niveles, original.niveles, strict=True):
        assert n_cargado.model_dump(exclude={"recesos"}) == n_original.model_dump(
            exclude={"recesos"}
        )
        assert [(r.inicio, r.fin) for r in n_cargado.recesos] == [
            (r.inicio, r.fin) for r in n_original.recesos
        ]


def test_ejemplo_mediano_tiene_tamano_objetivo() -> None:
    datos = construir_datos(Tamano.MEDIANO)
    assert len(datos.grupos) == 30
    assert 35 <= len(datos.profesores) <= 50


def test_crud_y_cascadas(tmp_path: Path) -> None:
    ruta = tmp_path / "p.horario"
    crear_proyecto_ejemplo(ruta)
    with Repositorio.abrir(ruta) as repo:
        datos = repo.cargar_datos()
        profesor = datos.profesores[0]
        assert profesor.disponibilidad
        afectados = repo.afectados_por_eliminar("profesores", profesor.id)
        assert afectados["disponibilidad"] == len(profesor.disponibilidad)

        repo.eliminar_profesor(profesor.id)
        filas = repo._filas("SELECT * FROM disponibilidad WHERE profesor_id = ?", (profesor.id,))
        assert filas == []
        assert all(g.titular_id != profesor.id for g in repo.listar_grupos())

        nivel = datos.niveles[0]
        repo.eliminar_nivel(nivel.id)
        grados_restantes = {g.nivel_id for g in repo.listar_grados()}
        assert nivel.id not in grados_restantes

        asignatura = repo.guardar_asignatura(
            datos.asignaturas[0].model_copy(update={"id": None, "nombre": "Robótica"})
        )
        assert asignatura.id is not None
        repo.guardar_asignatura(asignatura.model_copy(update={"max_horas_dia": 3}))
        assert (
            next(a for a in repo.listar_asignaturas() if a.id == asignatura.id).max_horas_dia == 3
        )

        with pytest.raises(sqlite3.IntegrityError):
            repo.guardar_asignatura(asignatura.model_copy(update={"id": None}))


def test_plan_cero_elimina(tmp_path: Path) -> None:
    with Repositorio.crear(tmp_path / "p.horario") as repo:
        datos = construir_datos()
        repo.reemplazar_datos(datos)
        item = datos.plan[0]
        repo.guardar_plan(
            PlanEstudios(
                grado_id=item.grado_id, asignatura_id=item.asignatura_id, horas_semanales=0
            )
        )
        assert len(repo.listar_plan()) == len(datos.plan) - 1


def test_configuracion_y_fijas(tmp_path: Path) -> None:
    with Repositorio.crear(tmp_path / "p.horario") as repo:
        repo.reemplazar_datos(construir_datos())
        config = Configuracion(
            nombre_escuela="Otra",
            margen_traslado_min=5,
            tiempo_limite_s=60,
            hilos=2,
            pesos=Pesos(huecos_profesor=99),
        )
        repo.guardar_configuracion(config)
        assert repo.obtener_configuracion() == config
        grupo = repo.listar_grupos()[0]
        fija = repo.guardar_asignacion_fija(
            AsignacionFija(grupo_id=grupo.id, asignatura_id=1, dia="L", indice_franja=0)
        )
        assert repo.listar_asignaciones_fijas() == [fija]
        repo.eliminar_asignacion_fija(fija.id)
        assert repo.listar_asignaciones_fijas() == []


def test_soluciones_ida_y_vuelta(tmp_path: Path) -> None:
    with Repositorio.crear(tmp_path / "p.horario") as repo:
        repo.reemplazar_datos(construir_datos())
        grupo = repo.listar_grupos()[0]
        profesor = repo.listar_profesores()[0]
        solucion = Solucion(
            estado=EstadoSolucion.FACTIBLE,
            tiempo_s=1.5,
            penalizaciones={"huecos_profesor": 3},
            nota="prueba",
            asignaciones=[
                Asignacion(
                    grupo_id=grupo.id,
                    asignatura_id=1,
                    profesor_id=profesor.id,
                    nivel_id=1,
                    dia="L",
                    indice=0,
                )
            ],
        )
        guardada = repo.guardar_solucion(solucion)
        assert repo.cargar_solucion(guardada.id) == guardada
        assert [s.id for s in repo.listar_soluciones()] == [guardada.id]
        repo.eliminar_solucion(guardada.id)
        assert repo.listar_soluciones() == []


def test_guardar_como(tmp_path: Path) -> None:
    ruta = tmp_path / "a.horario"
    datos = crear_proyecto_ejemplo(ruta)
    with Repositorio.abrir(ruta) as repo:
        repo.guardar_como(tmp_path / "b.horario")
    with Repositorio.abrir(tmp_path / "b.horario") as copia:
        assert copia.cargar_datos() == datos


def test_migraciones(tmp_path: Path) -> None:
    ruta = tmp_path / "m.horario"
    with Repositorio.crear(ruta):
        pass
    conexion = sqlite3.connect(ruta)
    assert migraciones.version_de(conexion) == migraciones.VERSION_ACTUAL

    aplicadas: list[int] = []

    def a_v2(cx: sqlite3.Connection) -> None:
        cx.execute("ALTER TABLE niveles ADD COLUMN color TEXT")
        aplicadas.append(2)

    anterior = migraciones.aplicar_migraciones(conexion, version_actual=2, migraciones={2: a_v2})
    assert anterior == 1 and aplicadas == [2]
    assert migraciones.version_de(conexion) == 2
    columnas = [f[1] for f in conexion.execute("PRAGMA table_info(niveles)")]
    assert "color" in columnas
    conexion.close()

    with pytest.raises(migraciones.ErrorVersionEsquema):
        Repositorio.abrir(ruta)  # el programa solo conoce la versión 1
