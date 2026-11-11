"""Creado con Claude. Profesores por grupo: matriz grupos × asignaturas con el profesor fijo
de cada clase. Una celda vacía deja que el generador elija al profesor."""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import DatosEscuela, DocenteAsignado
from timetabling.gui.pantallas.base import Pantalla
from timetabling.gui.pantallas.plan import _encabezado

ROL_CLASE = Qt.ItemDataRole.UserRole  # (grupo_id, asignatura_id)
ROL_PROFESOR = Qt.ItemDataRole.UserRole + 1  # id del profesor o None
SIN_ASIGNAR = "—"


class _DelegadoProfesor(QStyledItemDelegate):
    """Lista desplegable con los profesores habilitados para esa asignatura y grado."""

    def __init__(self, pantalla: PantallaDocentes) -> None:
        super().__init__(pantalla.tabla)
        self.pantalla = pantalla

    def createEditor(  # noqa: N802 - nombre de Qt
        self,
        padre: QWidget,
        opcion: QStyleOptionViewItem,
        indice: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        editor = QComboBox(padre)
        grupo_id, asignatura_id = indice.data(ROL_CLASE)
        editor.addItem("(el generador decide)", None)
        for profesor_id, nombre in self.pantalla.candidatos(grupo_id, asignatura_id):
            editor.addItem(nombre, profesor_id)
        return editor

    def setEditorData(  # noqa: N802 - nombre de Qt
        self, editor: QWidget, indice: QModelIndex | QPersistentModelIndex
    ) -> None:
        assert isinstance(editor, QComboBox)
        posicion = editor.findData(indice.data(ROL_PROFESOR))
        editor.setCurrentIndex(max(posicion, 0))

    def setModelData(  # noqa: N802 - nombre de Qt
        self,
        editor: QWidget,
        modelo: QAbstractItemModel,
        indice: QModelIndex | QPersistentModelIndex,
    ) -> None:
        assert isinstance(editor, QComboBox)
        self.pantalla.asignar(*indice.data(ROL_CLASE), editor.currentData())


class PantallaDocentes(Pantalla):
    titulo = "Profesores por grupo"

    def __init__(self) -> None:
        super().__init__()
        self.tabla = QTableWidget()
        self.tabla.setItemDelegate(_DelegadoProfesor(self))
        self.resumen = QLabel()
        aviso = QLabel(
            "Profesor fijo de cada asignatura en cada grupo. El generador lo respeta y solo "
            "decide los horarios. Deje «—» para que el generador elija entre los habilitados."
        )
        aviso.setWordWrap(True)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        capa.addWidget(aviso)
        capa.addWidget(self.resumen)
        capa.addWidget(self.tabla, 1)
        self.datos = DatosEscuela()
        self._celdas: dict[tuple[int, int], QTableWidgetItem] = {}
        self._fila_grupo: dict[int, int] = {}

    def candidatos(self, grupo_id: int, asignatura_id: int) -> list[tuple[int, str]]:
        grado_id = self.datos.grupo(grupo_id).grado_id
        return [
            (p.id, p.nombre)
            for p in sorted(self.datos.profesores, key=lambda p: p.nombre.lower())
            if p.id is not None and asignatura_id in p.asignaturas and grado_id in p.grados
        ]

    def refrescar(self) -> None:
        assert self.repo is not None
        self.datos = self.repo.cargar_datos()
        datos = self.datos
        en_plan = {p.asignatura_id for p in datos.plan if p.horas_semanales > 0}
        asignaturas = [a for a in datos.asignaturas if a.id in en_plan]
        grupos = sorted(
            datos.grupos,
            key=lambda g: ([gr.id for gr in datos.grados].index(g.grado_id), g.seccion),
        )
        asignados = {(d.grupo_id, d.asignatura_id): d.profesor_id for d in datos.docentes_asignados}
        nombres = {p.id: p.nombre for p in datos.profesores}
        self.tabla.clear()
        self.tabla.setRowCount(len(grupos))
        self.tabla.setColumnCount(len(asignaturas))
        self.tabla.setHorizontalHeaderLabels([_encabezado(a.nombre) for a in asignaturas])
        self.tabla.setVerticalHeaderLabels([datos.nombre_grupo(g) for g in grupos])
        self._celdas = {}
        self._fila_grupo = {}
        gris = QBrush(QColor("#EEEEEE"))
        for fila, grupo in enumerate(grupos):
            assert grupo.id is not None
            self._fila_grupo[grupo.id] = fila
            plan = datos.plan_de_grado(grupo.grado_id)
            for columna, asignatura in enumerate(asignaturas):
                assert asignatura.id is not None
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if asignatura.id not in plan:
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    item.setBackground(gris)
                else:
                    profesor_id = asignados.get((grupo.id, asignatura.id))
                    item.setData(ROL_CLASE, (grupo.id, asignatura.id))
                    item.setData(ROL_PROFESOR, profesor_id)
                    item.setText(nombres.get(profesor_id, SIN_ASIGNAR))
                    item.setToolTip(f"{plan[asignatura.id]} h/semana")
                    self._celdas[(grupo.id, asignatura.id)] = item
                self.tabla.setItem(fila, columna, item)
        self.tabla.resizeColumnsToContents()
        self.tabla.horizontalHeader().setMinimumHeight(40)
        self._actualizar_resumen()

    def _actualizar_resumen(self) -> None:
        total = len(self._celdas)
        con_profesor = sum(1 for i in self._celdas.values() if i.data(ROL_PROFESOR) is not None)
        self.resumen.setText(f"{con_profesor} de {total} clases tienen profesor asignado.")

    def asignar(self, grupo_id: int, asignatura_id: int, profesor_id: int | None) -> None:
        """Fija (o quita, con ``None``) el profesor de una asignatura en un grupo."""
        assert self.repo is not None
        item = self._celdas[(grupo_id, asignatura_id)]
        if item.data(ROL_PROFESOR) == profesor_id:
            return
        if profesor_id is None:
            self.repo.quitar_docente(grupo_id, asignatura_id)
            item.setText(SIN_ASIGNAR)
        else:
            self.repo.asignar_docente(
                DocenteAsignado(
                    grupo_id=grupo_id, asignatura_id=asignatura_id, profesor_id=profesor_id
                )
            )
            item.setText(self.datos.profesor(profesor_id).nombre)
        item.setData(ROL_PROFESOR, profesor_id)
        self.datos = self.repo.cargar_datos()
        self._actualizar_resumen()
        self.datos_cambiados.emit()

    def seleccionar(self, entidad: str, elemento_id: int | None) -> None:
        if elemento_id in self._fila_grupo:
            self.tabla.selectRow(self._fila_grupo[elemento_id])
