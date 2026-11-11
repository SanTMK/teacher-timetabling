"""Creado con Claude. Eventos por nivel (hora cívica) y profesores que asisten a ellos."""

from pathlib import Path

import openpyxl
from openpyxl.styles import PatternFill
from pytestqt.qtbot import QtBot

from timetabling.dominio.cuadricula import COLOR_EVENTO, cuadricula_grupo
from timetabling.dominio.modelos import (
    Asignacion,
    AsignacionFija,
    DatosEscuela,
    EstadoSolucion,
    Evento,
    Grado,
    Nivel,
    Profesor,
    a_minutos,
)
from timetabling.importacion.horarios_excel import (
    asistencia_por_defecto,
    es_celeste,
    importar,
    leer_libro,
)
from timetabling.nucleo.franjas import franjas_utiles_nivel, generar_franjas
from timetabling.nucleo.resolver import resolver
from timetabling.nucleo.validacion import Severidad, validar
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.repositorio import Repositorio

# En «minima»: franjas de 60 min 08–11, lunes y martes; Matemáticas y Español 2 h cada una.
CIVICA = Evento(id=1, nivel_id=1, dia="L", inicio=a_minutos("08:00"), fin=a_minutos("09:00"))


def _con_civica(datos: DatosEscuela) -> DatosEscuela:
    datos.niveles[0].eventos = [CIVICA]
    return datos


def test_franjas_utiles_conservan_indices(minima: DatosEscuela) -> None:
    nivel = _con_civica(minima).niveles[0]
    utiles = franjas_utiles_nivel(nivel)
    assert len(utiles) == 5
    assert [f.indice for f in utiles if f.dia == "L"] == [1, 2]


def test_solver_no_pone_clases_en_el_evento(minima: DatosEscuela) -> None:
    _con_civica(minima)
    resultado = resolver(minima)
    assert resultado.estado in (EstadoSolucion.OPTIMO, EstadoSolucion.FACTIBLE)
    assert verificar(minima, resultado.asignaciones) == []
    assert not any(a.dia == "L" and a.indice == 0 for a in resultado.asignaciones)


def test_profesor_que_asiste_no_da_clase_en_otro_nivel(minima: DatosEscuela) -> None:
    # Un segundo nivel con la misma jornada y un evento a las 08:00 del lunes. Carmen asiste.
    minima.niveles.append(
        minima.niveles[0].model_copy(
            update={
                "id": 2,
                "nombre": "Secundaria",
                "eventos": [CIVICA.model_copy(update={"id": 2, "nivel_id": 2})],
            }
        )
    )
    carmen = minima.profesor(3)
    carmen.eventos = {2}
    franjas = generar_franjas(minima)
    resultado = resolver(minima)
    assert verificar(minima, resultado.asignaciones) == []
    por_clave = {(f.nivel_id, f.dia, f.indice): f for f in franjas}
    for a in resultado.asignaciones:
        if a.profesor_id == 3:
            f = por_clave[(a.nivel_id, a.dia, a.indice)]
            assert not CIVICA.toca(f.dia, f.inicio, f.fin)


def test_verificador_d15(minima: DatosEscuela) -> None:
    _con_civica(minima)
    clase = Asignacion(grupo_id=1, asignatura_id=1, profesor_id=1, nivel_id=1, dia="L", indice=0)
    assert "D15" in {v.codigo for v in verificar(minima, [clase])}


def test_validacion_con_eventos(minima: DatosEscuela) -> None:
    _con_civica(minima)
    # Con la hora cívica quedan 5 franjas; un plan de 6 horas ya no cabe.
    minima.plan[0].horas_semanales = 4
    assert any("solo tiene 5 franjas" in p.mensaje for p in validar(minima))
    minima.plan[0].horas_semanales = 2
    minima.asignaciones_fijas = [
        AsignacionFija(grupo_id=1, asignatura_id=1, dia="L", indice_franja=0)
    ]
    errores = [p for p in validar(minima) if p.severidad == Severidad.ERROR]
    assert any("ocupada por «Hora cívica»" in p.mensaje for p in errores)
    minima.asignaciones_fijas = []
    minima.niveles[0].eventos = [CIVICA.model_copy(update={"dia": "V"})]
    assert any("no coincide con ninguna franja" in p.mensaje for p in validar(minima))


def test_cuadricula_muestra_el_evento(minima: DatosEscuela) -> None:
    _con_civica(minima)
    cuadricula = cuadricula_grupo(minima, generar_franjas(minima), [], 1)
    (bloque,) = cuadricula.bloques
    assert bloque.titulo == "Hora cívica" and bloque.color == COLOR_EVENTO


def test_persistencia_conserva_asistencia(tmp_path: Path, minima: DatosEscuela) -> None:
    _con_civica(minima)
    minima.profesor(1).eventos = {1}
    ruta = tmp_path / "e.horario"
    with Repositorio.crear(ruta) as repo:
        repo.reemplazar_datos(minima)
        datos = repo.cargar_datos()
        assert datos.niveles[0].eventos == [CIVICA]
        assert datos.profesor(1).eventos == {1}
        # Guardar el nivel (p. ej. al cambiar un receso) no borra la asistencia.
        repo.guardar_nivel(datos.niveles[0].model_copy(update={"duracion_min": 60}))
        assert repo.cargar_datos().profesor(1).eventos == {1}
        # Quitar el evento sí la quita.
        repo.guardar_nivel(datos.niveles[0].model_copy(update={"eventos": []}))
        assert repo.cargar_datos().profesor(1).eventos == set()


def test_asistencia_por_defecto(tmp_path: Path, minima: DatosEscuela) -> None:
    _con_civica(minima)
    segundo = Nivel(
        id=2,
        nombre="Secundaria",
        duracion_min=60,
        inicio_jornada=a_minutos("08:00"),
        fin_jornada=a_minutos("11:00"),
        dias=["L", "M"],
    )
    minima.niveles.append(segundo)
    minima.grados.append(Grado(id=2, nivel_id=2, nombre="7°"))
    minima.profesores.append(Profesor(id=4, nombre="Diana", asignaturas={1}, grados={1, 2}))
    ruta = tmp_path / "e.horario"
    with Repositorio.crear(ruta) as repo:
        repo.reemplazar_datos(minima)
        avisos = asistencia_por_defecto(repo)
        datos = repo.cargar_datos()
    assert datos.profesor(1).eventos == {1}  # un solo nivel: asiste
    assert datos.profesor(4).eventos == set()  # dos niveles: elige a mano
    assert any("Diana" in a for a in avisos)


def test_importar_detecta_celdas_celestes(tmp_path: Path, minima: DatosEscuela) -> None:
    assert es_celeste("FF00FFFF") and es_celeste("FF66FFFF")
    assert not es_celeste("FFFFC000") and not es_celeste(None)
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "1st"
    hoja.append([None, None, "1A"])
    hoja.append([None, None, "Monday", "Tuesday"])
    hoja.append([None, "8:00-9:00", None, "Matemáticas"])
    hoja.append([None, "9:00-10:00", "Español", "Matemáticas"])
    hoja.append([None, "10:00-11:00", "Matemáticas", "Español"])
    hoja["C3"].fill = PatternFill("solid", fgColor="FF00FFFF")
    excel = tmp_path / "c.xlsx"
    libro.save(excel)

    minima.grados[0].nombre = "Primero"
    ruta = tmp_path / "e.horario"
    with Repositorio.crear(ruta) as repo:
        repo.reemplazar_datos(minima)
        informe = importar(repo, leer_libro(excel))
        datos = repo.cargar_datos()
    (evento,) = datos.niveles[0].eventos
    assert (evento.dia, evento.inicio, evento.fin) == ("L", a_minutos("08:00"), a_minutos("09:00"))
    assert informe.eventos_nuevos
    # Todos los profesores de «minima» dan clase en un solo nivel: asisten.
    assert all(p.eventos == {evento.id} for p in datos.profesores)


def test_pantallas_niveles_y_profesores(qtbot: QtBot, tmp_path: Path, minima: DatosEscuela) -> None:
    from PySide6.QtCore import QSettings

    from timetabling.gui.app import VentanaPrincipal
    from timetabling.gui.pantallas.niveles import PantallaNiveles
    from timetabling.gui.pantallas.profesores import PantallaProfesores

    ruta = tmp_path / "e.horario"
    with Repositorio.crear(ruta) as repo:
        repo.reemplazar_datos(minima)
    ventana = VentanaPrincipal(QSettings(str(tmp_path / "a.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(ventana)
    ventana.abrir_proyecto(ruta)

    niveles = ventana.mostrar("niveles")
    assert isinstance(niveles, PantallaNiveles)
    niveles.lista.setCurrentRow(0)
    niveles.agregar_evento_nuevo()
    assert niveles.guardar()
    with Repositorio.abrir(ruta) as repo:
        (evento,) = repo.listar_niveles()[0].eventos
    assert (evento.dia, evento.inicio) == ("L", a_minutos("08:00"))
    assert any(
        "Hora cívica" in niveles.vista_franjas.item(i).text()
        for i in range(niveles.vista_franjas.count())
    )

    profesores = ventana.mostrar("profesores")
    assert isinstance(profesores, PantallaProfesores)
    profesores.lista.setCurrentRow(0)
    assert profesores.eventos.count() == 1
    profesores.marcar(profesores.eventos, {evento.id})
    assert profesores.guardar()
    with Repositorio.abrir(ruta) as repo:
        assert repo.listar_profesores()[0].eventos == {evento.id}
