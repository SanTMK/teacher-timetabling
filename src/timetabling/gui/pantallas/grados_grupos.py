"""Creado con Claude. Pantalla de grados y grupos: árbol nivel → grado → grupos."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from timetabling.dominio.modelos import Grado, Grupo
from timetabling.gui.pantallas.base import ErroresFormulario, Pantalla

NIVEL, GRADO, GRUPO = "niveles", "grados", "grupos"


class PantallaGradosGrupos(Pantalla):
    titulo = "Grados y grupos"

    def __init__(self) -> None:
        super().__init__()
        # Elemento en edición: (tipo, id o None si es nuevo, id del padre)
        self.edicion: tuple[str, int | None, int | None] | None = None

        self.arbol = QTreeWidget()
        self.arbol.setHeaderLabels(["Nivel / grado / grupo", "Alumnos"])
        self.arbol.setColumnWidth(0, 220)
        self.arbol.currentItemChanged.connect(self._al_seleccionar)
        self.boton_grado = QPushButton("Agregar grado")
        self.boton_grado.clicked.connect(self.agregar_grado)
        self.boton_grupo = QPushButton("Agregar grupo")
        self.boton_grupo.clicked.connect(self.agregar_grupo)
        self.boton_eliminar = QPushButton("Eliminar")
        self.boton_eliminar.clicked.connect(self.eliminar)

        # Formulario de grado
        self.errores_grado = ErroresFormulario()
        self.nombre_grado = QLineEdit()
        self.nivel_grado = QLabel()
        pagina_grado = QWidget()
        formulario_grado = QFormLayout(pagina_grado)
        formulario_grado.addRow("Nivel", self.nivel_grado)
        self.errores_grado.fila(formulario_grado, "nombre", "Nombre del grado", self.nombre_grado)
        formulario_grado.addRow(self.errores_grado.general)

        # Formulario de grupo
        self.errores_grupo = ErroresFormulario()
        self.grado_grupo = QLabel()
        self.seccion = QLineEdit()
        self.estudiantes = QSpinBox()
        self.estudiantes.setRange(0, 200)
        self.titular = QComboBox()
        pagina_grupo = QWidget()
        formulario_grupo = QFormLayout(pagina_grupo)
        formulario_grupo.addRow("Grado", self.grado_grupo)
        self.errores_grupo.fila(formulario_grupo, "seccion", "Sección", self.seccion)
        self.errores_grupo.fila(formulario_grupo, "estudiantes", "Estudiantes", self.estudiantes)
        self.errores_grupo.fila(formulario_grupo, "titular_id", "Titular (opcional)", self.titular)
        formulario_grupo.addRow(self.errores_grupo.general)

        self.vacio = QLabel("Seleccione un grado o grupo, o agregue uno nuevo.")
        self.formularios = QStackedWidget()
        self.formularios.addWidget(self.vacio)
        self.formularios.addWidget(pagina_grado)
        self.formularios.addWidget(pagina_grupo)

        self.boton_guardar = QPushButton("Guardar")
        self.boton_guardar.setDefault(True)
        self.boton_guardar.clicked.connect(self.guardar)
        self.estado = QLabel()

        izquierda = QWidget()
        capa_izq = QVBoxLayout(izquierda)
        capa_izq.setContentsMargins(0, 0, 0, 0)
        capa_izq.addWidget(self.arbol)
        botones = QHBoxLayout()
        for boton in (self.boton_grado, self.boton_grupo, self.boton_eliminar):
            botones.addWidget(boton)
        capa_izq.addLayout(botones)
        derecha = QWidget()
        capa_der = QVBoxLayout(derecha)
        capa_der.addWidget(self.formularios)
        capa_der.addStretch()
        pie = QHBoxLayout()
        pie.addWidget(self.estado, 1)
        pie.addWidget(self.boton_guardar)
        capa_der.addLayout(pie)
        divisor = QSplitter()
        divisor.addWidget(izquierda)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(1, 2)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        capa.addWidget(divisor, 1)

    # --- Árbol ----------------------------------------------------------------------

    def refrescar(self) -> None:
        seleccion = (self.edicion[0], self.edicion[1]) if self.edicion else None
        self._llenar_arbol(seleccion)

    def _llenar_arbol(self, seleccion: tuple[str, int | None] | None) -> None:
        assert self.repo is not None
        datos = self.repo.cargar_datos()
        self.arbol.blockSignals(True)
        self.arbol.clear()
        elegido: QTreeWidgetItem | None = None
        for nivel in datos.niveles:
            item_nivel = QTreeWidgetItem([nivel.nombre])
            item_nivel.setData(0, Qt.ItemDataRole.UserRole, (NIVEL, nivel.id))
            self.arbol.addTopLevelItem(item_nivel)
            for grado in [g for g in datos.grados if g.nivel_id == nivel.id]:
                item_grado = QTreeWidgetItem([grado.nombre])
                item_grado.setData(0, Qt.ItemDataRole.UserRole, (GRADO, grado.id))
                item_nivel.addChild(item_grado)
                if seleccion == (GRADO, grado.id):
                    elegido = item_grado
                for grupo in [g for g in datos.grupos if g.grado_id == grado.id]:
                    item_grupo = QTreeWidgetItem(
                        [datos.nombre_grupo(grupo), str(grupo.estudiantes)]
                    )
                    item_grupo.setData(0, Qt.ItemDataRole.UserRole, (GRUPO, grupo.id))
                    item_grado.addChild(item_grupo)
                    if seleccion == (GRUPO, grupo.id):
                        elegido = item_grupo
        self.arbol.expandAll()
        self.arbol.blockSignals(False)
        if elegido is not None:
            self.arbol.setCurrentItem(elegido)
        else:
            self.edicion = None
            self.formularios.setCurrentWidget(self.vacio)
        self._actualizar_botones()

    def _dato(self, item: QTreeWidgetItem | None) -> tuple[str, int] | None:
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None

    def _al_seleccionar(self, actual: QTreeWidgetItem | None, _anterior: object) -> None:
        dato = self._dato(actual)
        self.estado.clear()
        if dato is None or dato[0] == NIVEL:
            self.edicion = None
            self.formularios.setCurrentWidget(self.vacio)
        elif dato[0] == GRADO:
            self._editar_grado(dato[1], None)
        else:
            self._editar_grupo(dato[1], None)
        self._actualizar_botones()

    def _actualizar_botones(self) -> None:
        dato = self._dato(self.arbol.currentItem())
        self.boton_grado.setEnabled(dato is not None)
        self.boton_grupo.setEnabled(dato is not None and dato[0] != NIVEL)
        self.boton_eliminar.setEnabled(dato is not None and dato[0] != NIVEL)
        self.boton_guardar.setEnabled(self.edicion is not None)

    def _nivel_seleccionado(self) -> int | None:
        item = self.arbol.currentItem()
        while item is not None and self._dato(item)[0] != NIVEL:  # type: ignore[index]
            item = item.parent()
        dato = self._dato(item)
        return dato[1] if dato else None

    def _grado_seleccionado(self) -> int | None:
        item = self.arbol.currentItem()
        dato = self._dato(item)
        if dato and dato[0] == GRUPO and item is not None:
            dato = self._dato(item.parent())
        return dato[1] if dato and dato[0] == GRADO else None

    # --- Edición --------------------------------------------------------------------

    def _editar_grado(self, grado_id: int | None, nivel_id: int | None) -> None:
        assert self.repo is not None
        datos = self.repo.cargar_datos()
        grado = next((g for g in datos.grados if g.id == grado_id), None)
        nivel_id = grado.nivel_id if grado else nivel_id
        assert nivel_id is not None
        self.edicion = (GRADO, grado_id, nivel_id)
        self.nivel_grado.setText(datos.nivel(nivel_id).nombre)
        self.nombre_grado.setText(grado.nombre if grado else "")
        self.errores_grado.limpiar()
        self.formularios.setCurrentIndex(1)

    def _editar_grupo(self, grupo_id: int | None, grado_id: int | None) -> None:
        assert self.repo is not None
        datos = self.repo.cargar_datos()
        grupo = next((g for g in datos.grupos if g.id == grupo_id), None)
        grado_id = grupo.grado_id if grupo else grado_id
        assert grado_id is not None
        self.edicion = (GRUPO, grupo_id, grado_id)
        grado = datos.grado(grado_id)
        self.grado_grupo.setText(f"{grado.nombre} ({datos.nivel(grado.nivel_id).nombre})")
        self.seccion.setText(grupo.seccion if grupo else "")
        self.estudiantes.setValue(grupo.estudiantes if grupo else 0)
        self.titular.clear()
        self.titular.addItem("(sin titular)", None)
        for profesor in datos.profesores:
            self.titular.addItem(profesor.nombre, profesor.id)
        indice = self.titular.findData(grupo.titular_id) if grupo and grupo.titular_id else 0
        self.titular.setCurrentIndex(max(indice, 0))
        self.errores_grupo.limpiar()
        self.formularios.setCurrentIndex(2)

    def agregar_grado(self) -> None:
        nivel_id = self._nivel_seleccionado()
        if nivel_id is None:
            self.avisar_error("Seleccione primero un nivel.")
            return
        self._editar_grado(None, nivel_id)
        self.estado.setText("Grado nuevo")
        self._actualizar_botones()
        self.nombre_grado.setFocus()

    def agregar_grupo(self) -> None:
        grado_id = self._grado_seleccionado()
        if grado_id is None:
            self.avisar_error("Seleccione primero un grado.")
            return
        self._editar_grupo(None, grado_id)
        self.estado.setText("Grupo nuevo")
        self._actualizar_botones()
        self.seccion.setFocus()

    def guardar(self) -> bool:
        if self.edicion is None or self.repo is None:
            return False
        repo = self.repo
        tipo, elemento_id, padre_id = self.edicion
        assert padre_id is not None
        guardado: list[int] = []
        if tipo == GRADO:
            ok = self.guardar_con(
                self.errores_grado,
                lambda: guardado.append(
                    repo.guardar_grado(
                        Grado(id=elemento_id, nivel_id=padre_id, nombre=self.nombre_grado.text())
                    ).id  # type: ignore[arg-type]
                ),
            )
        else:
            ok = self.guardar_con(
                self.errores_grupo,
                lambda: guardado.append(
                    repo.guardar_grupo(
                        Grupo(
                            id=elemento_id,
                            grado_id=padre_id,
                            seccion=self.seccion.text(),
                            estudiantes=self.estudiantes.value(),
                            titular_id=self.titular.currentData(),
                        )
                    ).id  # type: ignore[arg-type]
                ),
                "seccion",
            )
        if ok:
            self._llenar_arbol((tipo, guardado[0]))
            self.estado.setText("Cambios guardados.")
        return ok

    def eliminar(self) -> bool:
        dato = self._dato(self.arbol.currentItem())
        if dato is None or dato[0] == NIVEL or self.repo is None:
            return False
        tipo, elemento_id = dato
        nombre = self.arbol.currentItem().text(0)
        if not self.confirmar_borrado(tipo, elemento_id, nombre):
            return False
        if tipo == GRADO:
            self.repo.eliminar_grado(elemento_id)
        else:
            self.repo.eliminar_grupo(elemento_id)
        self.edicion = None
        self.datos_cambiados.emit()
        self._llenar_arbol(None)
        return True

    def seleccionar(self, entidad: str, elemento_id: int | None) -> None:
        if entidad in (GRADO, GRUPO) and elemento_id is not None:
            self._llenar_arbol((entidad, elemento_id))
