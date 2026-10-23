"""Creado con Claude. Pantalla de asignaturas: color, espacio requerido, bloques dobles."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QLineEdit,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
)

from timetabling.dominio.colores import color_texto
from timetabling.dominio.modelos import Asignatura, BloqueDoble
from timetabling.gui.pantallas.base import PantallaListaFormulario

SIN_ESPACIO = "(ninguno)"
_BLOQUES = {
    BloqueDoble.NO: "No",
    BloqueDoble.PREFERIDO: "Preferido",
    BloqueDoble.OBLIGATORIO: "Obligatorio",
}


def icono_color(color: str) -> QIcon:
    mapa = QPixmap(14, 14)
    mapa.fill(QColor(color))
    return QIcon(mapa)


class PantallaAsignaturas(PantallaListaFormulario):
    titulo = "Asignaturas"
    tabla = "asignaturas"
    texto_nuevo = "Nueva asignatura"

    def __init__(self) -> None:
        super().__init__()
        self.nombre = QLineEdit()
        self.espacio = QComboBox()
        self.espacio.setEditable(True)
        self.max_horas = QSpinBox()
        self.max_horas.setRange(1, 12)
        self.bloque = QComboBox()
        for valor, texto in _BLOQUES.items():
            self.bloque.addItem(texto, valor)
        self.exigente = QCheckBox("Mejor en la primera mitad de la jornada")
        self.color = "#CCCCCC"
        self.boton_color = QPushButton()
        self.boton_color.clicked.connect(self._elegir_color)

        self.errores.fila(self.formulario, "nombre", "Nombre", self.nombre)
        self.errores.fila(
            self.formulario, "espacio_requerido", "Tipo de espacio requerido", self.espacio
        )
        self.errores.fila(
            self.formulario, "max_horas_dia", "Máximo de horas por día", self.max_horas
        )
        self.errores.fila(self.formulario, "bloque_doble", "Bloque doble", self.bloque)
        self.errores.fila(self.formulario, "exigente", "Exigente", self.exigente)
        self.errores.fila(self.formulario, "color", "Color", self.boton_color)
        self.capa_contenido.addStretch()

    def poner_color(self, color: str) -> None:
        self.color = color.upper()
        self.boton_color.setText(self.color)
        self.boton_color.setStyleSheet(
            f"background-color: {self.color}; color: {color_texto(self.color)};"
        )

    def _elegir_color(self) -> None:
        elegido = QColorDialog.getColor(QColor(self.color), self, "Color de la asignatura")
        if elegido.isValid():
            self.poner_color(elegido.name())

    def elementos(self) -> list[tuple[int, str]]:
        assert self.repo is not None
        return [(a.id, a.nombre) for a in self.repo.listar_asignaturas() if a.id is not None]

    def _llenar_lista(self, seleccion: int | None) -> None:
        super()._llenar_lista(seleccion)
        assert self.repo is not None
        colores = {a.id: a.color for a in self.repo.listar_asignaturas()}
        for fila in range(self.lista.count()):
            item: QListWidgetItem = self.lista.item(fila)
            item.setIcon(icono_color(colores.get(item.data(Qt.ItemDataRole.UserRole), "#CCCCCC")))

    def cargar_elemento(self, elemento_id: int | None) -> None:
        assert self.repo is not None
        asignaturas = self.repo.listar_asignaturas()
        asignatura = next((a for a in asignaturas if a.id == elemento_id), None) or Asignatura(
            nombre="(nueva)"
        )
        self.nombre.setText(asignatura.nombre if elemento_id is not None else "")
        tipos = sorted(
            {a.espacio_requerido for a in asignaturas if a.espacio_requerido}
            | {e.tipo for e in self.repo.listar_espacios()}
        )
        self.espacio.clear()
        self.espacio.addItems([SIN_ESPACIO, *tipos])
        self.espacio.setCurrentText(asignatura.espacio_requerido or SIN_ESPACIO)
        self.max_horas.setValue(asignatura.max_horas_dia)
        self.bloque.setCurrentIndex(self.bloque.findData(asignatura.bloque_doble))
        self.exigente.setChecked(asignatura.exigente)
        self.poner_color(asignatura.color)

    def guardar_elemento(self) -> int:
        assert self.repo is not None
        espacio = self.espacio.currentText().strip()
        asignatura = self.repo.guardar_asignatura(
            Asignatura(
                id=self.actual_id,
                nombre=self.nombre.text(),
                espacio_requerido=None if espacio in ("", SIN_ESPACIO) else espacio,
                max_horas_dia=self.max_horas.value(),
                bloque_doble=self.bloque.currentData(),
                exigente=self.exigente.isChecked(),
                color=self.color,
            )
        )
        assert asignatura.id is not None
        return asignatura.id

    def eliminar_elemento(self, elemento_id: int) -> None:
        assert self.repo is not None
        self.repo.eliminar_asignatura(elemento_id)
