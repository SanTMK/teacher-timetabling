"""Creado con Claude. Pantalla de configuración general y pesos de las restricciones blandas."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from timetabling.dominio.modelos import NOMBRES_PENALIZACIONES, Configuracion, Pesos
from timetabling.gui.pantallas.base import ErroresFormulario, Pantalla


def _spin(minimo: int, maximo: int, sufijo: str = "") -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimo, maximo)
    spin.setSuffix(sufijo)
    return spin


class PantallaConfiguracion(Pantalla):
    titulo = "Configuración"

    def __init__(self) -> None:
        super().__init__()
        self.errores = ErroresFormulario()
        self.nombre = QLineEdit()
        self.margen = _spin(0, 120, " min")
        self.tiempo = _spin(1, 24 * 3600, " s")
        self.hilos = _spin(1, 64)

        general = QGroupBox("General")
        formulario = QFormLayout(general)
        self.errores.fila(formulario, "nombre_escuela", "Nombre de la escuela", self.nombre)
        self.errores.fila(formulario, "margen_traslado_min", "Margen de traslado", self.margen)
        self.errores.fila(formulario, "tiempo_limite_s", "Tiempo límite del solver", self.tiempo)
        self.errores.fila(formulario, "hilos", "Hilos del solver", self.hilos)

        caja_pesos = QGroupBox("Pesos de las restricciones blandas")
        formulario_pesos = QFormLayout(caja_pesos)
        self.pesos: dict[str, QSpinBox] = {}
        for clave, nombre in NOMBRES_PENALIZACIONES.items():
            self.pesos[clave] = _spin(0, 1000)
            formulario_pesos.addRow(nombre, self.pesos[clave])
        restaurar = QPushButton("Restaurar valores por defecto")
        restaurar.clicked.connect(self.restaurar_pesos)
        formulario_pesos.addRow(restaurar)

        self.boton_guardar = QPushButton("Guardar")
        self.boton_guardar.setDefault(True)
        self.boton_guardar.clicked.connect(self.guardar)
        self.estado = QLabel()

        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        capa.addWidget(general)
        capa.addWidget(caja_pesos)
        capa.addWidget(self.errores.general)
        botones = QHBoxLayout()
        botones.addWidget(self.estado, 1)
        botones.addWidget(self.boton_guardar)
        capa.addLayout(botones)
        capa.addStretch()

    def refrescar(self) -> None:
        assert self.repo is not None
        config = self.repo.obtener_configuracion()
        self.nombre.setText(config.nombre_escuela)
        self.margen.setValue(config.margen_traslado_min)
        self.tiempo.setValue(config.tiempo_limite_s)
        self.hilos.setValue(config.hilos)
        self._poner_pesos(config.pesos)
        self.errores.limpiar()
        self.estado.clear()

    def _poner_pesos(self, pesos: Pesos) -> None:
        for clave, valor in pesos.model_dump().items():
            self.pesos[clave].setValue(valor)

    def restaurar_pesos(self) -> None:
        self._poner_pesos(Pesos())

    def guardar(self) -> bool:
        assert self.repo is not None
        repo = self.repo

        def accion() -> None:
            repo.guardar_configuracion(
                Configuracion(
                    nombre_escuela=self.nombre.text(),
                    margen_traslado_min=self.margen.value(),
                    tiempo_limite_s=self.tiempo.value(),
                    hilos=self.hilos.value(),
                    pesos=Pesos(**{c: s.value() for c, s in self.pesos.items()}),
                )
            )

        guardado = self.guardar_con(self.errores, accion, "nombre_escuela")
        self.estado.setText("Cambios guardados." if guardado else "")
        return guardado
