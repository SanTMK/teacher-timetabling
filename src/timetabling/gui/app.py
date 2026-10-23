"""Creado con Claude. Ventana principal: barra lateral de pantallas y manejo de proyectos."""

from __future__ import annotations

import sys
from importlib import resources
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from timetabling.gui.pantallas.asignaturas import PantallaAsignaturas
from timetabling.gui.pantallas.base import Pantalla
from timetabling.gui.pantallas.configuracion import PantallaConfiguracion
from timetabling.gui.pantallas.espacios import PantallaEspacios
from timetabling.gui.pantallas.generar import PantallaGenerar
from timetabling.gui.pantallas.grados_grupos import PantallaGradosGrupos
from timetabling.gui.pantallas.niveles import PantallaNiveles
from timetabling.gui.pantallas.plan import PantallaPlan
from timetabling.gui.pantallas.profesores import PantallaProfesores
from timetabling.gui.pantallas.resultados import PantallaResultados
from timetabling.gui.pantallas.validacion import PantallaValidacion
from timetabling.persistencia.repositorio import EXTENSION, Repositorio

FILTRO = f"Proyecto de horario (*{EXTENSION})"
MAX_RECIENTES = 8

# Entidad de un problema de validación → pantalla a la que lleva.
_PANTALLA_DE_ENTIDAD = {
    "configuracion": "configuracion",
    "niveles": "niveles",
    "grados": "grados",
    "grupos": "grados",
    "asignaturas": "asignaturas",
    "plan": "plan",
    "profesores": "profesores",
    "espacios": "espacios",
    "asignaciones_fijas": "grados",
}


class VentanaPrincipal(QMainWindow):
    def __init__(self, ajustes: QSettings | None = None) -> None:
        super().__init__()
        self.ajustes = ajustes or QSettings("Timetabling", "Timetabling")
        self.repo: Repositorio | None = None
        self.resize(1200, 780)

        self.pantallas: dict[str, Pantalla] = {
            "configuracion": PantallaConfiguracion(),
            "niveles": PantallaNiveles(),
            "grados": PantallaGradosGrupos(),
            "asignaturas": PantallaAsignaturas(),
            "plan": PantallaPlan(),
            "profesores": PantallaProfesores(),
            "espacios": PantallaEspacios(),
            "validacion": PantallaValidacion(),
            "generar": PantallaGenerar(),
            "resultados": PantallaResultados(),
        }
        self.barra = QListWidget()
        self.barra.setObjectName("barraLateral")
        self.barra.setFixedWidth(190)
        self.barra.setStyleSheet("QListWidget#barraLateral::item { padding: 7px 10px; }")
        self.pila = QStackedWidget()
        for clave, pantalla in self.pantallas.items():
            elemento = QListWidgetItem(pantalla.titulo)
            elemento.setData(Qt.ItemDataRole.UserRole, clave)
            self.barra.addItem(elemento)
            self.pila.addWidget(pantalla)
        self.barra.currentRowChanged.connect(self._cambiar_pantalla)
        validacion = self.pantallas["validacion"]
        assert isinstance(validacion, PantallaValidacion)
        validacion.navegar.connect(self.navegar)
        generar = self.pantallas["generar"]
        assert isinstance(generar, PantallaGenerar)
        self.generar = generar
        generar.resolviendo.connect(self._bloquear_edicion)
        generar.solucion_guardada.connect(self.ver_solucion)
        generar.ver_validacion.connect(lambda: self.mostrar("validacion"))

        self.bienvenida = QLabel(
            "Cree un proyecto nuevo o abra uno existente desde el menú Archivo."
        )
        self.bienvenida.setAlignment(Qt.AlignmentFlag.AlignCenter)

        central = QWidget()
        capa = QHBoxLayout(central)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.addWidget(self.barra)
        derecha = QVBoxLayout()
        derecha.addWidget(self.bienvenida)
        derecha.addWidget(self.pila)
        capa.addLayout(derecha, 1)
        self.setCentralWidget(central)
        self._crear_menu()
        self._actualizar_estado()

    # --- Menú -----------------------------------------------------------------------

    def _crear_menu(self) -> None:
        menu = self.menuBar().addMenu("&Archivo")
        self.accion_nuevo = QAction("&Nuevo proyecto…", self)
        self.accion_nuevo.setShortcut(QKeySequence.StandardKey.New)
        self.accion_nuevo.triggered.connect(self._dialogo_nuevo)
        self.accion_abrir = QAction("&Abrir…", self)
        self.accion_abrir.setShortcut(QKeySequence.StandardKey.Open)
        self.accion_abrir.triggered.connect(self._dialogo_abrir)
        self.accion_guardar_como = QAction("&Guardar como…", self)
        self.accion_guardar_como.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.accion_guardar_como.triggered.connect(self._dialogo_guardar_como)
        self.menu_recientes = menu.addMenu("Proyectos &recientes")
        menu.insertAction(self.menu_recientes.menuAction(), self.accion_nuevo)
        menu.insertAction(self.menu_recientes.menuAction(), self.accion_abrir)
        menu.addAction(self.accion_guardar_como)
        menu.addSeparator()
        salir = QAction("&Salir", self)
        salir.setShortcut(QKeySequence.StandardKey.Quit)
        salir.triggered.connect(self.close)
        menu.addAction(salir)
        self._actualizar_recientes()

    def recientes(self) -> list[str]:
        valor = self.ajustes.value("recientes", [])
        if isinstance(valor, str):
            valor = [valor]
        return [r for r in (valor or []) if Path(r).exists()]

    def _recordar(self, ruta: Path) -> None:
        recientes = [str(ruta)] + [r for r in self.recientes() if r != str(ruta)]
        self.ajustes.setValue("recientes", recientes[:MAX_RECIENTES])
        self._actualizar_recientes()

    def _actualizar_recientes(self) -> None:
        self.menu_recientes.clear()
        recientes = self.recientes()
        for ruta in recientes:
            accion = self.menu_recientes.addAction(ruta)
            accion.triggered.connect(lambda _=False, r=ruta: self.abrir_proyecto(Path(r)))
        self.menu_recientes.setEnabled(bool(recientes))

    def _dialogo_nuevo(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Nuevo proyecto", "escuela" + EXTENSION, FILTRO)
        if ruta:
            self.nuevo_proyecto(Path(ruta))

    def _dialogo_abrir(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", "", FILTRO)
        if ruta:
            self.abrir_proyecto(Path(ruta))

    def _dialogo_guardar_como(self) -> None:
        if self.repo is None:
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar como", "", FILTRO)
        if ruta:
            self.guardar_como(Path(ruta))

    # --- Proyectos ------------------------------------------------------------------

    @staticmethod
    def _con_extension(ruta: Path) -> Path:
        return ruta if ruta.suffix == EXTENSION else ruta.with_suffix(EXTENSION)

    def nuevo_proyecto(self, ruta: Path) -> None:
        ruta = self._con_extension(ruta)
        try:
            repo = Repositorio.crear(ruta, sobrescribir=True)
        except Exception as error:  # noqa: BLE001 - se informa al usuario
            QMessageBox.critical(self, "Error", f"No se pudo crear el proyecto:\n{error}")
            return
        self._usar(repo)

    def abrir_proyecto(self, ruta: Path) -> None:
        try:
            repo = Repositorio.abrir(ruta)
        except Exception as error:  # noqa: BLE001 - se informa al usuario
            QMessageBox.critical(self, "Error", f"No se pudo abrir el proyecto:\n{error}")
            return
        self._usar(repo)

    def guardar_como(self, ruta: Path) -> None:
        """Copia el proyecto y continúa trabajando sobre la copia."""
        assert self.repo is not None
        ruta = self._con_extension(ruta)
        if ruta.resolve() == self.repo.ruta.resolve():
            return
        self.repo.guardar_como(ruta)
        self.abrir_proyecto(ruta)

    def _usar(self, repo: Repositorio) -> None:
        if self.repo is not None:
            self.repo.cerrar()
        self.repo = repo
        self._recordar(repo.ruta)
        for pantalla in self.pantallas.values():
            pantalla.establecer_repositorio(repo)
        if self.barra.currentRow() < 0:
            self.barra.setCurrentRow(0)
        self._actualizar_estado()

    def _actualizar_estado(self) -> None:
        abierto = self.repo is not None
        self.barra.setEnabled(abierto)
        self.pila.setVisible(abierto)
        self.bienvenida.setVisible(not abierto)
        self.accion_guardar_como.setEnabled(abierto)
        if self.repo is not None:
            nombre = self.repo.obtener_configuracion().nombre_escuela
            self.setWindowTitle(f"Timetabling — {nombre} ({self.repo.ruta.name})")
            self.statusBar().showMessage(str(self.repo.ruta))
        else:
            self.setWindowTitle("Timetabling")

    # --- Navegación -----------------------------------------------------------------

    def _cambiar_pantalla(self, fila: int) -> None:
        if fila < 0:
            return
        self.pila.setCurrentIndex(fila)
        pantalla = self.pila.currentWidget()
        if isinstance(pantalla, Pantalla) and self.repo is not None and pantalla.isEnabled():
            pantalla.refrescar()
            self._actualizar_estado()

    def mostrar(self, clave: str) -> Pantalla:
        self.barra.setCurrentRow(list(self.pantallas).index(clave))
        return self.pantallas[clave]

    def navegar(self, entidad: str, elemento_id: int | None) -> None:
        clave = _PANTALLA_DE_ENTIDAD.get(entidad)
        if clave is None:
            return
        self.mostrar(clave).seleccionar(entidad, elemento_id)

    def ver_solucion(self, solucion_id: int) -> None:
        resultados = self.mostrar("resultados")
        assert isinstance(resultados, PantallaResultados)
        resultados.seleccionar_solucion(solucion_id)

    def _bloquear_edicion(self, resolviendo: bool) -> None:
        """Mientras el solver trabaja no se pueden editar datos ni cambiar de proyecto."""
        for clave, pantalla in self.pantallas.items():
            if clave != "generar":
                pantalla.setEnabled(not resolviendo and self.repo is not None)
        for accion in (self.accion_nuevo, self.accion_abrir, self.accion_guardar_como):
            accion.setEnabled(not resolviendo)
        self.menu_recientes.setEnabled(not resolviendo and bool(self.recientes()))
        if resolviendo:
            self.statusBar().showMessage("Generando horario… la edición está bloqueada.")
        else:
            self._actualizar_estado()

    def closeEvent(self, evento) -> None:  # noqa: N802 - nombre de Qt
        if self.generar.trabajador is not None:
            self.generar.trabajador.cancelar()
            self.generar.trabajador.wait()
        if self.repo is not None:
            self.repo.cerrar()
            self.repo = None
        super().closeEvent(evento)


def icono_aplicacion() -> QIcon:
    ruta = resources.files("timetabling.recursos").joinpath("icono.png")
    with resources.as_file(ruta) as archivo:
        return QIcon(str(archivo))


def ejecutar(argumentos: list[str] | None = None) -> int:
    """Abre la interfaz gráfica. Devuelve el código de salida."""
    app = QApplication.instance() or QApplication(argumentos or sys.argv)
    app.setApplicationName("Timetabling")
    app.setWindowIcon(icono_aplicacion())
    ventana = VentanaPrincipal()
    ventana.show()
    recientes = ventana.recientes()
    if recientes:
        ventana.abrir_proyecto(Path(recientes[0]))
    return app.exec()
