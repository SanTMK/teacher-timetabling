"""Creado con Claude. Vista de horario: dibuja una ``Cuadricula`` en una tabla.

Misma lógica visual que la exportación: color por asignatura, recesos en gris y escala de
tiempo proporcional para profesores multinivel. Menú contextual para fijar o desfijar una
clase; las fijas se marcan con 📌.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import QHeaderView, QMenu, QTableWidget, QTableWidgetItem

from timetabling.dominio.colores import color_texto
from timetabling.dominio.cuadricula import Cuadricula
from timetabling.dominio.modelos import NOMBRES_DIAS, Asignacion

ROL_ASIGNACIONES = Qt.ItemDataRole.UserRole
ICONO_FIJA = "📌"
GRIS_RECESO = "#D9D9D9"
ALTO_FRANJA = 46
ALTO_RECESO = 20
ALTO_PROPORCIONAL = 8


def clave_clase(a: Asignacion) -> tuple[int, int, str, int]:
    return (a.grupo_id, a.asignatura_id, a.dia, a.indice)


class VistaHorario(QTableWidget):
    # (asignación, fijar: True para fijar, False para desfijar)
    fijar_pedido = Signal(object, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setWordWrap(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        # Sin esto Qt no permite filas más bajas que el texto del encabezado (~20 px).
        self.verticalHeader().setMinimumSectionSize(1)
        self.fijas: set[tuple[int, int, str, int]] = set()
        self.permite_fijar = True
        self.cuadricula: Cuadricula | None = None

    def mostrar(self, cuadricula: Cuadricula, fijas: set[tuple[int, int, str, int]]) -> None:
        self.cuadricula = cuadricula
        self.fijas = fijas
        self.clearSpans()
        self.clear()
        self.setRowCount(len(cuadricula.filas))
        self.setColumnCount(len(cuadricula.columnas))
        self.setHorizontalHeaderLabels([NOMBRES_DIAS.get(d, d) for d in cuadricula.columnas])
        etiquetas = []
        for i, fila in enumerate(cuadricula.filas):
            if fila.receso is not None:
                etiquetas.append("")
                self.setRowHeight(i, ALTO_RECESO)
                item = QTableWidgetItem(f"{fila.receso} ({fila.etiqueta})")
                item.setBackground(QBrush(QColor(GRIS_RECESO)))
                item.setForeground(QBrush(QColor("#000000")))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.setItem(i, 0, item)
                if self.columnCount() > 1:
                    self.setSpan(i, 0, 1, self.columnCount())
            elif cuadricula.proporcional:
                etiquetas.append(fila.etiqueta if fila.inicio % 30 == 0 else "")
                self.setRowHeight(i, ALTO_PROPORCIONAL)
            else:
                etiquetas.append(fila.etiqueta)
                self.setRowHeight(i, ALTO_FRANJA)
        self.setVerticalHeaderLabels(etiquetas)
        if cuadricula.proporcional:
            fuente = self.verticalHeader().font()
            fuente.setPointSize(8)
            self.verticalHeader().setFont(fuente)
        for bloque in cuadricula.bloques:
            fija = any(clave_clase(a) in fijas for a in bloque.asignaciones)
            texto = bloque.titulo + (f"\n{bloque.detalle}" if bloque.detalle else "")
            item = QTableWidgetItem(f"{ICONO_FIJA} {texto}" if fija else texto)
            item.setBackground(QBrush(QColor(bloque.color)))
            item.setForeground(QBrush(QColor(color_texto(bloque.color))))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setData(ROL_ASIGNACIONES, bloque.asignaciones)
            item.setToolTip(texto + ("\n(clase fija)" if fija else "\nClic derecho para fijarla"))
            self.setItem(bloque.fila, bloque.columna, item)
            if bloque.filas > 1:
                self.setSpan(bloque.fila, bloque.columna, bloque.filas, 1)

    def asignaciones_en(self, fila: int, columna: int) -> list[Asignacion]:
        item = self.item(fila, columna)
        if item is None:
            return []
        return list(item.data(ROL_ASIGNACIONES) or [])

    def _menu(self, posicion: QPoint) -> None:
        item = self.itemAt(posicion)
        if item is None or not self.permite_fijar:
            return
        asignaciones = self.asignaciones_en(item.row(), item.column())
        if len(asignaciones) != 1:
            return
        asignacion = asignaciones[0]
        fija = clave_clase(asignacion) in self.fijas
        menu = QMenu(self)
        accion = QAction("Desfijar esta clase" if fija else f"{ICONO_FIJA} Fijar esta clase", menu)
        accion.triggered.connect(lambda: self.fijar_pedido.emit(asignacion, not fija))
        menu.addAction(accion)
        menu.exec(self.viewport().mapToGlobal(posicion))
