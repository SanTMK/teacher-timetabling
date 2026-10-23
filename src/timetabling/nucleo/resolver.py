"""Creado con Claude. Ejecución cancelable del solver CP-SAT con informe de progreso."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from timetabling.dominio.modelos import Asignacion, DatosEscuela, EstadoSolucion
from timetabling.nucleo.modelo import ModeloHorario, construir_modelo
from timetabling.nucleo.objetivo import construir_objetivo


@dataclass(frozen=True)
class Progreso:
    soluciones: int
    mejor_objetivo: float | None
    cota: float | None
    tiempo_s: float


@dataclass
class ResultadoResolucion:
    estado: EstadoSolucion
    tiempo_s: float
    asignaciones: list[Asignacion] = field(default_factory=list)
    penalizaciones: dict[str, int] = field(default_factory=dict)
    objetivo: float | None = None

    @property
    def tiene_solucion(self) -> bool:
        return bool(self.asignaciones) or self.estado in (
            EstadoSolucion.OPTIMO,
            EstadoSolucion.FACTIBLE,
        )


class _Monitor(cp_model.CpSolverSolutionCallback):
    def __init__(
        self,
        al_progresar: Callable[[Progreso], None] | None,
        inicio: float,
        con_objetivo: bool = True,
        previas: int = 0,
    ) -> None:
        super().__init__()
        self._inicio = inicio
        self._al_progresar = al_progresar
        self._con_objetivo = con_objetivo
        self.soluciones = previas

    def on_solution_callback(self) -> None:
        self.soluciones += 1
        if self._al_progresar is not None:
            self._al_progresar(
                Progreso(
                    soluciones=self.soluciones,
                    mejor_objetivo=self.objective_value if self._con_objetivo else None,
                    cota=self.best_objective_bound if self._con_objetivo else None,
                    tiempo_s=time.perf_counter() - self._inicio,
                )
            )


class Resolutor:
    """Resuelve un ``DatosEscuela``. ``cancelar()`` puede llamarse desde otro hilo y
    conserva la mejor solución encontrada hasta ese momento."""

    def __init__(
        self,
        datos: DatosEscuela,
        tiempo_limite_s: float | None = None,
        hilos: int | None = None,
        al_progresar: Callable[[Progreso], None] | None = None,
        semilla: int | None = None,
    ) -> None:
        self.datos = datos
        self.tiempo_limite_s = tiempo_limite_s or datos.configuracion.tiempo_limite_s
        self.hilos = hilos or datos.configuracion.hilos
        self.al_progresar = al_progresar
        self.semilla = semilla
        self._solver = cp_model.CpSolver()
        self._cancelado = threading.Event()
        self.modelo: ModeloHorario | None = None

    def cancelar(self) -> None:
        self._cancelado.set()
        self._solver.stop_search()

    @property
    def cancelado(self) -> bool:
        return self._cancelado.is_set()

    def resolver(self) -> ResultadoResolucion:
        """Resuelve en dos etapas.

        1. Factibilidad: el modelo sin objetivo, hasta la primera solución. Es mucho más
           rápida y estable que buscar directamente con el objetivo.
        2. Optimización: se restaura el objetivo y se parte de esa solución como pista
           (``add_hint``) durante el tiempo restante.

        Si la segunda etapa no mejora a tiempo, se devuelve la solución de la primera.
        """
        inicio = time.perf_counter()
        mh = construir_modelo(self.datos)
        penalizaciones = construir_objetivo(mh)
        self.modelo = mh
        pesos = self.datos.configuracion.pesos.model_dump()
        objetivo = cp_model.LinearExpr.weighted_sum(
            list(penalizaciones.values()), [pesos[n] for n in penalizaciones]
        )

        def restante() -> float:
            return self.tiempo_limite_s - (time.perf_counter() - inicio)

        def cancelado() -> ResultadoResolucion:
            return ResultadoResolucion(EstadoSolucion.CANCELADO, time.perf_counter() - inicio)

        if self.cancelado:
            return cancelado()

        parametros = self._solver.parameters
        parametros.num_workers = self.hilos
        if self.semilla is not None:
            parametros.random_seed = self.semilla

        # Etapa 1: factibilidad
        mh.modelo.clear_objective()
        parametros.max_time_in_seconds = max(1.0, restante())
        parametros.stop_after_first_solution = True
        estado_cp = self._solver.solve(
            mh.modelo, _Monitor(self.al_progresar, inicio, con_objetivo=False)
        )
        self._comprobar_modelo(estado_cp, mh)
        if estado_cp == cp_model.INFEASIBLE:
            return ResultadoResolucion(EstadoSolucion.INFACTIBLE, time.perf_counter() - inicio)
        if estado_cp not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if self.cancelado:
                return cancelado()
            return ResultadoResolucion(
                EstadoSolucion.SIN_SOLUCION_EN_TIEMPO, time.perf_counter() - inicio
            )
        primera = self._extraer(mh, penalizaciones)
        if not penalizaciones or self.cancelado or restante() < 1.0:
            estado = EstadoSolucion.CANCELADO if self.cancelado else EstadoSolucion.FACTIBLE
            if not penalizaciones and not self.cancelado:
                estado = EstadoSolucion.OPTIMO
            return ResultadoResolucion(
                estado, time.perf_counter() - inicio, *primera, objetivo=self._valor(primera[1])
            )

        # Etapa 2: optimización a partir de la primera solución
        for var in mh.x.values():
            mh.modelo.add_hint(var, self._solver.boolean_value(var))
        mh.modelo.minimize(objetivo)
        parametros.stop_after_first_solution = False
        parametros.max_time_in_seconds = max(1.0, restante())
        estado_cp = self._solver.solve(mh.modelo, _Monitor(self.al_progresar, inicio, previas=1))
        self._comprobar_modelo(estado_cp, mh)
        tiempo = time.perf_counter() - inicio
        if estado_cp not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            estado = EstadoSolucion.CANCELADO if self.cancelado else EstadoSolucion.FACTIBLE
            return ResultadoResolucion(estado, tiempo, *primera, objetivo=self._valor(primera[1]))
        if self.cancelado:
            estado = EstadoSolucion.CANCELADO
        elif estado_cp == cp_model.OPTIMAL:
            estado = EstadoSolucion.OPTIMO
        else:
            estado = EstadoSolucion.FACTIBLE
        asignaciones, valores = self._extraer(mh, penalizaciones)
        return ResultadoResolucion(
            estado, tiempo, asignaciones, valores, self._solver.objective_value
        )

    @staticmethod
    def _comprobar_modelo(estado_cp: int, mh: ModeloHorario) -> None:
        if estado_cp == cp_model.MODEL_INVALID:
            raise RuntimeError(
                "Error interno: el modelo CP-SAT es inválido: " + mh.modelo.validate()
            )

    def _valor(self, valores: dict[str, int]) -> float:
        pesos = self.datos.configuracion.pesos.model_dump()
        return float(sum(pesos[n] * v for n, v in valores.items()))

    def _extraer(
        self, mh: ModeloHorario, penalizaciones: dict[str, cp_model.LinearExprT]
    ) -> tuple[list[Asignacion], dict[str, int]]:
        """Asignaciones y valor de cada penalización en la última solución del solver.

        Tras la etapa de factibilidad (sin objetivo) los valores de las penalizaciones son
        cotas superiores: sus variables auxiliares solo están acotadas por debajo.
        """
        asignaciones = [
            Asignacion(
                grupo_id=g,
                asignatura_id=a,
                profesor_id=p,
                nivel_id=mh.franjas[s].nivel_id,
                dia=mh.franjas[s].dia,
                indice=mh.franjas[s].indice,
            )
            for (g, a, p, s), var in mh.x.items()
            if self._solver.boolean_value(var)
        ]
        valores = {nombre: int(self._solver.value(expr)) for nombre, expr in penalizaciones.items()}
        return asignaciones, valores


def resolver(
    datos: DatosEscuela,
    tiempo_limite_s: float | None = None,
    hilos: int | None = None,
    al_progresar: Callable[[Progreso], None] | None = None,
) -> ResultadoResolucion:
    """Atajo para resolver sin necesidad de cancelar."""
    return Resolutor(datos, tiempo_limite_s, hilos, al_progresar).resolver()
