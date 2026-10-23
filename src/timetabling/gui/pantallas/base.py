"""Creado con Claude. Base común de las pantallas: acceso al proyecto, errores por campo,
confirmaciones y utilidades de formularios."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from timetabling.persistencia.repositorio import Repositorio

_NOMBRES_TABLA = {
    "niveles": "el nivel",
    "grados": "el grado",
    "grupos": "el grupo",
    "asignaturas": "la asignatura",
    "profesores": "el profesor",
}


def traducir_error(error: dict[str, Any]) -> str:
    """Mensaje en español para un error de pydantic."""
    tipo = error.get("type", "")
    ctx = error.get("ctx") or {}
    if tipo == "value_error":
        mensaje = str(error.get("msg", ""))
        return mensaje.removeprefix("Value error, ")
    if tipo == "greater_than_equal":
        return f"Debe ser mayor o igual que {ctx.get('ge')}"
    if tipo == "less_than_equal":
        return f"Debe ser menor o igual que {ctx.get('le')}"
    if tipo in ("missing", "string_too_short"):
        return "Campo obligatorio"
    if tipo.startswith("int"):
        return "Debe ser un número entero"
    return str(error.get("msg", "Valor inválido"))


class ErroresFormulario:
    """Etiquetas de error que se muestran junto a cada campo de un formulario."""

    def __init__(self) -> None:
        self._etiquetas: dict[str, QLabel] = {}
        self.general = self._nueva_etiqueta()

    @staticmethod
    def _nueva_etiqueta() -> QLabel:
        etiqueta = QLabel()
        etiqueta.setObjectName("error")
        etiqueta.setStyleSheet("color: #C62828;")
        etiqueta.setWordWrap(True)
        etiqueta.hide()
        return etiqueta

    def fila(self, formulario: QFormLayout, campo: str, rotulo: str, editor: QWidget) -> None:
        """Agrega ``editor`` al formulario con su etiqueta de error debajo."""
        contenedor = QWidget()
        capa = QVBoxLayout(contenedor)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(2)
        capa.addWidget(editor)
        etiqueta = self._nueva_etiqueta()
        capa.addWidget(etiqueta)
        self._etiquetas[campo] = etiqueta
        formulario.addRow(rotulo, contenedor)

    def limpiar(self) -> None:
        for etiqueta in [*self._etiquetas.values(), self.general]:
            etiqueta.clear()
            etiqueta.hide()

    def mostrar(self, campo: str | None, mensaje: str) -> None:
        etiqueta = self._etiquetas.get(campo or "", self.general)
        texto = f"{etiqueta.text()}\n{mensaje}" if etiqueta.text() else mensaje
        etiqueta.setText(texto)
        etiqueta.show()

    def desde_validacion(self, error: ValidationError) -> None:
        for detalle in error.errors():
            loc = detalle.get("loc") or ()
            campo = str(loc[0]) if loc else None
            self.mostrar(campo if campo in self._etiquetas else None, traducir_error(detalle))

    def texto(self, campo: str | None = None) -> str:
        return self._etiquetas.get(campo or "", self.general).text()

    def hay_errores(self) -> bool:
        return any(e.text() for e in [*self._etiquetas.values(), self.general])


class Pantalla(QWidget):
    """Pantalla de la barra lateral. Las subclases implementan ``refrescar``."""

    titulo = ""
    # Emitida tras guardar cambios, para que la ventana marque otras pantallas como viejas.
    datos_cambiados = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.repo: Repositorio | None = None

    def establecer_repositorio(self, repo: Repositorio | None) -> None:
        self.repo = repo
        self.setEnabled(repo is not None)
        if repo is not None:
            self.refrescar()

    def refrescar(self) -> None:
        """Vuelve a leer los datos del proyecto."""

    def seleccionar(self, entidad: str, elemento_id: int | None) -> None:
        """Enfoca un elemento (usado al navegar desde la validación)."""

    # --- Diálogos (reemplazables en las pruebas) ------------------------------------

    def confirmar(self, titulo: str, texto: str) -> bool:
        respuesta = QMessageBox.question(self, titulo, texto)
        return respuesta == QMessageBox.StandardButton.Yes

    def avisar_error(self, texto: str) -> None:
        QMessageBox.warning(self, "Error", texto)

    def confirmar_borrado(self, tabla: str, elemento_id: int, nombre: str) -> bool:
        """Pregunta antes de borrar, indicando qué otros datos se verán afectados."""
        assert self.repo is not None
        afectados = self.repo.afectados_por_eliminar(tabla, elemento_id)
        texto = f"¿Eliminar {_NOMBRES_TABLA.get(tabla, 'el elemento')} «{nombre}»?"
        if afectados:
            detalle = "\n".join(f"  • {cuantos} {que}" for que, cuantos in afectados.items())
            texto += f"\n\nTambién se eliminarán o modificarán:\n{detalle}"
        return self.confirmar("Confirmar eliminación", texto)

    def guardar_con(
        self, errores: ErroresFormulario, accion: Callable[[], object], campo_nombre: str = "nombre"
    ) -> bool:
        """Ejecuta ``accion`` mostrando los errores de validación junto a los campos."""
        errores.limpiar()
        try:
            accion()
        except ValidationError as error:
            errores.desde_validacion(error)
            return False
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error):
                errores.mostrar(campo_nombre, "Ya existe un elemento con ese nombre")
            else:
                errores.mostrar(None, f"No se pudo guardar: {error}")
            return False
        self.datos_cambiados.emit()
        return True


def editor_hora(minutos: int = 8 * 60) -> QTimeEdit:
    editor = QTimeEdit()
    editor.setDisplayFormat("HH:mm")
    poner_hora(editor, minutos)
    return editor


def poner_hora(editor: QTimeEdit, minutos: int) -> None:
    editor.setTime(QTime(min(minutos // 60, 23), minutos % 60 if minutos < 24 * 60 else 59))


def leer_hora(editor: QTimeEdit) -> int:
    hora = editor.time()
    return hora.hour() * 60 + hora.minute()


class PantallaListaFormulario(Pantalla):
    """Lista de elementos a la izquierda y formulario de edición a la derecha.

    Las subclases definen ``tabla`` (para advertir dependencias al borrar), construyen sus
    campos en ``self.formulario`` y ``self.errores`` e implementan ``elementos``,
    ``cargar_elemento``, ``guardar_elemento`` y ``eliminar_elemento``.
    """

    tabla = ""
    texto_nuevo = "Nuevo"

    def __init__(self) -> None:
        super().__init__()

        self.errores = ErroresFormulario()
        self.actual_id: int | None = None
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self._al_seleccionar)
        self.boton_nuevo = QPushButton(self.texto_nuevo)
        self.boton_nuevo.clicked.connect(self.nuevo)
        self.boton_eliminar = QPushButton("Eliminar")
        self.boton_eliminar.clicked.connect(self.eliminar)
        self.boton_guardar = QPushButton("Guardar")
        self.boton_guardar.setDefault(True)
        self.boton_guardar.clicked.connect(self.guardar)
        self.estado = QLabel()

        izquierda = QWidget()
        capa_izq = QVBoxLayout(izquierda)
        capa_izq.setContentsMargins(0, 0, 0, 0)
        capa_izq.addWidget(self.lista)
        botones_lista = QHBoxLayout()
        botones_lista.addWidget(self.boton_nuevo)
        botones_lista.addWidget(self.boton_eliminar)
        capa_izq.addLayout(botones_lista)

        self.contenido = QWidget()
        self.capa_contenido = QVBoxLayout(self.contenido)
        self.formulario = QFormLayout()
        self.formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.capa_contenido.addLayout(self.formulario)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(self.contenido)
        derecha = QWidget()
        capa_der = QVBoxLayout(derecha)
        capa_der.setContentsMargins(0, 0, 0, 0)
        capa_der.addWidget(desplazable, 1)
        capa_der.addWidget(self.errores.general)
        botones = QHBoxLayout()
        botones.addWidget(self.estado, 1)
        botones.addWidget(self.boton_guardar)
        capa_der.addLayout(botones)

        divisor = QSplitter()
        divisor.addWidget(izquierda)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(1, 3)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        capa.addWidget(divisor, 1)

    # --- A implementar --------------------------------------------------------------

    def elementos(self) -> list[tuple[int, str]]:
        raise NotImplementedError

    def cargar_elemento(self, elemento_id: int | None) -> None:
        """Llena el formulario (``None`` = elemento nuevo, valores por defecto)."""
        raise NotImplementedError

    def guardar_elemento(self) -> int:
        """Guarda el formulario y devuelve el id. Puede lanzar ``ValidationError``."""
        raise NotImplementedError

    def eliminar_elemento(self, elemento_id: int) -> None:
        raise NotImplementedError

    # --- Comportamiento común -------------------------------------------------------

    def refrescar(self) -> None:
        self._llenar_lista(self.actual_id)

    def _llenar_lista(self, seleccion: int | None) -> None:
        self.lista.blockSignals(True)
        self.lista.clear()
        fila_sel = -1
        for fila, (elemento_id, texto) in enumerate(self.elementos()):
            elemento = QListWidgetItem(texto)
            elemento.setData(Qt.ItemDataRole.UserRole, elemento_id)
            self.lista.addItem(elemento)
            if elemento_id == seleccion:
                fila_sel = fila
        self.lista.blockSignals(False)
        if fila_sel >= 0:
            self.lista.setCurrentRow(fila_sel)
        elif self.lista.count():
            self.lista.setCurrentRow(0)
        else:
            self.nuevo()

    def _al_seleccionar(self, fila: int) -> None:
        if fila < 0:
            return
        self.actual_id = self.lista.item(fila).data(Qt.ItemDataRole.UserRole)
        self.errores.limpiar()
        self.estado.clear()
        self.cargar_elemento(self.actual_id)
        self.boton_eliminar.setEnabled(True)

    def nuevo(self) -> None:
        self.lista.blockSignals(True)
        self.lista.clearSelection()
        self.lista.setCurrentRow(-1)
        self.lista.blockSignals(False)
        self.actual_id = None
        self.errores.limpiar()
        self.estado.setText("Elemento nuevo")
        self.cargar_elemento(None)
        self.boton_eliminar.setEnabled(False)

    def guardar(self) -> bool:
        resultado: list[int] = []
        if not self.guardar_con(self.errores, lambda: resultado.append(self.guardar_elemento())):
            return False
        self.actual_id = resultado[0]
        self._llenar_lista(self.actual_id)
        self.estado.setText("Cambios guardados.")
        return True

    def eliminar(self) -> bool:
        if self.actual_id is None or self.repo is None:
            return False
        nombre = self.lista.currentItem().text() if self.lista.currentItem() else ""
        if not self.confirmar_borrado(self.tabla, self.actual_id, nombre):
            return False
        self.eliminar_elemento(self.actual_id)
        self.actual_id = None
        self.datos_cambiados.emit()
        self._llenar_lista(None)
        return True

    def seleccionar(self, entidad: str, elemento_id: int | None) -> None:
        if elemento_id is not None:
            self._llenar_lista(elemento_id)
