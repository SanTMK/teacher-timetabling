"""Creado con Claude. Pantalla de espacios especiales (laboratorios, patios, salas…)."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLineEdit, QSpinBox

from timetabling.dominio.modelos import Espacio
from timetabling.gui.pantallas.base import PantallaListaFormulario


class PantallaEspacios(PantallaListaFormulario):
    titulo = "Espacios"
    tabla = "espacios"
    texto_nuevo = "Nuevo espacio"

    def __init__(self) -> None:
        super().__init__()
        self.nombre = QLineEdit()
        self.tipo = QComboBox()
        self.tipo.setEditable(True)
        self.cantidad = QSpinBox()
        self.cantidad.setRange(0, 100)
        self.errores.fila(self.formulario, "nombre", "Nombre", self.nombre)
        self.errores.fila(self.formulario, "tipo", "Tipo", self.tipo)
        self.errores.fila(self.formulario, "cantidad", "Cantidad", self.cantidad)
        self.capa_contenido.addStretch()

    def elementos(self) -> list[tuple[int, str]]:
        assert self.repo is not None
        return [
            (e.id, f"{e.nombre} ({e.tipo} × {e.cantidad})")
            for e in self.repo.listar_espacios()
            if e.id is not None
        ]

    def cargar_elemento(self, elemento_id: int | None) -> None:
        assert self.repo is not None
        espacios = self.repo.listar_espacios()
        espacio = next((e for e in espacios if e.id == elemento_id), None)
        tipos = sorted(
            {e.tipo for e in espacios}
            | {a.espacio_requerido for a in self.repo.listar_asignaturas() if a.espacio_requerido}
        )
        self.tipo.clear()
        self.tipo.addItems(tipos)
        self.nombre.setText(espacio.nombre if espacio else "")
        self.tipo.setCurrentText(espacio.tipo if espacio else "")
        self.cantidad.setValue(espacio.cantidad if espacio else 1)

    def guardar_elemento(self) -> int:
        assert self.repo is not None
        espacio = self.repo.guardar_espacio(
            Espacio(
                id=self.actual_id,
                nombre=self.nombre.text(),
                tipo=self.tipo.currentText(),
                cantidad=self.cantidad.value(),
            )
        )
        assert espacio.id is not None
        return espacio.id

    def eliminar_elemento(self, elemento_id: int) -> None:
        assert self.repo is not None
        self.repo.eliminar_espacio(elemento_id)
