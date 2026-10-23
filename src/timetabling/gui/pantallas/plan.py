"""Creado con Claude. Plan de estudios: matriz grados × asignaturas con horas semanales."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QLabel,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import PlanEstudios
from timetabling.gui.pantallas.base import Pantalla
from timetabling.nucleo.franjas import generar_franjas_nivel

ROL_ID = Qt.ItemDataRole.UserRole


def _encabezado(nombre: str) -> str:
    """Parte en dos líneas los nombres largos para que las columnas sean angostas."""
    if len(nombre) <= 12 or " " not in nombre:
        return nombre
    mitad = len(nombre) // 2
    espacios = [i for i, c in enumerate(nombre) if c == " "]
    corte = min(espacios, key=lambda i: abs(i - mitad))
    return nombre[:corte] + "\n" + nombre[corte + 1 :]


class _DelegadoHoras(QStyledItemDelegate):
    def createEditor(  # noqa: N802 - nombre de Qt
        self,
        padre: QWidget,
        opcion: QStyleOptionViewItem,
        indice: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        editor = QSpinBox(padre)
        editor.setRange(0, 60)
        return editor


class PantallaPlan(Pantalla):
    titulo = "Plan de estudios"

    def __init__(self) -> None:
        super().__init__()
        self.tabla = QTableWidget()
        self.tabla.setItemDelegate(_DelegadoHoras(self.tabla))
        self.tabla.itemChanged.connect(self._al_cambiar)
        self.aviso = QLabel(
            "Horas-clase semanales por grado. La columna Total compara la suma con las "
            "franjas semanales del nivel."
        )
        self.aviso.setWordWrap(True)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        capa.addWidget(self.aviso)
        capa.addWidget(self.tabla, 1)
        self._franjas_nivel: dict[int, int] = {}
        self._fila_grado: dict[int, int] = {}

    def refrescar(self) -> None:
        assert self.repo is not None
        datos = self.repo.cargar_datos()
        self._franjas_nivel = {
            n.id: len(generar_franjas_nivel(n)) for n in datos.niveles if n.id is not None
        }
        horas = {(p.grado_id, p.asignatura_id): p.horas_semanales for p in datos.plan}
        self.tabla.blockSignals(True)
        self.tabla.clear()
        self.tabla.setRowCount(len(datos.grados))
        self.tabla.setColumnCount(len(datos.asignaturas) + 1)
        self.tabla.setHorizontalHeaderLabels(
            ["Total"] + [_encabezado(a.nombre) for a in datos.asignaturas]
        )
        self.tabla.setVerticalHeaderLabels(
            [f"{datos.nivel(g.nivel_id).nombre} · {g.nombre}" for g in datos.grados]
        )
        self._fila_grado = {}
        for fila, grado in enumerate(datos.grados):
            assert grado.id is not None
            self._fila_grado[grado.id] = fila
            for columna, asignatura in enumerate(datos.asignaturas, start=1):
                valor = horas.get((grado.id, asignatura.id), 0)
                item = QTableWidgetItem(str(valor) if valor else "")
                item.setData(ROL_ID, (grado.id, asignatura.id))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tabla.setItem(fila, columna, item)
            total = QTableWidgetItem()
            total.setFlags(Qt.ItemFlag.ItemIsEnabled)
            total.setData(ROL_ID, ("total", grado.nivel_id))
            total.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tabla.setItem(fila, 0, total)
            self._actualizar_total(fila)
        self.tabla.resizeColumnsToContents()
        self.tabla.horizontalHeader().setMinimumHeight(40)
        self.tabla.blockSignals(False)

    def _actualizar_total(self, fila: int) -> None:
        suma = 0
        for columna in range(1, self.tabla.columnCount()):
            item = self.tabla.item(fila, columna)
            if item and item.text().strip().isdigit():
                suma += int(item.text())
        total = self.tabla.item(fila, 0)
        nivel_id = total.data(ROL_ID)[1]
        disponibles = self._franjas_nivel.get(nivel_id, 0)
        total.setText(f"{suma} / {disponibles}")
        excede = suma > disponibles
        total.setForeground(QBrush(QColor("#C62828" if excede else "#2E7D32")))
        total.setToolTip(
            "Excede las franjas disponibles del nivel"
            if excede
            else "Cabe en las franjas del nivel"
        )

    def _al_cambiar(self, item: QTableWidgetItem) -> None:
        dato = item.data(ROL_ID)
        if self.repo is None or not dato or dato[0] == "total":
            return
        texto = item.text().strip()
        if texto and not texto.isdigit():
            self.tabla.blockSignals(True)
            item.setText("")
            self.tabla.blockSignals(False)
            texto = ""
        horas = int(texto) if texto else 0
        if horas == 0 and texto:
            self.tabla.blockSignals(True)
            item.setText("")
            self.tabla.blockSignals(False)
        grado_id, asignatura_id = dato
        self.repo.guardar_plan(
            PlanEstudios(grado_id=grado_id, asignatura_id=asignatura_id, horas_semanales=horas)
        )
        self.tabla.blockSignals(True)
        self._actualizar_total(item.row())
        self.tabla.blockSignals(False)
        self.datos_cambiados.emit()

    def poner_horas(self, grado_id: int, asignatura_id: int, horas: int) -> None:
        """Equivalente a escribir en la celda (usado en pruebas)."""
        fila = self._fila_grado[grado_id]
        for columna in range(1, self.tabla.columnCount()):
            item = self.tabla.item(fila, columna)
            if item.data(ROL_ID) == (grado_id, asignatura_id):
                item.setText(str(horas))
                return
        raise KeyError((grado_id, asignatura_id))

    def seleccionar(self, entidad: str, elemento_id: int | None) -> None:
        if elemento_id in self._fila_grado:
            self.tabla.selectRow(self._fila_grado[elemento_id])
