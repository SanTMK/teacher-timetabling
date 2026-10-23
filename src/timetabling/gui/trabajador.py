"""Creado con Claude. Ejecución del solver en un ``QThread`` con señales de progreso.

El hilo solo trabaja con una copia de los datos del dominio; guardar la solución en la base
de datos queda a cargo del hilo de la interfaz (la conexión SQLite no se comparte).
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from timetabling.dominio.modelos import DatosEscuela, EstadoSolucion
from timetabling.nucleo.diagnostico import Conflicto, diagnosticar
from timetabling.nucleo.resolver import Progreso, Resolutor, ResultadoResolucion
from timetabling.nucleo.verificador import Violacion, verificar

TIEMPO_DIAGNOSTICO_S = 30.0


@dataclass
class ResultadoTrabajo:
    resultado: ResultadoResolucion
    violaciones: list[Violacion] = field(default_factory=list)
    diagnostico: list[Conflicto] = field(default_factory=list)


class TrabajadorResolucion(QThread):
    progreso = Signal(object)  # Progreso
    fase = Signal(str)  # texto de la etapa actual
    terminado = Signal(object)  # ResultadoTrabajo
    fallo = Signal(str)

    def __init__(self, datos: DatosEscuela, tiempo_limite_s: float | None = None) -> None:
        super().__init__()
        self.datos = datos.model_copy(deep=True)
        self.resolutor = Resolutor(self.datos, tiempo_limite_s, al_progresar=self._al_progresar)

    def _al_progresar(self, progreso: Progreso) -> None:
        self.progreso.emit(progreso)

    def cancelar(self) -> None:
        """Detiene la búsqueda conservando la mejor solución encontrada."""
        self.resolutor.cancelar()

    def run(self) -> None:
        try:
            self.fase.emit("Construyendo el modelo y buscando soluciones…")
            resultado = self.resolutor.resolver()
            trabajo = ResultadoTrabajo(resultado)
            if resultado.asignaciones:
                self.fase.emit("Verificando la solución…")
                trabajo.violaciones = verificar(self.datos, resultado.asignaciones)
            elif resultado.estado == EstadoSolucion.INFACTIBLE:
                self.fase.emit("Buscando la causa del conflicto…")
                trabajo.diagnostico = diagnosticar(self.datos, TIEMPO_DIAGNOSTICO_S)
            self.terminado.emit(trabajo)
        except Exception:  # noqa: BLE001 - se informa a la interfaz
            self.fallo.emit(traceback.format_exc())
