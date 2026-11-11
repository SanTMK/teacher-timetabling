"""Creado con Claude. Pantalla de niveles y recesos con vista previa de las franjas."""

from __future__ import annotations

from pydantic import ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from timetabling.dominio.modelos import (
    DIAS_VALIDOS,
    NOMBRES_DIAS,
    Evento,
    Nivel,
    Receso,
    a_hhmm,
)
from timetabling.gui.pantallas.base import (
    PantallaListaFormulario,
    editor_hora,
    leer_hora,
    poner_hora,
)
from timetabling.nucleo.franjas import evento_de_franja, generar_franjas_nivel

ROL_ID = Qt.ItemDataRole.UserRole


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

        caja_eventos = QGroupBox("Eventos (hora cívica)")
        capa_eventos = QVBoxLayout(caja_eventos)
        ayuda_eventos = QLabel(
            "Actividades de todo el nivel en un día y hora. Los grupos no tienen clase en las "
            "franjas que tocan; en «Profesores» se marca qué maestros asisten."
        )
        ayuda_eventos.setWordWrap(True)
        capa_eventos.addWidget(ayuda_eventos)
        self.eventos = QTableWidget(0, 4)
        self.eventos.setHorizontalHeaderLabels(["Nombre", "Día", "Inicio", "Fin"])
        self.eventos.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.eventos.setMinimumHeight(90)
        capa_eventos.addWidget(self.eventos)
        botones_eventos = QHBoxLayout()
        agregar_evento = QPushButton("Agregar evento")
        agregar_evento.clicked.connect(self.agregar_evento_nuevo)
        quitar_evento = QPushButton("Quitar evento")
        quitar_evento.clicked.connect(self.quitar_evento)
        botones_eventos.addWidget(agregar_evento)
        botones_eventos.addWidget(quitar_evento)
        botones_eventos.addStretch()
        capa_eventos.addLayout(botones_eventos)

        caja_especiales = QGroupBox("Horas con duración distinta")
        capa_especiales = QVBoxLayout(caja_especiales)
        capa_especiales.addWidget(
            QLabel(
                "Para las horas que no duran lo mismo que las demás "
                "(p. ej. una última hora de 40 minutos)."
            )
        )
        self.especiales = QTableWidget(0, 2)
        self.especiales.setHorizontalHeaderLabels(["Hora", "Duración"])
        self.especiales.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.especiales.setMinimumHeight(90)
        capa_especiales.addWidget(self.especiales)
        botones_especiales = QHBoxLayout()
        agregar_especial = QPushButton("Agregar hora")
        agregar_especial.clicked.connect(self.agregar_hora_nueva)
        quitar_especial = QPushButton("Quitar hora")
        quitar_especial.clicked.connect(self.quitar_especial)
        botones_especiales.addWidget(agregar_especial)
        botones_especiales.addWidget(quitar_especial)
        botones_especiales.addStretch()
        capa_especiales.addLayout(botones_especiales)
        self.error_especiales = QLabel()
        self.error_especiales.setStyleSheet("color: #C62828;")
        capa_especiales.addWidget(self.error_especiales)

        caja_vista = QGroupBox("Vista previa de las franjas")
        capa_vista = QVBoxLayout(caja_vista)
        self.resumen_franjas = QLabel()
        self.vista_franjas = QListWidget()
        self.vista_franjas.setMinimumHeight(150)
        capa_vista.addWidget(self.resumen_franjas)
        capa_vista.addWidget(self.vista_franjas)

        self.capa_contenido.addWidget(caja_recesos)
        self.capa_contenido.addWidget(caja_eventos)
        self.capa_contenido.addWidget(caja_especiales)
        self.capa_contenido.addWidget(caja_vista)
        self.capa_contenido.addStretch()

        for senal in (
            self.nombre.textChanged,
            self.duracion.valueChanged,
            self.inicio.timeChanged,
            self.fin.timeChanged,
            self.recesos.itemChanged,
            self.eventos.itemChanged,
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

    # --- Eventos ----------------------------------------------------------------------

    def agregar_evento(self, evento: Evento) -> None:
        fila = self.eventos.rowCount()
        self.eventos.blockSignals(True)
        self.eventos.insertRow(fila)
        nombre = QTableWidgetItem(evento.nombre)
        nombre.setData(ROL_ID, evento.id)
        self.eventos.setItem(fila, 0, nombre)
        dia = QComboBox()
        for codigo in DIAS_VALIDOS:
            dia.addItem(NOMBRES_DIAS[codigo], codigo)
        dia.setCurrentIndex(max(dia.findData(evento.dia), 0))
        dia.currentIndexChanged.connect(self.actualizar_vista_previa)
        self.eventos.setCellWidget(fila, 1, dia)
        for columna, minutos in ((2, evento.inicio), (3, evento.fin)):
            editor = editor_hora(minutos)
            editor.timeChanged.connect(self.actualizar_vista_previa)
            self.eventos.setCellWidget(fila, columna, editor)
        self.eventos.blockSignals(False)
        self.actualizar_vista_previa()

    def agregar_evento_nuevo(self) -> None:
        """Propone la primera hora del primer día lectivo."""
        inicio = leer_hora(self.inicio)
        dia = next((d for d, c in self.dias.items() if c.isChecked()), "L")
        self.agregar_evento(Evento(dia=dia, inicio=inicio, fin=inicio + self.duracion.value()))

    def quitar_evento(self) -> None:
        fila = self.eventos.currentRow()
        if fila < 0:
            fila = self.eventos.rowCount() - 1
        if fila >= 0:
            self.eventos.removeRow(fila)
            self.actualizar_vista_previa()

    def _leer_eventos(self) -> list[Evento]:
        eventos = []
        for fila in range(self.eventos.rowCount()):
            item = self.eventos.item(fila, 0)
            dia = self.eventos.cellWidget(fila, 1)
            inicio = self.eventos.cellWidget(fila, 2)
            fin = self.eventos.cellWidget(fila, 3)
            assert isinstance(dia, QComboBox)
            assert isinstance(inicio, QTimeEdit) and isinstance(fin, QTimeEdit)
            eventos.append(
                Evento(
                    id=item.data(ROL_ID) if item else None,
                    nombre=(item.text() if item else "") or "Hora cívica",
                    dia=dia.currentData(),
                    inicio=leer_hora(inicio),
                    fin=leer_hora(fin),
                )
            )
        return eventos

    # --- Horas con duración distinta ---------------------------------------------------

    def agregar_especial(self, numero: int, minutos: int) -> None:
        """Agrega una fila «hora ``numero`` (1 = primera) dura ``minutos``»."""
        fila = self.especiales.rowCount()
        self.especiales.insertRow(fila)
        for columna, (valor, minimo, maximo, sufijo) in enumerate(
            ((numero, 1, 30, ""), (minutos, 5, 240, " min"))
        ):
            editor = QSpinBox()
            editor.setRange(minimo, maximo)
            editor.setSuffix(sufijo)
            editor.setValue(valor)
            editor.valueChanged.connect(self.actualizar_vista_previa)
            self.especiales.setCellWidget(fila, columna, editor)
        self.actualizar_vista_previa()

    def agregar_hora_nueva(self) -> None:
        """Propone la última hora del día con la duración general.

        Si sobra tiempo al final de la jornada, propone la hora que ya no cabe (la que se
        querrá acortar); si no sobra, la última hora que ya existe.
        """
        usadas = set(self._leer_especiales())
        try:
            nivel = self._leer_nivel().model_copy(update={"id": self.actual_id or 0})
            del_dia = [f for f in generar_franjas_nivel(nivel) if f.dia == nivel.dias[0]]
            numero = len(del_dia)
            if not del_dia or del_dia[-1].fin < nivel.fin_jornada:
                numero += 1
        except (ValidationError, IndexError):
            numero = 1
        while numero - 1 in usadas and numero < 30:
            numero += 1
        self.agregar_especial(numero, self.duracion.value())

    def quitar_especial(self) -> None:
        fila = self.especiales.currentRow()
        if fila < 0:
            fila = self.especiales.rowCount() - 1
        if fila >= 0:
            self.especiales.removeRow(fila)
            self.actualizar_vista_previa()

    def _leer_especiales(self) -> dict[int, int]:
        """Índice de franja (0 = primera hora) → minutos. Una hora repetida gana la última."""
        duraciones: dict[int, int] = {}
        for fila in range(self.especiales.rowCount()):
            hora = self.especiales.cellWidget(fila, 0)
            minutos = self.especiales.cellWidget(fila, 1)
            assert isinstance(hora, QSpinBox) and isinstance(minutos, QSpinBox)
            duraciones[hora.value() - 1] = minutos.value()
        return duraciones

    def _horas_repetidas(self) -> bool:
        numeros = []
        for fila in range(self.especiales.rowCount()):
            hora = self.especiales.cellWidget(fila, 0)
            assert isinstance(hora, QSpinBox)
            numeros.append(hora.value())
        return len(numeros) != len(set(numeros))

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
            eventos=self._leer_eventos(),
            sin_huecos_alumnos=self.sin_huecos.isChecked(),
            duraciones_especiales=self._leer_especiales(),
        )

    def actualizar_vista_previa(self) -> None:
        self.vista_franjas.clear()
        self.error_recesos.clear()
        self.error_especiales.setText(
            "Hay una hora repetida; cada hora debe aparecer una sola vez."
            if self._horas_repetidas()
            else ""
        )
        try:
            nivel = self._leer_nivel().model_copy(update={"id": self.actual_id or 0})
        except ValidationError as error:
            self.resumen_franjas.setText("Corrija los datos para ver las franjas.")
            if any(e["loc"] and e["loc"][0] == "recesos" for e in error.errors()):
                self.error_recesos.setText("Algún receso tiene la hora de inicio ≥ la de fin.")
            if any(e["loc"] and e["loc"][0] == "eventos" for e in error.errors()):
                self.error_recesos.setText("Algún evento tiene la hora de inicio ≥ la de fin.")
            return
        franjas = generar_franjas_nivel(nivel)
        primer_dia = [f for f in franjas if f.dia == nivel.dias[0]]
        self.resumen_franjas.setText(
            f"{len(primer_dia)} franjas por día · {len(franjas)} por semana"
        )
        sobrantes = [i + 1 for i in nivel.duraciones_especiales if i >= len(primer_dia)]
        if sobrantes and not self.error_especiales.text():
            self.error_especiales.setText(
                f"La jornada solo tiene {len(primer_dia)} horas; no existe la hora "
                + ", ".join(str(n) for n in sobrantes)
                + "."
            )
        recesos = sorted(nivel.recesos, key=lambda r: r.inicio)
        for f in primer_dia:
            for receso in [r for r in recesos if r.fin <= f.inicio]:
                self.vista_franjas.addItem(
                    f"   {receso.nombre}: {a_hhmm(receso.inicio)}–{a_hhmm(receso.fin)}"
                )
                recesos.remove(receso)
            texto = f"{f.indice + 1}. {a_hhmm(f.inicio)}–{a_hhmm(f.fin)}"
            if f.indice in nivel.duraciones_especiales:
                texto += f"   ({f.duracion} min)"
            self.vista_franjas.addItem(texto)
        for evento in nivel.eventos:
            horas = [f.indice + 1 for f in franjas if evento_de_franja(f, nivel) is evento]
            cuales = (
                "hora " + ", ".join(str(h) for h in horas)
                if horas
                else "no coincide con ninguna franja"
            )
            self.vista_franjas.addItem(
                f"   {evento.nombre}: {NOMBRES_DIAS[evento.dia]} {a_hhmm(evento.inicio)}–"
                f"{a_hhmm(evento.fin)} ({cuales}, sin clase)"
            )

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
        self.eventos.setRowCount(0)
        for evento in nivel.eventos:
            self.agregar_evento(evento)
        self.especiales.setRowCount(0)
        for indice, minutos in nivel.duraciones_especiales.items():
            self.agregar_especial(indice + 1, minutos)
        self.actualizar_vista_previa()

    def guardar(self) -> bool:
        if self._horas_repetidas():
            self.errores.limpiar()
            self.errores.mostrar(None, "Hay una hora con duración distinta repetida.")
            return False
        return super().guardar()

    def guardar_elemento(self) -> int:
        assert self.repo is not None
        nivel = self.repo.guardar_nivel(self._leer_nivel())
        assert nivel.id is not None
        return nivel.id

    def eliminar_elemento(self, elemento_id: int) -> None:
        assert self.repo is not None
        self.repo.eliminar_nivel(elemento_id)
