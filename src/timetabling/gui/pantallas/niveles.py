"""Creado con Claude. Pantalla de niveles y recesos con vista previa de las franjas."""

from __future__ import annotations

from pydantic import ValidationError
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import DIAS_VALIDOS, NOMBRES_DIAS, Nivel, Receso, a_hhmm
from timetabling.gui.pantallas.base import (
    PantallaListaFormulario,
    editor_hora,
    leer_hora,
    poner_hora,
)
from timetabling.nucleo.franjas import generar_franjas_nivel


class PantallaNiveles(PantallaListaFormulario):
    titulo = "Niveles"
    tabla = "niveles"
    texto_nuevo = "Nuevo nivel"

    def __init__(self) -> None:
        super().__init__()
        self.nombre = QLineEdit()
        self.duracion = QSpinBox()
        self.duracion.setRange(5, 240)
        self.duracion.setSuffix(" min")
        self.inicio = editor_hora(7 * 60)
        self.fin = editor_hora(14 * 60)
        self.dias: dict[str, QCheckBox] = {}
        caja_dias = QWidget()
        capa_dias = QHBoxLayout(caja_dias)
        capa_dias.setContentsMargins(0, 0, 0, 0)
        for dia in DIAS_VALIDOS:
            self.dias[dia] = QCheckBox(dia)
            self.dias[dia].setToolTip(NOMBRES_DIAS[dia])
            capa_dias.addWidget(self.dias[dia])
        capa_dias.addStretch()
        self.sin_huecos = QCheckBox("Las clases de los alumnos deben ser continuas")

        self.errores.fila(self.formulario, "nombre", "Nombre", self.nombre)
        self.errores.fila(
            self.formulario, "duracion_min", "Duración de la hora-clase", self.duracion
        )
        self.errores.fila(self.formulario, "inicio_jornada", "Inicio de la jornada", self.inicio)
        self.errores.fila(self.formulario, "fin_jornada", "Fin de la jornada", self.fin)
        self.errores.fila(self.formulario, "dias", "Días lectivos", caja_dias)
        self.errores.fila(self.formulario, "sin_huecos_alumnos", "Sin huecos", self.sin_huecos)

        caja_recesos = QGroupBox("Recesos")
        capa_recesos = QVBoxLayout(caja_recesos)
        self.recesos = QTableWidget(0, 3)
        self.recesos.setHorizontalHeaderLabels(["Nombre", "Inicio", "Fin"])
        self.recesos.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.recesos.setMinimumHeight(110)
        capa_recesos.addWidget(self.recesos)
        botones = QHBoxLayout()
        agregar = QPushButton("Agregar receso")
        agregar.clicked.connect(lambda: self.agregar_receso(Receso(inicio=600, fin=630)))
        quitar = QPushButton("Quitar receso")
        quitar.clicked.connect(self.quitar_receso)
        botones.addWidget(agregar)
        botones.addWidget(quitar)
        botones.addStretch()
        capa_recesos.addLayout(botones)
        self.error_recesos = QLabel()
        self.error_recesos.setStyleSheet("color: #C62828;")
        capa_recesos.addWidget(self.error_recesos)

        caja_vista = QGroupBox("Vista previa de las franjas")
        capa_vista = QVBoxLayout(caja_vista)
        self.resumen_franjas = QLabel()
        self.vista_franjas = QListWidget()
        self.vista_franjas.setMinimumHeight(150)
        capa_vista.addWidget(self.resumen_franjas)
        capa_vista.addWidget(self.vista_franjas)

        self.capa_contenido.addWidget(caja_recesos)
        self.capa_contenido.addWidget(caja_vista)
        self.capa_contenido.addStretch()

        for senal in (
            self.nombre.textChanged,
            self.duracion.valueChanged,
            self.inicio.timeChanged,
            self.fin.timeChanged,
            self.recesos.itemChanged,
        ):
            senal.connect(self.actualizar_vista_previa)
        for casilla in self.dias.values():
            casilla.toggled.connect(self.actualizar_vista_previa)

    # --- Recesos --------------------------------------------------------------------

    def agregar_receso(self, receso: Receso) -> None:
        fila = self.recesos.rowCount()
        self.recesos.blockSignals(True)
        self.recesos.insertRow(fila)
        self.recesos.setItem(fila, 0, QTableWidgetItem(receso.nombre))
        for columna, minutos in ((1, receso.inicio), (2, receso.fin)):
            editor = editor_hora(minutos)
            editor.timeChanged.connect(self.actualizar_vista_previa)
            self.recesos.setCellWidget(fila, columna, editor)
        self.recesos.blockSignals(False)
        self.actualizar_vista_previa()

    def quitar_receso(self) -> None:
        fila = self.recesos.currentRow()
        if fila < 0:
            fila = self.recesos.rowCount() - 1
        if fila >= 0:
            self.recesos.removeRow(fila)
            self.actualizar_vista_previa()

    def _leer_recesos(self) -> list[Receso]:
        recesos = []
        for fila in range(self.recesos.rowCount()):
            item = self.recesos.item(fila, 0)
            inicio = self.recesos.cellWidget(fila, 1)
            fin = self.recesos.cellWidget(fila, 2)
            assert isinstance(inicio, QTimeEdit) and isinstance(fin, QTimeEdit)
            recesos.append(
                Receso(
                    nombre=item.text() if item else "Receso",
                    inicio=leer_hora(inicio),
                    fin=leer_hora(fin),
                )
            )
        return recesos

    # --- Formulario -----------------------------------------------------------------

    def _leer_nivel(self) -> Nivel:
        return Nivel(
            id=self.actual_id,
            nombre=self.nombre.text(),
            duracion_min=self.duracion.value(),
            inicio_jornada=leer_hora(self.inicio),
            fin_jornada=leer_hora(self.fin),
            dias=[d for d, c in self.dias.items() if c.isChecked()],
            recesos=self._leer_recesos(),
            sin_huecos_alumnos=self.sin_huecos.isChecked(),
        )

    def actualizar_vista_previa(self) -> None:
        self.vista_franjas.clear()
        self.error_recesos.clear()
        try:
            nivel = self._leer_nivel().model_copy(update={"id": self.actual_id or 0})
        except ValidationError as error:
            self.resumen_franjas.setText("Corrija los datos para ver las franjas.")
            if any(e["loc"] and e["loc"][0] == "recesos" for e in error.errors()):
                self.error_recesos.setText("Algún receso tiene la hora de inicio ≥ la de fin.")
            return
        franjas = generar_franjas_nivel(nivel)
        primer_dia = [f for f in franjas if f.dia == nivel.dias[0]]
        self.resumen_franjas.setText(
            f"{len(primer_dia)} franjas por día · {len(franjas)} por semana"
        )
        recesos = sorted(nivel.recesos, key=lambda r: r.inicio)
        for f in primer_dia:
            for receso in [r for r in recesos if r.fin <= f.inicio]:
                self.vista_franjas.addItem(
                    f"   {receso.nombre}: {a_hhmm(receso.inicio)}–{a_hhmm(receso.fin)}"
                )
                recesos.remove(receso)
            self.vista_franjas.addItem(f"{f.indice + 1}. {a_hhmm(f.inicio)}–{a_hhmm(f.fin)}")

    def elementos(self) -> list[tuple[int, str]]:
        assert self.repo is not None
        return [(n.id, n.nombre) for n in self.repo.listar_niveles() if n.id is not None]

    def cargar_elemento(self, elemento_id: int | None) -> None:
        assert self.repo is not None
        nivel = next((n for n in self.repo.listar_niveles() if n.id == elemento_id), None)
        if nivel is None:
            nivel = Nivel(
                nombre="(nuevo)", duracion_min=50, inicio_jornada=7 * 60, fin_jornada=14 * 60
            )
        self.nombre.setText(nivel.nombre if elemento_id is not None else "")
        self.duracion.setValue(nivel.duracion_min)
        poner_hora(self.inicio, nivel.inicio_jornada)
        poner_hora(self.fin, nivel.fin_jornada)
        for dia, casilla in self.dias.items():
            casilla.setChecked(dia in nivel.dias)
        self.sin_huecos.setChecked(nivel.sin_huecos_alumnos)
        self.recesos.setRowCount(0)
        for receso in nivel.recesos:
            self.agregar_receso(receso)
        self.actualizar_vista_previa()

    def guardar_elemento(self) -> int:
        assert self.repo is not None
        nivel = self.repo.guardar_nivel(self._leer_nivel())
        assert nivel.id is not None
        return nivel.id

    def eliminar_elemento(self, elemento_id: int) -> None:
        assert self.repo is not None
        self.repo.eliminar_nivel(elemento_id)
