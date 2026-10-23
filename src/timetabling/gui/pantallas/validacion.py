"""Creado con Claude. Pantalla de validación global: doble clic lleva al elemento."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from timetabling.gui.pantallas.base import Pantalla
from timetabling.nucleo.validacion import Problema, Severidad, validar

ROL_DESTINO = Qt.ItemDataRole.UserRole
_ENTIDADES = {
    "niveles": "Niveles",
    "grados": "Grados",
    "grupos": "Grupos",
    "asignaturas": "Asignaturas",
    "plan": "Plan de estudios",
    "profesores": "Profesores",
    "espacios": "Espacios",
    "asignaciones_fijas": "Asignaciones fijas",
}


class PantallaValidacion(Pantalla):
    titulo = "Validación"
    navegar = Signal(str, object)  # entidad, id del elemento (o None)

    def __init__(self) -> None:
        super().__init__()
        self.problemas: list[Problema] = []
        self.resumen = QLabel()
        revisar = QPushButton("Revisar ahora")
        revisar.clicked.connect(self.refrescar)
        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Severidad", "Sección", "Elemento", "Problema"])
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabla.setWordWrap(True)
        self.tabla.cellDoubleClicked.connect(self.ir_a)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        fila = QHBoxLayout()
        fila.addWidget(self.resumen, 1)
        fila.addWidget(revisar)
        capa.addLayout(fila)
        capa.addWidget(self.tabla, 1)
        ayuda = QLabel("Doble clic en un problema para ir al elemento correspondiente.")
        ayuda.setStyleSheet("color: palette(placeholder-text);")
        capa.addWidget(ayuda)

    def refrescar(self) -> None:
        assert self.repo is not None
        self.problemas = sorted(
            validar(self.repo.cargar_datos()), key=lambda p: p.severidad != Severidad.ERROR
        )
        errores = sum(p.severidad == Severidad.ERROR for p in self.problemas)
        advertencias = len(self.problemas) - errores
        if not self.problemas:
            self.resumen.setText("✔ No se encontraron problemas. Puede generar el horario.")
        else:
            texto = f"{errores} error(es) y {advertencias} advertencia(s)."
            if errores:
                texto += " Corrija los errores antes de generar."
            self.resumen.setText(texto)
        self.tabla.setRowCount(len(self.problemas))
        for fila, problema in enumerate(self.problemas):
            es_error = problema.severidad == Severidad.ERROR
            celdas = [
                "Error" if es_error else "Advertencia",
                _ENTIDADES.get(problema.entidad, problema.entidad),
                problema.elemento,
                problema.mensaje,
            ]
            for columna, texto in enumerate(celdas):
                item = QTableWidgetItem(texto)
                item.setData(ROL_DESTINO, (problema.entidad, problema.elemento_id))
                if columna == 0:
                    item.setForeground(QBrush(QColor("#C62828" if es_error else "#EF6C00")))
                self.tabla.setItem(fila, columna, item)
        self.tabla.resizeColumnsToContents()
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tabla.resizeRowsToContents()

    def ir_a(self, fila: int, _columna: int = 0) -> None:
        item = self.tabla.item(fila, 0)
        if item is not None:
            entidad, elemento_id = item.data(ROL_DESTINO)
            self.navegar.emit(entidad, elemento_id)
