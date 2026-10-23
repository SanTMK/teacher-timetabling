"""Creado con Claude. Widgets de arrastrar y soltar para capturar clases fijas.

``Paleta``: asignaturas del grupo con sus profesores; cada profesor (o «cualquiera») se
arrastra a la cuadrícula. ``CuadriculaFijas``: semana del grupo; recibe clases de la paleta,
permite moverlas entre celdas y devolverlas a la paleta para quitarlas.

Lo que se arrastra viaja como JSON con el tipo MIME ``MIME_FIJA``:
``{"asignatura_id", "profesor_id", "fija_id"?}`` (``fija_id`` solo si ya existe).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDrag, QDragMoveEvent, QDropEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
)

from timetabling.dominio.colores import color_texto
from timetabling.dominio.cuadricula import Cuadricula
from timetabling.dominio.modelos import NOMBRES_DIAS
from timetabling.gui.widgets.vista_horario import ALTO_FRANJA, ALTO_RECESO, GRIS_RECESO

MIME_FIJA = "application/x-timetabling-fija"
ROL_INFO = Qt.ItemDataRole.UserRole

Info = dict[str, Any]


def codificar(info: Info) -> QMimeData:
    mime = QMimeData()
    mime.setData(MIME_FIJA, json.dumps(info).encode())
    return mime


def decodificar(mime: QMimeData) -> Info | None:
    if not mime.hasFormat(MIME_FIJA):
        return None
    return json.loads(bytes(mime.data(MIME_FIJA).data()).decode())


class Paleta(QTreeWidget):
    """Asignaturas (no arrastrables) con sus profesores debajo (arrastrables)."""

    quitar_pedido = Signal(int)  # fija_id soltada sobre la paleta

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def agregar_asignatura(self, texto: str, color: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([texto])
        item.setBackground(0, QBrush(QColor(color)))
        item.setForeground(0, QBrush(QColor(color_texto(color))))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.addTopLevelItem(item)
        return item

    @staticmethod
    def agregar_profesor(padre: QTreeWidgetItem, texto: str, info: Info) -> QTreeWidgetItem:
        item = QTreeWidgetItem([texto])
        item.setData(0, ROL_INFO, info)
        item.setToolTip(0, "Arrástrelo a una hora de la semana")
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )
        padre.addChild(item)
        return item

    def info_seleccionada(self) -> Info | None:
        item = self.currentItem()
        return item.data(0, ROL_INFO) if item is not None else None

    def seleccionar_info(self, info: Info | None) -> None:
        for i in range(self.topLevelItemCount()):
            padre = self.topLevelItem(i)
            for j in range(padre.childCount()):
                if padre.child(j).data(0, ROL_INFO) == info:
                    self.setCurrentItem(padre.child(j))
                    return

    # --- Arrastre ------------------------------------------------------------------

    def mimeTypes(self) -> list[str]:  # noqa: N802 - nombre de Qt
        return [MIME_FIJA]

    def mimeData(self, items: Sequence[QTreeWidgetItem]) -> QMimeData:  # noqa: N802
        info = items[0].data(0, ROL_INFO) if items else None
        return codificar(info) if info else QMimeData()

    def _acepta(self, evento: QDragMoveEvent) -> None:
        info = decodificar(evento.mimeData())
        if info is not None and info.get("fija_id") is not None:
            evento.acceptProposedAction()
        else:
            evento.ignore()

    dragEnterEvent = _acepta  # noqa: N815 - nombre de Qt
    dragMoveEvent = _acepta  # noqa: N815 - nombre de Qt

    def dropEvent(self, evento: QDropEvent) -> None:  # noqa: N802 - nombre de Qt
        info = decodificar(evento.mimeData())
        if info is None or info.get("fija_id") is None:
            evento.ignore()
            return
        self.quitar_pedido.emit(info["fija_id"])
        evento.acceptProposedAction()


class CuadriculaFijas(QTableWidget):
    """Días × franjas de un grupo, con recesos intercalados (filas grises)."""

    soltado = Signal(dict, str, int)  # info, día, índice de franja
    quitar_pedido = Signal(int)  # fija_id

    def __init__(self) -> None:
        super().__init__()
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setWordWrap(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.verticalHeader().setMinimumSectionSize(1)
        self.dias: list[str] = []
        self._indice_de_fila: dict[int, int] = {}

    # --- Estructura ----------------------------------------------------------------

    def mostrar(self, cuadricula: Cuadricula) -> None:
        """Dibuja la semana vacía: una fila por franja y filas grises de receso."""
        self.dias = list(cuadricula.columnas)
        self._indice_de_fila = {}
        self.clearSpans()
        self.clear()
        self.setRowCount(len(cuadricula.filas))
        self.setColumnCount(len(self.dias))
        self.setHorizontalHeaderLabels([NOMBRES_DIAS.get(d, d) for d in self.dias])
        etiquetas = []
        for i, fila in enumerate(cuadricula.filas):
            if fila.receso is None:
                self._indice_de_fila[i] = len(self._indice_de_fila)
                etiquetas.append(fila.etiqueta)
                self.setRowHeight(i, ALTO_FRANJA)
                for c in range(len(self.dias)):
                    self.setItem(i, c, self._celda_vacia())
                continue
            etiquetas.append("")
            self.setRowHeight(i, ALTO_RECESO)
            item = QTableWidgetItem(f"{fila.receso} ({fila.etiqueta})")
            item.setBackground(QBrush(QColor(GRIS_RECESO)))
            item.setForeground(QBrush(QColor("#000000")))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.setItem(i, 0, item)
            if len(self.dias) > 1:
                self.setSpan(i, 0, 1, len(self.dias))
        self.setVerticalHeaderLabels(etiquetas)

    @staticmethod
    def _celda_vacia() -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return item

    def posicion(self, fila: int, columna: int) -> tuple[str, int] | None:
        """(día, índice de franja) de una celda, o ``None`` si es receso o está fuera."""
        indice = self._indice_de_fila.get(fila)
        if indice is None or not 0 <= columna < len(self.dias):
            return None
        return self.dias[columna], indice

    def celda(self, dia: str, indice: int) -> QTableWidgetItem | None:
        fila = next((f for f, i in self._indice_de_fila.items() if i == indice), None)
        if fila is None or dia not in self.dias:
            return None
        return self.item(fila, self.dias.index(dia))

    def poner_clase(
        self, dia: str, indice: int, texto: str, color: str, info: Info, ayuda: str
    ) -> None:
        item = self.celda(dia, indice)
        if item is None:
            return
        item.setText(texto)
        item.setBackground(QBrush(QColor(color)))
        item.setForeground(QBrush(QColor(color_texto(color))))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setToolTip(ayuda)
        item.setData(ROL_INFO, info)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        )

    def sombrear(self, dia: str, indice: int, color: str | None, ayuda: str = "") -> None:
        """Colorea una celda vacía (``None`` la deja en blanco)."""
        item = self.celda(dia, indice)
        if item is None or item.data(ROL_INFO):
            return
        item.setBackground(QBrush(QColor(color)) if color else QBrush())
        item.setToolTip(ayuda)

    def info_en(self, fila: int, columna: int) -> Info | None:
        item = self.item(fila, columna)
        return item.data(ROL_INFO) if item is not None else None

    # --- Arrastre ------------------------------------------------------------------

    def startDrag(self, acciones: Qt.DropAction) -> None:  # noqa: N802 - nombre de Qt
        item = self.currentItem()
        info = item.data(ROL_INFO) if item is not None else None
        if not info:
            return
        arrastre = QDrag(self)
        arrastre.setMimeData(codificar(info))
        arrastre.exec(Qt.DropAction.MoveAction)

    def destino(self, punto: QPoint, info: Info) -> tuple[str, int] | None:
        """Celda donde se puede soltar ``info``: franja libre o la misma clase."""
        indice = self.indexAt(punto)
        posicion = self.posicion(indice.row(), indice.column())
        if posicion is None:
            return None
        ocupante = self.info_en(indice.row(), indice.column())
        if ocupante and ocupante.get("fija_id") != info.get("fija_id"):
            return None
        return posicion

    def dragEnterEvent(self, evento: QDragMoveEvent) -> None:  # noqa: N802 - nombre de Qt
        if decodificar(evento.mimeData()) is not None:
            evento.acceptProposedAction()
        else:
            evento.ignore()

    def dragMoveEvent(self, evento: QDragMoveEvent) -> None:  # noqa: N802 - nombre de Qt
        info = decodificar(evento.mimeData())
        if info is not None and self.destino(evento.position().toPoint(), info) is not None:
            evento.acceptProposedAction()
        else:
            evento.ignore()

    def dropEvent(self, evento: QDropEvent) -> None:  # noqa: N802 - nombre de Qt
        info = decodificar(evento.mimeData())
        posicion = None if info is None else self.destino(evento.position().toPoint(), info)
        if info is None or posicion is None:
            evento.ignore()
            return
        evento.acceptProposedAction()
        self.soltado.emit(info, *posicion)

    # --- Quitar --------------------------------------------------------------------

    def keyPressEvent(self, evento: QKeyEvent) -> None:  # noqa: N802 - nombre de Qt
        item = self.currentItem()
        info = item.data(ROL_INFO) if item is not None else None
        if info and evento.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.quitar_pedido.emit(info["fija_id"])
            return
        super().keyPressEvent(evento)

    def _menu(self, punto: QPoint) -> None:
        item = self.itemAt(punto)
        info = item.data(ROL_INFO) if item is not None else None
        if not info:
            return
        menu = QMenu(self)
        accion = QAction("Quitar esta clase fija", menu)
        accion.triggered.connect(lambda: self.quitar_pedido.emit(info["fija_id"]))
        menu.addAction(accion)
        menu.exec(self.viewport().mapToGlobal(punto))
