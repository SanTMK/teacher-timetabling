"""Creado con Claude. Pantalla Generar: lanza el solver en segundo plano y muestra el progreso."""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from timetabling.dominio.estadisticas import penalizacion_total
from timetabling.dominio.modelos import EstadoSolucion, Pesos, Solucion
from timetabling.gui.pantallas.base import Pantalla
from timetabling.gui.trabajador import ResultadoTrabajo, TrabajadorResolucion
from timetabling.nucleo.resolver import Progreso
from timetabling.nucleo.validacion import Severidad, validar

_ESTADOS = {
    EstadoSolucion.OPTIMO: "Óptima",
    EstadoSolucion.FACTIBLE: "Factible (se agotó el tiempo; puede no ser la mejor)",
    EstadoSolucion.INFACTIBLE: "Sin solución posible con los datos actuales",
    EstadoSolucion.SIN_SOLUCION_EN_TIEMPO: "No se encontró solución en el tiempo límite",
    EstadoSolucion.CANCELADO: "Cancelada",
}


class PantallaGenerar(Pantalla):
    titulo = "Generar"
    resolviendo = Signal(bool)
    solucion_guardada = Signal(int)
    ver_validacion = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.trabajador: TrabajadorResolucion | None = None
        self.ultima_solucion_id: int | None = None
        self._inicio = 0.0
        self._limite = 1.0
        self._pesos = Pesos()
        self._reloj = QTimer(self)
        self._reloj.setInterval(200)
        self._reloj.timeout.connect(self._tic)

        self.boton_generar = QPushButton("Generar horario")
        self.boton_generar.setDefault(True)
        self.boton_generar.clicked.connect(lambda: self.generar())
        self.boton_cancelar = QPushButton("Cancelar")
        self.boton_cancelar.setToolTip("Detiene la búsqueda y conserva la mejor solución hallada")
        self.boton_cancelar.setEnabled(False)
        self.boton_cancelar.clicked.connect(self.cancelar)
        self.barra = QProgressBar()
        self.barra.setFormat("%p % del tiempo límite")
        self.fase = QLabel("Listo para generar.")
        self.mejor = QLabel("—")
        self.soluciones = QLabel("0")
        self.transcurrido = QLabel("0,0 s")
        self.mensaje = QLabel()
        self.mensaje.setWordWrap(True)
        self.boton_resultados = QPushButton("Ver resultados")
        self.boton_resultados.setVisible(False)
        self.boton_resultados.clicked.connect(
            lambda: (
                self.ultima_solucion_id is not None
                and self.solucion_guardada.emit(self.ultima_solucion_id)
            )
        )
        self.boton_validacion = QPushButton("Ir a Validación")
        self.boton_validacion.setVisible(False)
        self.boton_validacion.clicked.connect(self.ver_validacion.emit)
        self.diagnostico = QListWidget()
        self.diagnostico.setWordWrap(True)
        self.caja_diagnostico = QGroupBox("Posibles causas del conflicto")
        capa_diag = QVBoxLayout(self.caja_diagnostico)
        capa_diag.addWidget(self.diagnostico)
        self.caja_diagnostico.setVisible(False)

        botones = QHBoxLayout()
        botones.addWidget(self.boton_generar)
        botones.addWidget(self.boton_cancelar)
        botones.addStretch()
        datos = QFormLayout()
        datos.addRow("Etapa", self.fase)
        datos.addRow("Mejor penalización", self.mejor)
        datos.addRow("Soluciones encontradas", self.soluciones)
        datos.addRow("Tiempo transcurrido", self.transcurrido)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        capa.addLayout(botones)
        capa.addWidget(self.barra)
        capa.addLayout(datos)
        capa.addWidget(self.mensaje)
        acciones = QHBoxLayout()
        acciones.addWidget(self.boton_resultados)
        acciones.addWidget(self.boton_validacion)
        acciones.addStretch()
        capa.addLayout(acciones)
        capa.addWidget(self.caja_diagnostico, 1)
        capa.addStretch()

    @property
    def en_curso(self) -> bool:
        return self.trabajador is not None

    def refrescar(self) -> None:
        if not self.en_curso:
            assert self.repo is not None
            config = self.repo.obtener_configuracion()
            self.fase.setText(
                f"Listo para generar (tiempo límite {config.tiempo_limite_s} s, "
                f"{config.hilos} hilos)."
            )

    def _mostrar_mensaje(self, texto: str, color: str = "") -> None:
        self.mensaje.setText(texto)
        self.mensaje.setStyleSheet(f"color: {color};" if color else "")

    # --- Ciclo de resolución --------------------------------------------------------

    def generar(self, tiempo_limite_s: float | None = None) -> bool:
        """Valida y lanza el solver en segundo plano. Devuelve falso si no se lanzó."""
        if self.en_curso or self.repo is None:
            return False
        datos = self.repo.cargar_datos()
        self.boton_resultados.setVisible(False)
        self.boton_validacion.setVisible(False)
        self.caja_diagnostico.setVisible(False)
        self.diagnostico.clear()
        errores = [p for p in validar(datos) if p.severidad == Severidad.ERROR]
        if errores:
            self._mostrar_mensaje(
                f"Hay {len(errores)} error(es) en los datos; corríjalos antes de generar.\n"
                + "\n".join(f"• {p.mensaje}" for p in errores[:5]),
                "#C62828",
            )
            self.boton_validacion.setVisible(True)
            return False
        self._limite = float(tiempo_limite_s or datos.configuracion.tiempo_limite_s)
        self.trabajador = TrabajadorResolucion(datos, tiempo_limite_s)
        self.trabajador.progreso.connect(self._al_progresar)
        self.trabajador.fase.connect(self.fase.setText)
        self.trabajador.terminado.connect(self._al_terminar)
        self.trabajador.fallo.connect(self._al_fallar)
        self._pesos = datos.configuracion.pesos
        self.mejor.setText("—")
        self.soluciones.setText("0")
        self.barra.setValue(0)
        self._mostrar_mensaje("")
        self.boton_generar.setEnabled(False)
        self.boton_cancelar.setEnabled(True)
        self._inicio = time.monotonic()
        self._reloj.start()
        self.resolviendo.emit(True)
        self.trabajador.start()
        return True

    def cancelar(self) -> None:
        if self.trabajador is not None:
            self.boton_cancelar.setEnabled(False)
            self.fase.setText("Cancelando…")
            self.trabajador.cancelar()

    def _tic(self) -> None:
        transcurrido = time.monotonic() - self._inicio
        self.transcurrido.setText(f"{transcurrido:.1f} s".replace(".", ","))
        self.barra.setValue(min(100, int(100 * transcurrido / self._limite)))

    def _al_progresar(self, progreso: Progreso) -> None:
        self.soluciones.setText(str(progreso.soluciones))
        if progreso.mejor_objetivo is not None:
            self.mejor.setText(f"{progreso.mejor_objetivo:g}")

    def _terminar_trabajo(self) -> None:
        self._reloj.stop()
        self._tic()
        if self.trabajador is not None:
            self.trabajador.wait()
            self.trabajador.deleteLater()
        self.trabajador = None
        self.boton_generar.setEnabled(True)
        self.boton_cancelar.setEnabled(False)
        self.resolviendo.emit(False)

    def _al_fallar(self, detalle: str) -> None:
        self._terminar_trabajo()
        self.fase.setText("Error")
        self._mostrar_mensaje(f"Ocurrió un error interno al resolver:\n{detalle}", "#C62828")

    def _al_terminar(self, trabajo: ResultadoTrabajo) -> None:
        self._terminar_trabajo()
        resultado = trabajo.resultado
        self.barra.setValue(100)
        self.fase.setText(_ESTADOS[resultado.estado])
        if trabajo.violaciones:
            self._mostrar_mensaje(
                "Error interno: la solución no pasó la verificación y no se guardó.\n"
                + "\n".join(f"• {v}" for v in trabajo.violaciones[:10]),
                "#C62828",
            )
            return
        if resultado.asignaciones:
            assert self.repo is not None
            guardada = self.repo.guardar_solucion(
                Solucion(
                    estado=resultado.estado,
                    tiempo_s=round(resultado.tiempo_s, 2),
                    penalizaciones=resultado.penalizaciones,
                    asignaciones=resultado.asignaciones,
                )
            )
            self.ultima_solucion_id = guardada.id
            total = penalizacion_total(resultado.penalizaciones, self._pesos)
            self.mejor.setText(str(total))
            self._mostrar_mensaje(
                f"Solución #{guardada.id} verificada y guardada (penalización {total}).",
                "#2E7D32",
            )
            self.boton_resultados.setVisible(True)
            self.datos_cambiados.emit()
            return
        if resultado.estado == EstadoSolucion.INFACTIBLE:
            self._mostrar_mensaje(
                "No existe un horario que cumpla todas las restricciones duras.", "#C62828"
            )
            for conflicto in trabajo.diagnostico:
                self.diagnostico.addItem(f"• {conflicto.mensaje}")
            if not trabajo.diagnostico:
                self.diagnostico.addItem("No se pudo identificar la causa en el tiempo disponible.")
            self.caja_diagnostico.setVisible(True)
        elif resultado.estado == EstadoSolucion.SIN_SOLUCION_EN_TIEMPO:
            self._mostrar_mensaje(
                "No se encontró ninguna solución en el tiempo límite. Aumente el tiempo en "
                "Configuración o revise los datos.",
                "#EF6C00",
            )
        else:
            self._mostrar_mensaje("Se canceló antes de encontrar una solución.", "#EF6C00")
