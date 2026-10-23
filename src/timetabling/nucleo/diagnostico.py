"""Creado con Claude. Explicación de la infactibilidad de un modelo.

Reconstruye el modelo sin objetivo, con cada grupo de restricciones condicionado a un
literal de suposición (por profesor, por grupo y asignatura, por tipo de restricción), y
usa ``sufficient_assumptions_for_infeasibility`` de CP-SAT para obtener un subconjunto en
conflicto. Según la documentación de OR-Tools, ese subconjunto solo se minimiza con un
único hilo y en problemas sin objetivo; además no se garantiza que sea mínimo, por lo que
después se aplica un filtro de eliminación (se quita cada suposición y se comprueba si el
resto sigue siendo infactible).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from timetabling.dominio.modelos import NOMBRES_DIAS, DatosEscuela
from timetabling.nucleo.franjas import franjas_validas_profesor, generar_franjas_nivel
from timetabling.nucleo.modelo import Clave, ModeloHorario, construir_modelo


@dataclass(frozen=True)
class Conflicto:
    clave: Clave
    entidad: str  # pantalla a la que lleva: profesores, grupos, asignaturas, espacios…
    elemento_id: int | None
    mensaje: str

    def __str__(self) -> str:
        return self.mensaje


def _resolver(mh: ModeloHorario, claves: list[Clave], tiempo_s: float) -> tuple[int, list[Clave]]:
    modelo = mh.modelo
    modelo.clear_assumptions()
    modelo.add_assumptions([mh.suposiciones[c] for c in claves])
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1  # requisito para que el núcleo se minimice
    solver.parameters.max_time_in_seconds = max(0.5, tiempo_s)
    estado = solver.solve(modelo)
    if estado != cp_model.INFEASIBLE:
        return estado, []
    indices = set(solver.sufficient_assumptions_for_infeasibility())
    return estado, [c for c in claves if mh.suposiciones[c].index in indices]


def diagnosticar(
    datos: DatosEscuela, tiempo_limite_s: float = 60.0, minimizar: bool = True
) -> list[Conflicto]:
    """Devuelve un conjunto pequeño de restricciones que juntas no pueden cumplirse.

    Lista vacía si no se pudo demostrar la infactibilidad en el tiempo dado.
    """
    limite = time.perf_counter() + tiempo_limite_s
    mh = construir_modelo(datos, con_suposiciones=True)
    todas = list(mh.suposiciones)
    estado, nucleo = _resolver(mh, todas, tiempo_limite_s)
    if estado != cp_model.INFEASIBLE:
        return []
    if not nucleo:
        return [
            Conflicto(
                ("estructural",),
                "validacion",
                None,
                "Los datos son contradictorios aun sin restricciones de horario; revise la "
                "validación.",
            )
        ]
    if minimizar:
        for clave in list(nucleo):
            restante = limite - time.perf_counter()
            if restante <= 0 or len(nucleo) == 1:
                break
            if clave not in nucleo:
                continue
            prueba = [c for c in nucleo if c != clave]
            estado, nuevo = _resolver(mh, prueba, min(restante, 10.0))
            if estado == cp_model.INFEASIBLE:
                nucleo = nuevo or prueba
    return [traducir(datos, clave) for clave in nucleo]


def traducir(datos: DatosEscuela, clave: Clave) -> Conflicto:
    """Convierte una clave de restricción en un mensaje legible."""
    tipo = clave[0]
    if tipo == "curricular":
        g, a = int(clave[1]), int(clave[2])  # type: ignore[call-overload]
        grupo = datos.grupo(g)
        asignatura = datos.asignatura(a)
        horas = datos.plan_de_grado(grupo.grado_id).get(a, 0)
        franjas_nivel = generar_franjas_nivel(datos.nivel_de_grupo(grupo))
        habilitados = [
            f"{p.nombre}, disponible en {len(franjas_validas_profesor(p, franjas_nivel))} franjas"
            for p in datos.profesores
            if a in p.asignaturas and grupo.grado_id in p.grados
        ]
        return Conflicto(
            clave,
            "profesores",
            a,
            f"Las {horas} horas semanales de {asignatura.nombre} en "
            f"{datos.nombre_grupo(grupo)} deben darse con un único profesor habilitado y "
            f"disponible ({'; '.join(habilitados) or 'ninguno habilitado'})",
        )
    if tipo == "grupo":
        grupo = datos.grupo(int(clave[1]))  # type: ignore[call-overload]
        return Conflicto(
            clave,
            "grupos",
            grupo.id,
            f"{datos.nombre_grupo(grupo)} solo puede recibir una clase por franja",
        )
    if tipo in ("profesor", "carga", "consecutivas"):
        profesor = datos.profesor(int(clave[1]))  # type: ignore[call-overload]
        if tipo == "profesor":
            margen = datos.configuracion.margen_traslado_min
            detalle = f" (con margen de traslado de {margen} min)" if margen else ""
            mensaje = (
                f"{profesor.nombre} no puede estar en dos clases a la vez{detalle}, y solo da "
                "clase dentro de su disponibilidad"
            )
        elif tipo == "carga":
            mensaje = (
                f"Carga máxima de {profesor.nombre}: {profesor.carga_max_semanal_min} "
                f"min/semana y {profesor.carga_max_diaria_min} min/día"
            )
        else:
            mensaje = (
                f"{profesor.nombre} no puede dar más de {profesor.max_consecutivas} clases "
                "consecutivas"
            )
        return Conflicto(clave, "profesores", profesor.id, mensaje)
    if tipo == "espacio":
        tipo_espacio = str(clave[1])
        cantidad = datos.capacidad_espacios().get(tipo_espacio, 0)
        return Conflicto(
            clave,
            "espacios",
            None,
            f"Solo hay {cantidad} espacio(s) de tipo «{tipo_espacio}» a la vez",
        )
    if tipo in ("diaria", "bloque"):
        g, a = int(clave[1]), int(clave[2])  # type: ignore[call-overload]
        asignatura = datos.asignatura(a)
        nombre_grupo = datos.nombre_grupo(datos.grupo(g))
        if tipo == "diaria":
            extra = " y deben ser consecutivas" if asignatura.max_horas_dia == 2 else ""
            mensaje = (
                f"{asignatura.nombre} en {nombre_grupo}: máximo {asignatura.max_horas_dia} "
                f"hora{'s' if asignatura.max_horas_dia != 1 else ''} por día{extra}"
            )
        else:
            mensaje = (
                f"{asignatura.nombre} en {nombre_grupo} debe darse en bloques dobles sin "
                "receso intermedio"
            )
        return Conflicto(clave, "asignaturas", a, mensaje)
    if tipo == "sin_huecos":
        grupo = datos.grupo(int(clave[1]))  # type: ignore[call-overload]
        return Conflicto(
            clave,
            "niveles",
            datos.nivel_de_grupo(grupo).id,
            f"{datos.nombre_grupo(grupo)} no puede tener huecos: sus clases deben empezar en "
            "la primera franja y ser continuas",
        )
    if tipo == "fija":
        fija = datos.asignaciones_fijas[int(clave[1])]  # type: ignore[call-overload]
        con = f" con {datos.profesor(fija.profesor_id).nombre}" if fija.profesor_id else ""
        return Conflicto(
            clave,
            "asignaciones_fijas",
            fija.id,
            f"Asignación fija: {datos.asignatura(fija.asignatura_id).nombre}{con} en "
            f"{datos.nombre_grupo(datos.grupo(fija.grupo_id))} el "
            f"{NOMBRES_DIAS.get(fija.dia, fija.dia)}, franja {fija.indice_franja + 1}",
        )
    return Conflicto(clave, "validacion", None, f"Restricción {clave}")
