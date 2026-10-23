"""Creado con Claude. Restricciones blandas (penalizaciones ponderadas B1–B8)."""

from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model

from timetabling.dominio.modelos import BloqueDoble, TipoDisponibilidad
from timetabling.nucleo.modelo import ModeloHorario, franjas_del_dia

Expr = cp_model.LinearExprT


def construir_objetivo(mh: ModeloHorario) -> dict[str, Expr]:
    """Agrega las penalizaciones al modelo y fija el objetivo de minimización.

    Devuelve ``nombre de penalización → expresión`` (sin ponderar) para poder informar
    el valor de cada una tras resolver. Las penalizaciones con peso 0 no se construyen.
    """
    pesos = mh.datos.configuracion.pesos.model_dump()
    constructores = {
        "huecos_profesor": _b1_huecos_profesor,
        "distribucion_semanal": _b2_distribucion_semanal,
        "exigente_tarde": _b3_exigente_tarde,
        "preferible_no": _b4_preferible_no,
        "dias_profesor": _b5_dias_profesor,
        "desequilibrio_carga": _b6_desequilibrio_carga,
        "titular_preescolar": _b7_titular_preescolar,
        "bloque_doble_preferido": _b8_bloque_doble_preferido,
    }
    penalizaciones: dict[str, Expr] = {}
    for nombre, construir in constructores.items():
        if pesos[nombre] > 0:
            terminos = construir(mh)
            if terminos:
                penalizaciones[nombre] = cp_model.LinearExpr.sum(terminos)
    if penalizaciones:
        mh.modelo.minimize(
            cp_model.LinearExpr.weighted_sum(
                list(penalizaciones.values()), [pesos[n] for n in penalizaciones]
            )
        )
    return penalizaciones


def _b1_huecos_profesor(mh: ModeloHorario) -> list[Expr]:
    """Franjas libres entre la primera y la última clase del día, por nivel.

    ``empezo[k] ≥ empezo[k-1]``, ``empezo[k] ≥ o[k]``; ``sigue[k] ≥ sigue[k+1]``,
    ``sigue[k] ≥ o[k]``; ``hueco[k] ≥ empezo[k] + sigue[k] − 1 − o[k]``.
    """
    modelo = mh.modelo
    terminos: list[Expr] = []
    for profesor in mh.datos.profesores:
        p = profesor.id
        for nivel_id, dia in mh.franjas_por_nivel_dia:
            franjas = franjas_del_dia(mh, nivel_id, dia)
            ocupacion = [mh.o.get((p, f.id)) for f in franjas]
            posiciones = [k for k, o in enumerate(ocupacion) if o is not None]
            if len(posiciones) < 3:
                continue  # con menos de tres franjas posibles no puede haber hueco
            inicio, fin = posiciones[0], posiciones[-1]
            empezo = [modelo.new_bool_var("") for _ in range(inicio, fin + 1)]
            sigue = [modelo.new_bool_var("") for _ in range(inicio, fin + 1)]
            for j, k in enumerate(range(inicio, fin + 1)):
                o = ocupacion[k]
                if j:
                    modelo.add(empezo[j] >= empezo[j - 1])
                    modelo.add(sigue[j - 1] >= sigue[j])
                if o is not None:
                    modelo.add(empezo[j] >= o)
                    modelo.add(sigue[j] >= o)
                if 0 < j < fin - inicio:
                    hueco = modelo.new_bool_var("")
                    libre = 1 - o if o is not None else 1
                    modelo.add(hueco >= empezo[j] + sigue[j] + libre - 2)
                    terminos.append(hueco)
    return terminos


def _b2_distribucion_semanal(mh: ModeloHorario) -> list[Expr]:
    """Clases de más (más de una por día) cuando las horas semanales ≤ días lectivos."""
    terminos: list[Expr] = []
    for grupo in mh.datos.grupos:
        nivel = mh.datos.nivel_de_grupo(grupo)
        for a, horas in mh.datos.plan_de_grado(grupo.grado_id).items():
            if horas > len(nivel.dias) or horas < 2:
                continue
            por_dia: dict[str, list[cp_model.IntVar]] = defaultdict(list)
            for s in {k[3] for k in mh.por_ga.get((grupo.id, a), [])}:
                por_dia[mh.franjas[s].dia].append(mh.z[(grupo.id, a, s)])
            for variables in por_dia.values():
                if len(variables) < 2:
                    continue
                exceso = mh.modelo.new_int_var(0, len(variables) - 1, "")
                mh.modelo.add(exceso >= cp_model.LinearExpr.sum(variables) - 1)
                terminos.append(exceso)
    return terminos


def _b3_exigente_tarde(mh: ModeloHorario) -> list[Expr]:
    """Clases de asignaturas exigentes que empiezan después de la mitad de la jornada."""
    exigentes = {a.id for a in mh.datos.asignaturas if a.exigente}
    mitad = {n.id: (n.inicio_jornada + n.fin_jornada) / 2 for n in mh.datos.niveles}
    return [
        var
        for (g, a, s), var in mh.z.items()
        if a in exigentes and mh.franjas[s].inicio >= mitad[mh.franjas[s].nivel_id]
    ]


def _b4_preferible_no(mh: ModeloHorario) -> list[Expr]:
    return [
        var
        for (g, a, p, s), var in mh.x.items()
        if mh.validas[p].get(s) == TipoDisponibilidad.PREFERIBLE_NO
    ]


def _b5_dias_profesor(mh: ModeloHorario) -> list[Expr]:
    """Un punto por cada día en que el profesor tiene al menos una clase."""
    por_dia: dict[tuple[int, str], list[cp_model.IntVar]] = defaultdict(list)
    for (p, s), var in mh.o.items():
        por_dia[(p, mh.franjas[s].dia)].append(var)
    terminos: list[Expr] = []
    for variables in por_dia.values():
        trabaja = mh.modelo.new_bool_var("")
        for var in variables:
            mh.modelo.add_implication(var, trabaja)
        terminos.append(trabaja)
    return terminos


def _b6_desequilibrio_carga(mh: ModeloHorario) -> list[Expr]:
    """Diferencia entre la carga máxima y mínima de los profesores de cada asignatura y
    nivel (solo se comparan docentes que podrían repartirse esos grupos), en unidades de la
    hora-clase más corta (redondeo hacia arriba)."""
    unidad = min((n.duracion_min for n in mh.datos.niveles), default=50)
    carga: dict[int, Expr] = {}
    profesores_de: dict[tuple[int, int], set[int]] = defaultdict(set)
    claves_de: dict[int, list[tuple[int, int, int, str]]] = defaultdict(list)
    for clave in mh.x:
        claves_de[clave[2]].append(clave)
        profesores_de[(clave[1], mh.franjas[clave[3]].nivel_id)].add(clave[2])
    for p, claves in claves_de.items():
        carga[p] = mh.suma(claves, {k: mh.franjas[k[3]].duracion for k in claves})
    terminos: list[Expr] = []
    for _a, profesores in profesores_de.items():
        if len(profesores) < 2:
            continue
        tope = max(mh.datos.profesor(p).carga_max_semanal_min for p in profesores)
        maximo = mh.modelo.new_int_var(0, tope, "")
        minimo = mh.modelo.new_int_var(0, tope, "")
        for p in profesores:
            mh.modelo.add(maximo >= carga[p])
            mh.modelo.add(minimo <= carga[p])
        diferencia = mh.modelo.new_int_var(0, tope // unidad + 1, "")
        mh.modelo.add(unidad * diferencia >= maximo - minimo)
        terminos.append(diferencia)
    return terminos


def _b7_titular_preescolar(mh: ModeloHorario) -> list[Expr]:
    """Franjas de grupos de preescolar con titular que no imparte el titular."""
    terminos: list[Expr] = []
    for grupo in mh.datos.grupos:
        if grupo.titular_id is None or not mh.datos.nivel_de_grupo(grupo).es_preescolar:
            continue
        terminos.extend(
            var for (g, a, p, s), var in mh.x.items() if g == grupo.id and p != grupo.titular_id
        )
    return terminos


def _b8_bloque_doble_preferido(mh: ModeloHorario) -> list[Expr]:
    """Horas no emparejadas en asignaturas con bloque doble preferido (sin contar la hora
    impar inevitable)."""
    terminos: list[Expr] = []
    for grupo in mh.datos.grupos:
        for a, horas in mh.datos.plan_de_grado(grupo.grado_id).items():
            if mh.datos.asignatura(a).bloque_doble != BloqueDoble.PREFERIDO:
                continue
            sueltas = mh.sueltas.get((grupo.id, a))
            if sueltas:
                terminos.append(cp_model.LinearExpr.sum(sueltas) - horas % 2)
    return terminos
