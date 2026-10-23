"""Creado con Claude. Generación de franjas por nivel y matriz de traslapes."""

from __future__ import annotations

from collections import defaultdict

from timetabling.dominio.modelos import (
    DatosEscuela,
    Disponibilidad,
    Franja,
    Nivel,
    Profesor,
    TipoDisponibilidad,
)


def generar_franjas_nivel(nivel: Nivel) -> list[Franja]:
    """Genera las franjas consecutivas de cada día lectivo del nivel.

    Si una franja chocaría con un receso, la siguiente comienza al terminar el receso.
    Se detiene cuando la franja ya no cabe antes del fin de la jornada.
    """
    if nivel.id is None:
        raise ValueError(f"El nivel «{nivel.nombre}» no tiene id")
    recesos = sorted(nivel.recesos, key=lambda r: r.inicio)
    franjas: list[Franja] = []
    for dia in nivel.dias:
        inicio = nivel.inicio_jornada
        indice = 0
        receso_pendiente = False
        while True:
            fin = inicio + nivel.duracion_min
            if fin > nivel.fin_jornada:
                break
            choque = next((r for r in recesos if inicio < r.fin and r.inicio < fin), None)
            if choque is not None:
                inicio = choque.fin
                receso_pendiente = indice > 0
                continue
            franjas.append(
                Franja(
                    nivel_id=nivel.id,
                    dia=dia,
                    indice=indice,
                    inicio=inicio,
                    fin=fin,
                    receso_antes=receso_pendiente,
                )
            )
            receso_pendiente = False
            inicio = fin
            indice += 1
    return franjas


def generar_franjas(datos: DatosEscuela) -> list[Franja]:
    """Franjas de todos los niveles."""
    return [f for nivel in datos.niveles for f in generar_franjas_nivel(nivel)]


def separadas_por_receso(a: Franja, b: Franja) -> bool:
    """Verdadero si entre dos franjas consecutivas del mismo nivel y día hay un receso."""
    primera, segunda = (a, b) if a.indice < b.indice else (b, a)
    return segunda.receso_antes or primera.fin != segunda.inicio


def adyacentes(a: Franja, b: Franja) -> bool:
    """Consecutivas, del mismo nivel y día, sin receso entre ellas (aptas para bloque doble)."""
    return (
        a.nivel_id == b.nivel_id
        and a.dia == b.dia
        and abs(a.indice - b.indice) == 1
        and not separadas_por_receso(a, b)
    )


def se_traslapan(a: Franja, b: Franja, margen_min: int) -> bool:
    """Dos franjas del mismo día se traslapan si ``a < d + m`` y ``c < b + m``.

    El margen de traslado solo aplica entre niveles distintos.
    """
    if a.dia != b.dia:
        return False
    margen = margen_min if a.nivel_id != b.nivel_id else 0
    return a.inicio < b.fin + margen and b.inicio < a.fin + margen


def matriz_traslapes(franjas: list[Franja], margen_min: int) -> dict[str, set[str]]:
    """``franja_id → {franja_id}`` de las otras franjas con las que se traslapa."""
    matriz: dict[str, set[str]] = {f.id: set() for f in franjas}
    por_dia: dict[str, list[Franja]] = defaultdict(list)
    for franja in franjas:
        por_dia[franja.dia].append(franja)
    for del_dia in por_dia.values():
        for i, a in enumerate(del_dia):
            for b in del_dia[i + 1 :]:
                if se_traslapan(a, b, margen_min):
                    matriz[a.id].add(b.id)
                    matriz[b.id].add(a.id)
    return matriz


def cliques_maximales(matriz: dict[str, set[str]]) -> list[frozenset[str]]:
    """Cliques maximales del grafo de traslapes (Bron–Kerbosch con pivote).

    Incluye cliques de un solo elemento para las franjas aisladas, de modo que cada
    franja y cada par traslapado queda cubierto por al menos un clique.
    """
    resultado: list[frozenset[str]] = []

    def expandir(r: set[str], p: set[str], x: set[str]) -> None:
        if not p and not x:
            resultado.append(frozenset(r))
            return
        pivote = max(p | x, key=lambda v: len(matriz[v] & p))
        for v in list(p - matriz[pivote]):
            expandir(r | {v}, p & matriz[v], x & matriz[v])
            p.remove(v)
            x.add(v)

    expandir(set(), set(matriz), set())
    return resultado


def tipo_disponibilidad(
    franja: Franja, disponibilidad: list[Disponibilidad]
) -> TipoDisponibilidad | None:
    """Indica si la franja es válida para un profesor y con qué tipo.

    La franja debe caber completa en la unión de los rangos de ese día (rangos contiguos
    o traslapados se consideran uno solo). Es ``preferible_no`` si toca algún rango de
    ese tipo; ``None`` si no está disponible.
    """
    rangos = sorted((d for d in disponibilidad if d.dia == franja.dia), key=lambda d: d.inicio)
    cubierto_hasta: int | None = None
    inicio_union: int | None = None
    cabe = False
    for rango in rangos:
        if cubierto_hasta is None or rango.inicio > cubierto_hasta:
            inicio_union, cubierto_hasta = rango.inicio, rango.fin
        else:
            cubierto_hasta = max(cubierto_hasta, rango.fin)
        if (
            inicio_union is not None
            and inicio_union <= franja.inicio
            and franja.fin <= cubierto_hasta
        ):
            cabe = True
            break
    if not cabe:
        return None
    toca_no_preferible = any(
        d.tipo == TipoDisponibilidad.PREFERIBLE_NO
        and d.inicio < franja.fin
        and franja.inicio < d.fin
        for d in rangos
    )
    return TipoDisponibilidad.PREFERIBLE_NO if toca_no_preferible else TipoDisponibilidad.DISPONIBLE


def franjas_validas_profesor(
    profesor: Profesor, franjas: list[Franja]
) -> dict[str, TipoDisponibilidad]:
    """``franja_id → tipo`` de las franjas en que el profesor puede dar clase."""
    validas: dict[str, TipoDisponibilidad] = {}
    for franja in franjas:
        tipo = tipo_disponibilidad(franja, profesor.disponibilidad)
        if tipo is not None:
            validas[franja.id] = tipo
    return validas
