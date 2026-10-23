"""Creado con Claude. Pantalla de profesores: datos generales, habilitaciones y disponibilidad."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from timetabling.dominio.modelos import (
    DIAS_VALIDOS,
    DatosEscuela,
    Profesor,
    TipoDisponibilidad,
)
from timetabling.gui.pantallas.base import PantallaListaFormulario
from timetabling.gui.widgets.disponibilidad import COLORES, EditorDisponibilidad
from timetabling.nucleo.franjas import generar_franjas_nivel

ROL_ID = Qt.ItemDataRole.UserRole


def _lista_casillas() -> QListWidget:
    lista = QListWidget()
    lista.setMaximumHeight(140)
    return lista


def _marcados(lista: QListWidget) -> set[int]:
    return {
        lista.item(i).data(ROL_ID)
        for i in range(lista.count())
        if lista.item(i).checkState() == Qt.CheckState.Checked
    }


class PantallaProfesores(PantallaListaFormulario):
    titulo = "Profesores"
    tabla = "profesores"
    texto_nuevo = "Nuevo profesor"

    def __init__(self) -> None:
        super().__init__()
        self._datos: DatosEscuela | None = None
        self.nombre = QLineEdit()
        self.carga_semanal = QSpinBox()
        self.carga_semanal.setRange(0, 7 * 24 * 60)
        self.carga_semanal.setSingleStep(50)
        self.carga_semanal.setSuffix(" min/semana")
        self.carga_diaria = QSpinBox()
        self.carga_diaria.setRange(0, 24 * 60)
        self.carga_diaria.setSingleStep(50)
        self.carga_diaria.setSuffix(" min/día")
        self.max_consecutivas = QSpinBox()
        self.max_consecutivas.setRange(1, 20)
        self.asignaturas = _lista_casillas()
        self.grados = _lista_casillas()
        self.grados.itemChanged.connect(self._actualizar_referencia)

        self.errores.fila(self.formulario, "nombre", "Nombre", self.nombre)
        self.errores.fila(
            self.formulario, "carga_max_semanal_min", "Carga máxima semanal", self.carga_semanal
        )
        self.errores.fila(
            self.formulario, "carga_max_diaria_min", "Carga máxima diaria", self.carga_diaria
        )
        self.errores.fila(
            self.formulario, "max_consecutivas", "Máx. clases consecutivas", self.max_consecutivas
        )
        self.errores.fila(self.formulario, "asignaturas", "Asignaturas", self.asignaturas)
        self.errores.fila(self.formulario, "grados", "Grados", self.grados)

        self.editor = EditorDisponibilidad()
        caja = QGroupBox("Disponibilidad")
        capa = QVBoxLayout(caja)
        herramientas = QHBoxLayout()
        self.modos = QButtonGroup(self)
        for texto, modo in (
            ("Disponible", TipoDisponibilidad.DISPONIBLE),
            ("Preferible no", TipoDisponibilidad.PREFERIBLE_NO),
            ("Borrar", None),
        ):
            boton = QRadioButton(texto)
            if modo is not None:
                boton.setStyleSheet(
                    f"QRadioButton {{ background: {COLORES[modo].name()}; color: black;"
                    " padding: 2px 6px; border-radius: 3px; }"
                )
            boton.toggled.connect(lambda activo, m=modo: activo and self._poner_modo(m))
            self.modos.addButton(boton)
            herramientas.addWidget(boton)
            if modo == TipoDisponibilidad.DISPONIBLE:
                boton.setChecked(True)
        herramientas.addStretch()
        copiar = QPushButton("Copiar día a toda la semana")
        copiar.setToolTip("Copia el día seleccionado (en negrita) a los demás días")
        copiar.clicked.connect(lambda: self.editor.copiar_dia_a_semana())
        limpiar = QPushButton("Limpiar")
        limpiar.clicked.connect(lambda: self.editor.limpiar())
        herramientas.addWidget(copiar)
        herramientas.addWidget(limpiar)
        capa.addLayout(herramientas)
        capa.addWidget(self.editor)
        self.leyenda_niveles = QLabel()
        capa.addWidget(self.leyenda_niveles)
        ayuda = QLabel(
            "Arrastre para marcar un rango de días y horas. Las bandas de color a la izquierda "
            "de cada día son las franjas de los niveles que atiende el profesor."
        )
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet("color: palette(placeholder-text);")
        capa.addWidget(ayuda)
        self.capa_contenido.addWidget(caja)
        self.capa_contenido.addStretch()

    def _poner_modo(self, modo: TipoDisponibilidad | None) -> None:
        self.editor.modo = modo

    def refrescar(self) -> None:
        assert self.repo is not None
        self._datos = self.repo.cargar_datos()
        super().refrescar()

    def elementos(self) -> list[tuple[int, str]]:
        assert self._datos is not None
        return [(p.id, p.nombre) for p in self._datos.profesores if p.id is not None]

    def _configurar_editor(self, profesor: Profesor) -> None:
        assert self._datos is not None
        niveles = self._datos.niveles
        dias = [d for d in DIAS_VALIDOS if any(d in n.dias for n in niveles)] or None
        inicios = [n.inicio_jornada for n in niveles] + [d.inicio for d in profesor.disponibilidad]
        fines = [n.fin_jornada for n in niveles] + [d.fin for d in profesor.disponibilidad]
        self.editor.configurar(
            dias or [], min(inicios, default=7 * 60), max(fines, default=15 * 60)
        )
        self.editor.poner_disponibilidad(profesor.disponibilidad)

    def _actualizar_referencia(self) -> None:
        if self._datos is None:
            return
        grados = _marcados(self.grados)
        niveles_ids = {g.nivel_id for g in self._datos.grados if g.id in grados}
        niveles = [n for n in self._datos.niveles if n.id in niveles_ids]
        self.editor.poner_referencia([generar_franjas_nivel(n) for n in niveles])
        self.leyenda_niveles.setText(
            "Franjas de referencia: "
            + " ".join(
                f'<span style="color:{self.editor.color_nivel(i).name()}">■</span> {n.nombre}'
                for i, n in enumerate(niveles)
            )
            if niveles
            else "Marque grados para ver las franjas de referencia."
        )

    def cargar_elemento(self, elemento_id: int | None) -> None:
        assert self.repo is not None
        self._datos = self.repo.cargar_datos()
        datos = self._datos
        profesor = next((p for p in datos.profesores if p.id == elemento_id), None) or Profesor(
            nombre="(nuevo)"
        )
        self.nombre.setText(profesor.nombre if elemento_id is not None else "")
        self.carga_semanal.setValue(profesor.carga_max_semanal_min)
        self.carga_diaria.setValue(profesor.carga_max_diaria_min)
        self.max_consecutivas.setValue(profesor.max_consecutivas)
        self.asignaturas.clear()
        for asignatura in datos.asignaturas:
            self._agregar_casilla(
                self.asignaturas,
                asignatura.nombre,
                asignatura.id,
                asignatura.id in profesor.asignaturas,
            )
        self.grados.blockSignals(True)
        self.grados.clear()
        for grado in datos.grados:
            self._agregar_casilla(
                self.grados,
                f"{datos.nivel(grado.nivel_id).nombre} · {grado.nombre}",
                grado.id,
                grado.id in profesor.grados,
            )
        self.grados.blockSignals(False)
        self._configurar_editor(profesor)
        self._actualizar_referencia()

    @staticmethod
    def _agregar_casilla(lista: QListWidget, texto: str, valor: int | None, marcado: bool) -> None:
        item = QListWidgetItem(texto)
        item.setData(ROL_ID, valor)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if marcado else Qt.CheckState.Unchecked)
        lista.addItem(item)

    def marcar(self, lista: QListWidget, valores: set[int]) -> None:
        """Marca exactamente las casillas con esos ids (usado en pruebas)."""
        for i in range(lista.count()):
            item = lista.item(i)
            estado = (
                Qt.CheckState.Checked if item.data(ROL_ID) in valores else Qt.CheckState.Unchecked
            )
            item.setCheckState(estado)

    def guardar_elemento(self) -> int:
        assert self.repo is not None
        profesor = self.repo.guardar_profesor(
            Profesor(
                id=self.actual_id,
                nombre=self.nombre.text(),
                asignaturas=_marcados(self.asignaturas),
                grados=_marcados(self.grados),
                disponibilidad=self.editor.disponibilidad(),
                carga_max_semanal_min=self.carga_semanal.value(),
                carga_max_diaria_min=self.carga_diaria.value(),
                max_consecutivas=self.max_consecutivas.value(),
            )
        )
        assert profesor.id is not None
        self._datos = self.repo.cargar_datos()
        return profesor.id

    def eliminar_elemento(self, elemento_id: int) -> None:
        assert self.repo is not None
        self.repo.eliminar_profesor(elemento_id)
        self._datos = self.repo.cargar_datos()
