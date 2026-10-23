"""Creado con Claude. Pruebas de la interfaz de captura (pytest-qt)."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtWidgets import QTreeWidgetItem
from pytestqt.qtbot import QtBot
from typer.testing import CliRunner

from timetabling.cli import app
from timetabling.dominio.modelos import TipoDisponibilidad, a_minutos
from timetabling.ejemplo import crear_proyecto_ejemplo
from timetabling.gui.app import VentanaPrincipal
from timetabling.gui.pantallas.asignaturas import PantallaAsignaturas
from timetabling.gui.pantallas.base import Pantalla, poner_hora
from timetabling.gui.pantallas.configuracion import PantallaConfiguracion
from timetabling.gui.pantallas.grados_grupos import PantallaGradosGrupos
from timetabling.gui.pantallas.niveles import PantallaNiveles
from timetabling.gui.pantallas.plan import PantallaPlan
from timetabling.gui.pantallas.profesores import PantallaProfesores
from timetabling.gui.pantallas.validacion import PantallaValidacion
from timetabling.gui.widgets.disponibilidad import EditorDisponibilidad
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.repositorio import Repositorio


@pytest.fixture
def ventana(qtbot: QtBot, tmp_path: Path) -> VentanaPrincipal:
    ajustes = QSettings(str(tmp_path / "ajustes.ini"), QSettings.Format.IniFormat)
    v = VentanaPrincipal(ajustes)
    qtbot.addWidget(v)
    v.show()
    return v


def _pantalla[T: Pantalla](ventana: VentanaPrincipal, clave: str, tipo: type[T]) -> T:
    pantalla = ventana.mostrar(clave)
    assert isinstance(pantalla, tipo)
    return pantalla


def _buscar(arbol_item: QTreeWidgetItem | None, texto: str) -> QTreeWidgetItem:
    assert arbol_item is not None
    if arbol_item.text(0) == texto:
        return arbol_item
    for i in range(arbol_item.childCount()):
        try:
            return _buscar(arbol_item.child(i), texto)
        except LookupError:
            pass
    raise LookupError(texto)


def _seleccionar_en_arbol(pantalla: PantallaGradosGrupos, texto: str) -> None:
    for i in range(pantalla.arbol.topLevelItemCount()):
        try:
            pantalla.arbol.setCurrentItem(_buscar(pantalla.arbol.topLevelItem(i), texto))
            return
        except LookupError:
            pass
    raise LookupError(texto)


def _arrastrar(
    qtbot: QtBot, editor: EditorDisponibilidad, dia: str, desde: int, hasta: int
) -> None:
    """Arrastra con el ratón sobre la columna de ``dia`` entre dos horas (en minutos)."""
    x = int(editor.MARGEN_IZQ + editor.dias.index(dia) * editor._ancho_dia() + 5)

    def y(minuto: int) -> int:
        return int(editor.ALTO_ENCABEZADO + (minuto - editor.inicio) / 15 * editor.ALTO_CELDA + 3)

    qtbot.mousePress(editor, Qt.MouseButton.LeftButton, pos=QPoint(x, y(desde)))
    qtbot.mouseMove(editor, QPoint(x, y(hasta - 15)))
    qtbot.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=QPoint(x, y(hasta - 15)))


def test_crear_proyecto_desde_cero_y_resolver(
    ventana: VentanaPrincipal, qtbot: QtBot, tmp_path: Path
) -> None:
    ruta = tmp_path / "escuela.horario"
    ventana.nuevo_proyecto(ruta)
    assert ventana.repo is not None and ruta.exists()

    # Configuración
    config = _pantalla(ventana, "configuracion", PantallaConfiguracion)
    config.nombre.setText("Escuela Prueba")
    config.tiempo.setValue(20)
    assert config.guardar()

    # Nivel con receso y vista previa
    niveles = _pantalla(ventana, "niveles", PantallaNiveles)
    niveles.nuevo()
    niveles.nombre.setText("Primaria")
    niveles.duracion.setValue(60)
    poner_hora(niveles.inicio, a_minutos("08:00"))
    poner_hora(niveles.fin, a_minutos("11:15"))
    for dia, casilla in niveles.dias.items():
        casilla.setChecked(dia in ("L", "M"))
    from timetabling.dominio.modelos import Receso

    niveles.agregar_receso(
        Receso(nombre="Recreo", inicio=a_minutos("10:00"), fin=a_minutos("10:15"))
    )
    assert niveles.resumen_franjas.text() == "3 franjas por día · 6 por semana"
    assert niveles.vista_franjas.item(2).text().strip() == "Recreo: 10:00–10:15"
    assert niveles.guardar()

    # Grado y grupos
    grados = _pantalla(ventana, "grados", PantallaGradosGrupos)
    _seleccionar_en_arbol(grados, "Primaria")
    grados.agregar_grado()
    grados.nombre_grado.setText("1°")
    assert grados.guardar()
    for seccion in ("A", "B"):
        _seleccionar_en_arbol(grados, "1°")
        grados.agregar_grupo()
        grados.seccion.setText(seccion)
        grados.estudiantes.setValue(20)
        assert grados.guardar()

    # Asignaturas
    asignaturas = _pantalla(ventana, "asignaturas", PantallaAsignaturas)
    for nombre in ("Matemáticas", "Español"):
        asignaturas.nuevo()
        asignaturas.nombre.setText(nombre)
        asignaturas.max_horas.setValue(2)
        assert asignaturas.guardar()

    datos = ventana.repo.cargar_datos()
    grado = datos.grados[0]
    mat, esp = (a.id for a in datos.asignaturas)

    # Plan de estudios
    plan = _pantalla(ventana, "plan", PantallaPlan)
    plan.poner_horas(grado.id, mat, 2)
    plan.poner_horas(grado.id, esp, 2)
    assert plan.tabla.item(0, 0).text() == "4 / 6"

    # Profesores con disponibilidad marcada arrastrando el ratón
    profesores = _pantalla(ventana, "profesores", PantallaProfesores)
    for nombre, asigs in (("Ana", {mat}), ("Bruno", {esp}), ("Carmen", {mat, esp})):
        profesores.nuevo()
        profesores.nombre.setText(nombre)
        profesores.marcar(profesores.asignaturas, asigs)
        profesores.marcar(profesores.grados, {grado.id})
        _arrastrar(qtbot, profesores.editor, "L", a_minutos("08:00"), a_minutos("11:15"))
        profesores.editor.copiar_dia_a_semana("L")
        assert profesores.guardar()
    ana = next(p for p in ventana.repo.listar_profesores() if p.nombre == "Ana")
    assert [(d.dia, d.inicio, d.fin) for d in ana.disponibilidad] == [
        ("L", a_minutos("08:00"), a_minutos("11:15")),
        ("M", a_minutos("08:00"), a_minutos("11:15")),
    ]

    # Validación sin problemas
    validacion = _pantalla(ventana, "validacion", PantallaValidacion)
    assert validacion.problemas == []

    # Resolver desde la CLI
    resultado = CliRunner().invoke(app, ["generar", str(ruta), "--tiempo-limite", "10"])
    assert resultado.exit_code == 0, resultado.output
    with Repositorio.abrir(ruta) as repo:
        solucion = repo.cargar_solucion(repo.listar_soluciones()[0].id)
        assert verificar(repo.cargar_datos(), solucion.asignaciones) == []
        assert len(solucion.asignaciones) == 8


def test_errores_junto_a_los_campos(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    ventana.nuevo_proyecto(tmp_path / "p.horario")
    niveles = _pantalla(ventana, "niveles", PantallaNiveles)
    niveles.nuevo()
    niveles.nombre.setText("")
    poner_hora(niveles.inicio, a_minutos("12:00"))
    poner_hora(niveles.fin, a_minutos("08:00"))
    for casilla in niveles.dias.values():
        casilla.setChecked(False)
    assert not niveles.guardar()
    assert niveles.errores.texto("nombre") == "El nombre no puede estar vacío"
    assert "al menos un día" in niveles.errores.texto("dias")
    assert "debe ser menor que la de fin" in niveles.errores.texto("fin_jornada")

    asignaturas = _pantalla(ventana, "asignaturas", PantallaAsignaturas)
    asignaturas.nuevo()
    asignaturas.nombre.setText("Arte")
    assert asignaturas.guardar()
    asignaturas.nuevo()
    asignaturas.nombre.setText("Arte")
    assert not asignaturas.guardar()
    assert asignaturas.errores.texto("nombre") == "Ya existe un elemento con ese nombre"


def test_borrar_advierte_lo_afectado(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    crear_proyecto_ejemplo(ruta)
    ventana.abrir_proyecto(ruta)
    profesores = _pantalla(ventana, "profesores", PantallaProfesores)
    textos: list[str] = []
    profesores.confirmar = lambda titulo, texto: textos.append(texto) or False  # type: ignore[method-assign]
    antes = profesores.lista.count()
    assert not profesores.eliminar()
    assert "disponibilidad" in textos[0] and "grupos con titular" in textos[0]
    assert profesores.lista.count() == antes
    profesores.confirmar = lambda titulo, texto: True  # type: ignore[method-assign]
    assert profesores.eliminar()
    assert profesores.lista.count() == antes - 1


def test_validacion_navega_al_elemento(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    ruta = tmp_path / "e.horario"
    datos = crear_proyecto_ejemplo(ruta)
    with Repositorio.abrir(ruta) as repo:
        profesor = datos.profesores[3]
        repo.guardar_profesor(profesor.model_copy(update={"disponibilidad": []}))
    ventana.abrir_proyecto(ruta)
    validacion = _pantalla(ventana, "validacion", PantallaValidacion)
    fila = next(
        i
        for i, p in enumerate(validacion.problemas)
        if p.mensaje.endswith("no tiene disponibilidad")
    )
    validacion.ir_a(fila)
    profesores = ventana.pantallas["profesores"]
    assert ventana.pila.currentWidget() is profesores
    assert isinstance(profesores, PantallaProfesores)
    assert profesores.actual_id == profesor.id
    assert profesores.nombre.text() == profesor.nombre


def test_editor_disponibilidad_modos_y_conversion(qtbot: QtBot) -> None:
    editor = EditorDisponibilidad()
    qtbot.addWidget(editor)
    editor.resize(600, editor.sizeHint().height())
    editor.configurar(["L", "M"], a_minutos("07:00"), a_minutos("10:00"))
    editor.modo = TipoDisponibilidad.PREFERIBLE_NO
    _arrastrar(qtbot, editor, "L", a_minutos("07:00"), a_minutos("08:00"))
    editor.pintar("L", a_minutos("08:00"), a_minutos("10:00"), TipoDisponibilidad.DISPONIBLE)
    editor.modo = None
    _arrastrar(qtbot, editor, "L", a_minutos("09:00"), a_minutos("09:30"))
    rangos = [(d.dia, d.inicio, d.fin, d.tipo) for d in editor.disponibilidad()]
    assert rangos == [
        ("L", 420, 480, TipoDisponibilidad.PREFERIBLE_NO),
        ("L", 480, 540, TipoDisponibilidad.DISPONIBLE),
        ("L", 570, 600, TipoDisponibilidad.DISPONIBLE),
    ]
    editor.copiar_dia_a_semana("L")
    assert len(editor.disponibilidad()) == 6
    # Ida y vuelta: los rangos alineados a 15 min se conservan exactamente
    copia = EditorDisponibilidad()
    copia.configurar(["L", "M"], a_minutos("07:00"), a_minutos("10:00"))
    copia.poner_disponibilidad(editor.disponibilidad())
    assert copia.disponibilidad() == editor.disponibilidad()


def test_proyectos_recientes_y_guardar_como(ventana: VentanaPrincipal, tmp_path: Path) -> None:
    ruta = tmp_path / "a.horario"
    crear_proyecto_ejemplo(ruta)
    ventana.abrir_proyecto(ruta)
    ventana.guardar_como(tmp_path / "b")
    assert ventana.repo is not None and ventana.repo.ruta == tmp_path / "b.horario"
    assert ventana.recientes()[:2] == [str(tmp_path / "b.horario"), str(ruta)]
    assert "b.horario" in ventana.windowTitle()


def test_icono_de_la_aplicacion(qtbot: QtBot) -> None:
    from timetabling.gui.app import icono_aplicacion

    icono = icono_aplicacion()
    assert not icono.isNull()
    assert icono.availableSizes()
