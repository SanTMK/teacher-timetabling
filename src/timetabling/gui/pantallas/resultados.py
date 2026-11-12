"""Creado con Claude. Pantalla Resultados: soluciones guardadas, vistas de horario, resúmenes,
ajustes manuales (fijar/desfijar), horario vigente, cambios respecto a él y exportación a
Excel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.comparacion import (
    ENCABEZADOS_CAMBIOS,
    Cambio,
    ClaveClase,
    claves_cambiadas,
    comparar,
    filas_cambios,
    profesores_afectados,
)
from timetabling.dominio.cuadricula import (
    cuadricula_espacio,
    cuadricula_grupo,
    cuadricula_profesor,
    espacios_usados,
)
from timetabling.dominio.estadisticas import carga_docente, penalizacion_total
from timetabling.dominio.modelos import (
    NOMBRES_PENALIZACIONES,
    Asignacion,
    AsignacionFija,
    DatosEscuela,
    Franja,
    Solucion,
)
from timetabling.exportacion.excel import OpcionesExportacion, exportar_excel
from timetabling.gui.pantallas.base import Pantalla
from timetabling.gui.widgets.vista_horario import VistaHorario, clave_clase
from timetabling.nucleo.franjas import generar_franjas


class DialogoExportar(QDialog):
    def __init__(self, padre: QWidget, con_cambios: bool = False) -> None:
        super().__init__(padre)
        self.setWindowTitle("Exportar a Excel")
        self.casillas = {
            "grupos": QCheckBox("Una hoja por grupo"),
            "profesores": QCheckBox("Una hoja por profesor"),
            "espacios": QCheckBox("Ocupación de espacios especiales"),
            "resumen": QCheckBox("Resumen y carga docente"),
            "cambios": QCheckBox("Cambios respecto al horario vigente"),
        }
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel("¿Qué desea incluir? (la leyenda de colores siempre se incluye)"))
        for casilla in self.casillas.values():
            casilla.setChecked(True)
            capa.addWidget(casilla)
        self.casillas["cambios"].setVisible(con_cambios)
        self.casillas["cambios"].setChecked(con_cambios)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        capa.addWidget(botones)

    def opciones(self) -> OpcionesExportacion:
        return OpcionesExportacion(**{c: v.isChecked() for c, v in self.casillas.items()})


def _tabla(encabezados: list[str]) -> QTableWidget:
    tabla = QTableWidget(0, len(encabezados))
    tabla.setHorizontalHeaderLabels(encabezados)
    tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    tabla.setSortingEnabled(False)
    return tabla


def _celda(valor: object) -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setData(Qt.ItemDataRole.DisplayRole, valor)
    return item


class PantallaResultados(Pantalla):
    titulo = "Resultados"

    def __init__(self) -> None:
        super().__init__()
        self.datos: DatosEscuela | None = None
        self.franjas: list[Franja] = []
        self.solucion: Solucion | None = None
        # Horario vigente con el que se compara la solución elegida (si es otra).
        self.vigente: Solucion | None = None
        self.cambios: list[Cambio] = []
        self.cambiadas: set[ClaveClase] = set()

        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self._al_elegir_solucion)
        self.boton_vigente = QPushButton("Marcar como vigente")
        self.boton_vigente.setToolTip(
            "El horario vigente es el que está en uso: las demás soluciones se comparan con "
            "él, y «Reajustar» en Generar parte de él cambiando lo menos posible"
        )
        self.boton_vigente.clicked.connect(self.marcar_vigente)
        self.resaltar = QCheckBox("Resaltar cambios respecto al vigente (↻)")
        self.resaltar.setChecked(True)
        self.resaltar.toggled.connect(self._actualizar_vistas)
        self.boton_eliminar = QPushButton("Eliminar solución")
        self.boton_eliminar.clicked.connect(self.eliminar_solucion)
        self.boton_exportar = QPushButton("Exportar a Excel…")
        self.boton_exportar.clicked.connect(self._dialogo_exportar)
        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        self.aviso_fijas = QLabel()
        self.aviso_fijas.setStyleSheet("color: palette(placeholder-text);")

        self.pestanas = QTabWidget()
        self.selector_grupo = QComboBox()
        self.vista_grupo = VistaHorario()
        self.selector_profesor = QComboBox()
        self.vista_profesor = VistaHorario()
        self.selector_espacio = QComboBox()
        self.vista_espacio = VistaHorario()
        self.vista_espacio.permite_fijar = False
        for selector, vista, nombre in (
            (self.selector_grupo, self.vista_grupo, "Por grupo"),
            (self.selector_profesor, self.vista_profesor, "Por profesor"),
            (self.selector_espacio, self.vista_espacio, "Por espacio"),
        ):
            pagina = QWidget()
            capa = QVBoxLayout(pagina)
            capa.addWidget(selector)
            capa.addWidget(vista, 1)
            self.pestanas.addTab(pagina, nombre)
            selector.currentIndexChanged.connect(self._actualizar_vistas)
            vista.fijar_pedido.connect(self.fijar)
        self.tabla_penalizaciones = _tabla(["Restricción blanda", "Valor", "Peso", "Ponderado"])
        self.pestanas.addTab(self.tabla_penalizaciones, "Penalizaciones")
        self.tabla_cambios = _tabla(ENCABEZADOS_CAMBIOS)
        self.tabla_cambios.setSortingEnabled(False)
        cabecera = self.tabla_cambios.horizontalHeader()
        for columna, modo in enumerate(
            [QHeaderView.ResizeMode.ResizeToContents] * 3 + [QHeaderView.ResizeMode.Stretch] * 2
        ):
            cabecera.setSectionResizeMode(columna, modo)
        self.indice_cambios = self.pestanas.addTab(self.tabla_cambios, "Cambios")
        self.tabla_carga = _tabla(
            ["Profesor", "Minutos", "Máximo", "% de carga", "Días con clase", "Huecos"]
        )
        self.pestanas.addTab(self.tabla_carga, "Carga docente")

        arriba = QHBoxLayout()
        arriba.addWidget(QLabel("Solución:"))
        arriba.addWidget(self.selector, 1)
        arriba.addWidget(self.boton_vigente)
        arriba.addWidget(self.boton_eliminar)
        arriba.addWidget(self.boton_exportar)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        capa.addLayout(arriba)
        capa.addWidget(self.resumen)
        capa.addWidget(self.resaltar)
        capa.addWidget(self.pestanas, 1)
        capa.addWidget(self.aviso_fijas)

    # --- Carga ----------------------------------------------------------------------

    def refrescar(self, solucion_id: int | None = None) -> None:
        assert self.repo is not None
        self.datos = self.repo.cargar_datos()
        self.franjas = generar_franjas(self.datos)
        actual = solucion_id or (self.solucion.id if self.solucion else None)
        soluciones = self.repo.listar_soluciones()
        pesos = self.datos.configuracion.pesos
        self.selector.blockSignals(True)
        self.selector.clear()
        for s in soluciones:
            total = penalizacion_total(s.penalizaciones, pesos)
            texto = f"#{s.id} · {s.fecha:%d/%m/%Y %H:%M} · {s.estado.value} · penalización {total}"
            if s.nota:
                texto += f" · {s.nota}"
            self.selector.addItem(f"★ VIGENTE · {texto}" if s.vigente else texto, s.id)
        if actual is None:
            actual = next((s.id for s in soluciones if s.vigente), None)
        indice = self.selector.findData(actual) if actual is not None else 0
        self.selector.setCurrentIndex(max(indice, 0))
        self.selector.blockSignals(False)
        self._llenar_selectores()
        self._al_elegir_solucion()

    def seleccionar_solucion(self, solucion_id: int) -> None:
        self.refrescar(solucion_id)

    def _llenar_selectores(self) -> None:
        assert self.datos is not None
        datos = self.datos
        for selector, elementos in (
            (self.selector_grupo, [(datos.nombre_grupo(g), g.id) for g in datos.grupos]),
            (self.selector_profesor, [(p.nombre, p.id) for p in datos.profesores]),
            (
                self.selector_espacio,
                [(f"{t} · {datos.nivel(n).nombre}", (t, n)) for t, n in espacios_usados(datos)],
            ),
        ):
            anterior = selector.currentData()
            selector.blockSignals(True)
            selector.clear()
            for texto, dato in elementos:
                selector.addItem(texto, dato)
            indice = selector.findData(anterior) if anterior is not None else 0
            selector.setCurrentIndex(max(indice, 0))
            selector.blockSignals(False)

    def _al_elegir_solucion(self) -> None:
        assert self.repo is not None
        solucion_id = self.selector.currentData()
        self.solucion = self.repo.cargar_solucion(solucion_id) if solucion_id else None
        hay = self.solucion is not None
        vigente_id = self.repo.solucion_vigente_id()
        self.vigente = None
        if hay and vigente_id is not None and vigente_id != solucion_id:
            self.vigente = self.repo.cargar_solucion(vigente_id)
        base = self.vigente.asignaciones if self.vigente else []
        nueva = self.solucion.asignaciones if self.solucion else []
        self.cambios = comparar(base, nueva) if self.vigente else []
        self.cambiadas = claves_cambiadas(base, nueva) if self.vigente else set()
        self.resaltar.setVisible(self.vigente is not None)
        self.pestanas.setTabVisible(self.indice_cambios, self.vigente is not None)
        self.pestanas.setTabText(self.indice_cambios, f"Cambios ({len(self.cambios)})")
        self.boton_vigente.setEnabled(hay and not (self.solucion and self.solucion.vigente))
        self.boton_eliminar.setEnabled(hay)
        self.boton_exportar.setEnabled(hay)
        self.pestanas.setEnabled(hay)
        if self.solucion is None:
            self.resumen.setText("Aún no hay soluciones guardadas. Genere un horario primero.")
        else:
            assert self.datos is not None
            s = self.solucion
            total = penalizacion_total(s.penalizaciones, self.datos.configuracion.pesos)
            self.resumen.setText(
                f"Estado: <b>{s.estado.value}</b> · generada el {s.fecha:%d/%m/%Y %H:%M} · "
                f"tiempo de cómputo {s.tiempo_s:.1f} s · penalización total <b>{total}</b>"
            )
            if s.vigente:
                self.resumen.setText(self.resumen.text() + "<br>★ Este es el horario vigente.")
            elif self.vigente is not None:
                afectados = len(profesores_afectados(self.cambios))
                self.resumen.setText(
                    self.resumen.text() + f"<br>Respecto al horario vigente #{self.vigente.id}: "
                    f"<b>{len(self.cambios)} clase(s) cambiada(s)</b>, "
                    f"{afectados} profesor(es) afectado(s). Vea la pestaña «Cambios»."
                )
            else:
                self.resumen.setText(
                    self.resumen.text()
                    + "<br>Aún no hay horario vigente. Si este es el que se usa en la escuela, "
                    "pulse «Marcar como vigente»."
                )
        self._actualizar_vistas()
        self._actualizar_tablas()

    # --- Vistas ---------------------------------------------------------------------

    def _fijas(self) -> set[tuple[int, int, str, int]]:
        assert self.datos is not None
        return {
            (f.grupo_id, f.asignatura_id, f.dia, f.indice_franja)
            for f in self.datos.asignaciones_fijas
        }

    def _actualizar_vistas(self) -> None:
        if self.datos is None:
            return
        asignaciones = self.solucion.asignaciones if self.solucion else []
        fijas = self._fijas()
        cambiadas = self.cambiadas if self.resaltar.isChecked() else set()
        n = len(self.datos.asignaciones_fijas)
        self.aviso_fijas.setText(
            f"{n} clase(s) fija(s): se respetarán al generar de nuevo. "
            "Clic derecho sobre una clase para fijarla o desfijarla."
        )
        if (g := self.selector_grupo.currentData()) is not None:
            self.vista_grupo.mostrar(
                cuadricula_grupo(self.datos, self.franjas, asignaciones, g), fijas, cambiadas
            )
        if (p := self.selector_profesor.currentData()) is not None:
            self.vista_profesor.mostrar(
                cuadricula_profesor(self.datos, self.franjas, asignaciones, p), fijas, cambiadas
            )
        if (e := self.selector_espacio.currentData()) is not None:
            tipo, nivel_id = e
            self.vista_espacio.mostrar(
                cuadricula_espacio(self.datos, self.franjas, asignaciones, tipo, nivel_id),
                fijas,
                cambiadas,
            )

    def _actualizar_tablas(self) -> None:
        assert self.datos is not None
        self.tabla_cambios.setRowCount(0)
        filas = filas_cambios(self.datos, self.franjas, self.cambios)
        self.tabla_cambios.setRowCount(len(filas))
        for fila, valores in enumerate(filas):
            for columna, dato in enumerate(valores):
                self.tabla_cambios.setItem(fila, columna, _celda(dato))
        for tabla in (self.tabla_penalizaciones, self.tabla_carga):
            tabla.setSortingEnabled(False)
            tabla.setRowCount(0)
        if self.solucion is None:
            return
        pesos = self.datos.configuracion.pesos.model_dump()
        self.tabla_penalizaciones.setRowCount(len(NOMBRES_PENALIZACIONES))
        for fila, (clave, nombre) in enumerate(NOMBRES_PENALIZACIONES.items()):
            valor = self.solucion.penalizaciones.get(clave, 0)
            for columna, dato in enumerate([nombre, valor, pesos[clave], valor * pesos[clave]]):
                self.tabla_penalizaciones.setItem(fila, columna, _celda(dato))
        cargas = carga_docente(self.datos, self.franjas, self.solucion.asignaciones)
        self.tabla_carga.setRowCount(len(cargas))
        for fila, c in enumerate(cargas):
            datos_fila = [c.nombre, c.minutos, c.maximo, round(c.porcentaje, 1), c.dias, c.huecos]
            for columna, dato in enumerate(datos_fila):
                self.tabla_carga.setItem(fila, columna, _celda(dato))
        self.tabla_carga.setSortingEnabled(True)

    # --- Ajustes manuales -----------------------------------------------------------

    def fijar(self, asignacion: Asignacion, fijar: bool) -> None:
        """Crea (o elimina) la asignación fija correspondiente a una clase."""
        assert self.repo is not None and self.datos is not None
        clave = clave_clase(asignacion)
        if fijar:
            if clave not in self._fijas():
                self.repo.guardar_asignacion_fija(
                    AsignacionFija(
                        grupo_id=asignacion.grupo_id,
                        asignatura_id=asignacion.asignatura_id,
                        profesor_id=asignacion.profesor_id,
                        dia=asignacion.dia,
                        indice_franja=asignacion.indice,
                    )
                )
        else:
            for fija in self.datos.asignaciones_fijas:
                if (fija.grupo_id, fija.asignatura_id, fija.dia, fija.indice_franja) == clave:
                    assert fija.id is not None
                    self.repo.eliminar_asignacion_fija(fija.id)
        self.datos = self.repo.cargar_datos()
        self.datos_cambiados.emit()
        self._actualizar_vistas()

    # --- Gestión de soluciones y exportación ----------------------------------------

    def marcar_vigente(self) -> None:
        if self.solucion is None or self.repo is None:
            return
        anterior = self.repo.solucion_vigente_id()
        if anterior is not None and not self.confirmar(
            "Marcar como vigente",
            f"La solución #{self.solucion.id} pasará a ser el horario vigente en lugar de "
            f"la #{anterior}. ¿Continuar?",
        ):
            return
        self.repo.marcar_vigente(self.solucion.id)
        self.datos_cambiados.emit()
        self.refrescar(self.solucion.id)

    def eliminar_solucion(self) -> bool:
        if self.solucion is None or self.repo is None:
            return False
        if not self.confirmar("Eliminar solución", f"¿Eliminar la solución #{self.solucion.id}?"):
            return False
        assert self.solucion.id is not None
        self.repo.eliminar_solucion(self.solucion.id)
        self.solucion = None
        self.refrescar()
        return True

    def _dialogo_exportar(self) -> None:
        if self.solucion is None:
            return
        dialogo = DialogoExportar(self, con_cambios=self.vigente is not None)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar a Excel", f"horario_{self.solucion.id}.xlsx", "Excel (*.xlsx)"
        )
        if not ruta:
            return
        try:
            destino = self.exportar(Path(ruta), dialogo.opciones())
        except OSError as error:
            self.avisar_error(f"No se pudo escribir el archivo:\n{error}")
            return
        QMessageBox.information(self, "Exportar a Excel", f"Horario exportado a:\n{destino}")

    def exportar(self, ruta: Path, opciones: OpcionesExportacion | None = None) -> Path:
        assert self.datos is not None and self.solucion is not None
        if ruta.suffix.lower() != ".xlsx":
            ruta = ruta.with_suffix(".xlsx")
        cambios = self.cambios if self.vigente is not None else None
        return exportar_excel(self.datos, self.solucion, self.franjas, ruta, opciones, cambios)
