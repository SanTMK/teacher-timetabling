"""Creado con Claude. Ciclo completo en la interfaz: generar → fijar → regenerar → exportar."""

from pathlib import Path

import openpyxl
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from timetabling.dominio.modelos import Disponibilidad, EstadoSolucion
from timetabling.ejemplo import crear_proyecto_ejemplo
from timetabling.exportacion.excel import OpcionesExportacion
from timetabling.gui.app import VentanaPrincipal
from timetabling.gui.pantallas.fijas import SOMBRA_NO_DISPONIBLE, PantallaFijas
from timetabling.gui.pantallas.generar import PantallaGenerar
from timetabling.gui.pantallas.resultados import PantallaResultados
from timetabling.gui.widgets.arrastre import ROL_INFO, CuadriculaFijas, codificar
from timetabling.gui.widgets.vista_horario import ICONO_CAMBIO, ICONO_FIJA
from timetabling.nucleo.franjas import franjas_validas_profesor
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.repositorio import Repositorio


@pytest.fixture
def ventana(qtbot: QtBot, tmp_path: Path) -> VentanaPrincipal:
    ajustes = QSettings(str(tmp_path / "ajustes.ini"), QSettings.Format.IniFormat)
    v = VentanaPrincipal(ajustes)
    qtbot.addWidget(v)
    v.show()
    ruta = tmp_path / "escuela.horario"
    crear_proyecto_ejemplo(ruta)
    v.abrir_proyecto(ruta)
    return v


def _generar(ventana: VentanaPrincipal, qtbot: QtBot, limite: float) -> PantallaGenerar:
    generar = ventana.mostrar("generar")
    assert isinstance(generar, PantallaGenerar)
    assert generar.generar(tiempo_limite_s=limite)
    return generar


def _esperar(qtbot: QtBot, generar: PantallaGenerar, timeout_s: float = 90) -> None:
    qtbot.waitUntil(lambda: not generar.en_curso, timeout=int(timeout_s * 1000))


def test_ciclo_generar_fijar_regenerar_exportar(
    ventana: VentanaPrincipal, qtbot: QtBot, tmp_path: Path
) -> None:
    # La interfaz sigue procesando eventos mientras el solver trabaja.
    latidos: list[int] = []
    reloj = QTimer()
    reloj.timeout.connect(lambda: latidos.append(1))
    reloj.start(50)

    generar = _generar(ventana, qtbot, limite=4)
    assert not ventana.pantallas["profesores"].isEnabled()
    assert not ventana.pantallas["resultados"].isEnabled()
    assert not ventana.accion_abrir.isEnabled()
    _esperar(qtbot, generar)
    reloj.stop()
    assert len(latidos) >= 20  # ~4 s a 50 ms: el bucle de eventos no se congeló
    assert ventana.pantallas["profesores"].isEnabled()
    assert ventana.accion_abrir.isEnabled()
    assert generar.ultima_solucion_id is not None
    assert "verificada y guardada" in generar.mensaje.text()

    # Resultados de la solución recién generada
    generar.boton_resultados.click()
    resultados = ventana.pantallas["resultados"]
    assert isinstance(resultados, PantallaResultados)
    assert ventana.pila.currentWidget() is resultados
    assert resultados.solucion is not None
    primera = resultados.solucion
    assert resultados.tabla_carga.rowCount() == len(ventana.repo.listar_profesores())

    # Fijar una clase desde la vista por grupo
    vista = resultados.vista_grupo
    celda = next(
        (f, c)
        for f in range(vista.rowCount())
        for c in range(vista.columnCount())
        if len(vista.asignaciones_en(f, c)) == 1
    )
    clase = vista.asignaciones_en(*celda)[0]
    resultados.fijar(clase, True)
    fijas = ventana.repo.listar_asignaciones_fijas()
    assert len(fijas) == 1 and fijas[0].profesor_id == clase.profesor_id
    assert vista.item(*celda).text().startswith(ICONO_FIJA)

    # Regenerar: la clase fija se respeta
    generar = _generar(ventana, qtbot, limite=4)
    _esperar(qtbot, generar)
    assert generar.ultima_solucion_id != primera.id
    with Repositorio.abrir(ventana.repo.ruta) as repo:
        nueva = repo.cargar_solucion(generar.ultima_solucion_id)
        assert verificar(repo.cargar_datos(), nueva.asignaciones) == []
    assert any(
        (a.grupo_id, a.asignatura_id, a.profesor_id, a.dia, a.indice)
        == (clase.grupo_id, clase.asignatura_id, clase.profesor_id, clase.dia, clase.indice)
        for a in nueva.asignaciones
    )

    # Desfijar
    ventana.ver_solucion(nueva.id)
    resultados.fijar(clase, False)
    assert ventana.repo.listar_asignaciones_fijas() == []
    assert resultados.selector.count() == 2

    # Exportar a Excel
    destino = resultados.exportar(tmp_path / "horario")
    assert destino.suffix == ".xlsx"
    libro = openpyxl.load_workbook(destino)
    assert "Resumen" in libro.sheetnames and "K3A" in libro.sheetnames


def test_cancelar_conserva_la_mejor_solucion(ventana: VentanaPrincipal, qtbot: QtBot) -> None:
    generar = _generar(ventana, qtbot, limite=120)
    qtbot.waitUntil(lambda: generar.soluciones.text() != "0", timeout=60000)
    generar.boton_cancelar.click()
    _esperar(qtbot, generar, timeout_s=30)
    assert generar.ultima_solucion_id is not None
    solucion = ventana.repo.cargar_solucion(generar.ultima_solucion_id)
    assert solucion.estado in (EstadoSolucion.CANCELADO, EstadoSolucion.OPTIMO)
    assert solucion.tiempo_s < 60


def test_infactible_muestra_diagnostico(ventana: VentanaPrincipal, qtbot: QtBot) -> None:
    repo = ventana.repo
    assert repo is not None
    titular = next(p for p in repo.listar_profesores() if p.nombre == "Ana López")
    for rango in titular.disponibilidad:
        rango.inicio = 9 * 60 + 30
    repo.guardar_profesor(titular)
    generar = _generar(ventana, qtbot, limite=10)
    _esperar(qtbot, generar)
    assert generar.caja_diagnostico.isVisible()
    assert generar.diagnostico.count() >= 1
    assert "Ana López" in "\n".join(
        generar.diagnostico.item(i).text() for i in range(generar.diagnostico.count())
    )
    assert repo.listar_soluciones() == []


def test_errores_de_validacion_impiden_generar(ventana: VentanaPrincipal) -> None:
    repo = ventana.repo
    assert repo is not None
    for profesor in repo.listar_profesores():
        repo.guardar_profesor(profesor.model_copy(update={"asignaturas": set()}))
    generar = ventana.mostrar("generar")
    assert isinstance(generar, PantallaGenerar)
    assert not generar.generar()
    assert "error(es) en los datos" in generar.mensaje.text()
    assert generar.boton_validacion.isVisibleTo(generar)
    generar.boton_validacion.click()
    assert ventana.pila.currentWidget() is ventana.pantallas["validacion"]


def _soltar(widget: QWidget, mime: QMimeData, punto: QPoint) -> bool:
    """Envía un ``QDropEvent`` como lo haría Qt al terminar un arrastre."""
    evento = QDropEvent(
        QPointF(punto),
        Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(evento)  # type: ignore[attr-defined]
    return evento.isAccepted()


def _centro(cuadricula: CuadriculaFijas, dia: str, indice: int) -> QPoint:
    item = cuadricula.celda(dia, indice)
    assert item is not None
    return cuadricula.visualItemRect(item).center()


def test_clases_fijas_arrastrando_antes_de_generar(
    ventana: VentanaPrincipal, qtbot: QtBot, tmp_path: Path
) -> None:
    fijas = ventana.mostrar("fijas")
    assert isinstance(fijas, PantallaFijas)
    datos = fijas._datos
    assert not datos.asignaciones_fijas
    grupo = datos.grupos[0]
    fijas.grupo.setCurrentIndex(fijas.grupo.findData(grupo.id))
    plan = datos.plan_de_grado(grupo.grado_id)

    # La paleta tiene las asignaturas del plan, cada una con «cualquiera» + habilitados.
    paleta = fijas.paleta
    assert paleta.topLevelItemCount() == len(plan)
    asignatura_item = paleta.topLevelItem(0)
    profesor_item = asignatura_item.child(1)  # el primero es «cualquiera»
    info = profesor_item.data(0, ROL_INFO)
    # Con disponibilidad de un solo día, el resto de la semana queda sombreado.
    nivel = datos.nivel_de_grupo(grupo)
    original = datos.profesor(info["profesor_id"])
    profesor = original.model_copy(
        update={
            "disponibilidad": [
                Disponibilidad(
                    dia=nivel.dias[0], inicio=nivel.inicio_jornada, fin=nivel.fin_jornada
                )
            ]
        }
    )
    assert ventana.repo is not None
    ventana.repo.guardar_profesor(profesor)
    fijas.refrescar()
    paleta.seleccionar_info(info)
    profesor_item = paleta.currentItem()

    # Se sombrean las horas en que el profesor no está disponible; se suelta en una libre.
    cuadricula = fijas.cuadricula
    franjas = [f for f in fijas._franjas if f.nivel_id == nivel.id]
    validas = franjas_validas_profesor(profesor, franjas)
    libre = next(f for f in franjas if f.id in validas)
    for f in franjas:
        celda = cuadricula.celda(f.dia, f.indice)
        assert celda is not None
        if f.id not in validas:
            assert celda.background().color().name().upper() == SOMBRA_NO_DISPONIBLE
    otra = next(f for f in franjas if f.id in validas and f != libre)
    assert len(validas) < len(franjas)
    assert _soltar(
        cuadricula, paleta.mimeData([profesor_item]), _centro(cuadricula, libre.dia, libre.indice)
    )
    fija = fijas._datos.asignaciones_fijas[0]
    assert (fija.grupo_id, fija.asignatura_id, fija.profesor_id) == (
        grupo.id,
        info["asignatura_id"],
        profesor.id,
    )
    assert "1 de" in paleta.topLevelItem(0).text(0)

    # Una casilla ocupada no acepta otra clase; la clase sí se puede mover a otra hora.
    cualquiera = paleta.topLevelItem(0).child(0)
    assert not _soltar(
        cuadricula, paleta.mimeData([cualquiera]), _centro(cuadricula, libre.dia, libre.indice)
    )
    celda = cuadricula.celda(libre.dia, libre.indice)
    assert celda is not None
    mover = codificar(celda.data(ROL_INFO))
    assert _soltar(cuadricula, mover, _centro(cuadricula, otra.dia, otra.indice))
    fija = fijas._datos.asignaciones_fijas[0]
    assert (fija.dia, fija.indice_franja) == (otra.dia, otra.indice)

    # Una segunda clase devuelta a la paleta se elimina.
    assert _soltar(
        cuadricula,
        paleta.mimeData([paleta.topLevelItem(0).child(0)]),
        _centro(cuadricula, libre.dia, libre.indice),
    )
    assert len(fijas._datos.asignaciones_fijas) == 2
    celda = cuadricula.celda(libre.dia, libre.indice)
    assert celda is not None
    assert _soltar(paleta, codificar(celda.data(ROL_INFO)), QPoint(5, 5))
    assert len(fijas._datos.asignaciones_fijas) == 1

    ventana.repo.guardar_profesor(original)  # disponibilidad completa para resolver
    generar = _generar(ventana, qtbot, limite=10)
    _esperar(qtbot, generar)
    assert generar.ultima_solucion_id is not None
    with Repositorio.abrir(ventana.repo.ruta) as repo:  # type: ignore[union-attr]
        solucion = repo.cargar_solucion(generar.ultima_solucion_id)
    assert any(
        (a.grupo_id, a.asignatura_id, a.profesor_id, a.dia, a.indice)
        == (grupo.id, fija.asignatura_id, profesor.id, otra.dia, otra.indice)
        for a in solucion.asignaciones
    )


def test_horario_vigente_y_reajuste(ventana: VentanaPrincipal, qtbot: QtBot) -> None:
    repo = ventana.repo
    assert repo is not None
    generar = _generar(ventana, qtbot, limite=4)
    assert not generar.boton_reajustar.isEnabled()  # aún no hay horario vigente
    _esperar(qtbot, generar)
    primera_id = generar.ultima_solucion_id
    assert primera_id is not None

    # Marcar como vigente desde Resultados
    ventana.ver_solucion(primera_id)
    resultados = ventana.pantallas["resultados"]
    assert isinstance(resultados, PantallaResultados)
    resultados.boton_vigente.click()
    assert repo.solucion_vigente_id() == primera_id
    assert resultados.selector.currentText().startswith("★ VIGENTE")
    assert not resultados.boton_vigente.isEnabled()
    assert not resultados.pestanas.isTabVisible(resultados.indice_cambios)

    # Reajustar sin cambios en los datos: el horario se conserva
    generar = ventana.mostrar("generar")
    assert isinstance(generar, PantallaGenerar)
    assert generar.boton_reajustar.isEnabled()
    assert generar.generar(tiempo_limite_s=6, reajustar=True)
    _esperar(qtbot, generar)
    assert "0 clase(s) cambiada(s)" in generar.mensaje.text()
    reajuste_id = generar.ultima_solucion_id
    assert reajuste_id != primera_id
    assert repo.cargar_solucion(reajuste_id).nota == f"Reajuste del horario #{primera_id}"

    generar.boton_resultados.click()
    assert resultados.solucion is not None and resultados.solucion.id == reajuste_id
    assert resultados.pestanas.isTabVisible(resultados.indice_cambios)
    assert resultados.pestanas.tabText(resultados.indice_cambios) == "Cambios (0)"
    assert "0 clase(s) cambiada(s)" in resultados.resumen.text()

    # Una solución con cambios se resalta en la vista y se lista en «Cambios»
    vigente = repo.cargar_solucion(primera_id)
    otra = vigente.asignaciones[0]
    sustituto = next(p for p in repo.listar_profesores() if p.id != otra.profesor_id)
    cambiadas = [
        a.model_copy(update={"profesor_id": sustituto.id}) if a is otra else a
        for a in vigente.asignaciones
    ]
    movida = repo.guardar_solucion(
        vigente.model_copy(update={"id": None, "vigente": False, "asignaciones": cambiadas})
    )
    resultados.seleccionar_solucion(movida.id)
    assert resultados.tabla_cambios.rowCount() == 1
    assert resultados.tabla_cambios.item(0, 2).text() == "Cambio de profesor"
    resultados.selector_grupo.setCurrentIndex(resultados.selector_grupo.findData(otra.grupo_id))
    vista = resultados.vista_grupo
    textos = [
        vista.item(f, c).text()
        for f in range(vista.rowCount())
        for c in range(vista.columnCount())
        if vista.item(f, c)
    ]
    assert sum(t.startswith(ICONO_CAMBIO) for t in textos) == 1
    resultados.resaltar.setChecked(False)
    assert not any(
        vista.item(f, c).text().startswith(ICONO_CAMBIO)
        for f in range(vista.rowCount())
        for c in range(vista.columnCount())
        if vista.item(f, c)
    )

    # (la solución hecha a mano puede tener choques: solo se exporta la hoja de cambios)
    solo_cambios = OpcionesExportacion(
        grupos=False, profesores=False, espacios=False, resumen=False
    )
    destino = resultados.exportar(Path(repo.ruta).with_name("cambios.xlsx"), solo_cambios)
    assert "Cambios" in openpyxl.load_workbook(destino).sheetnames
