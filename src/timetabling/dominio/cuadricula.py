"""Creado con Claude. Disposición de un horario en cuadrícula (filas × días).

Es la lógica visual común a la vista de horario de la interfaz y a la exportación a Excel:

* Grupos, y profesores de un solo nivel: una fila por franja del nivel, con filas de receso
  intercaladas.
* Profesores de varios niveles: escala de tiempo proporcional (filas de 5 minutos) y cada
  clase abarca las filas de su duración real.
* Espacios: ocupación por franja de un nivel (varias clases pueden compartir celda).

Las franjas se reciben ya generadas para no depender del núcleo.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from timetabling.dominio.modelos import (
    DIAS_VALIDOS,
    Asignacion,
    DatosEscuela,
    Franja,
    Nivel,
    a_hhmm,
)

PASO_PROPORCIONAL = 5


@dataclass(frozen=True)
class FilaCuadricula:
    etiqueta: str
    inicio: int
    fin: int
    receso: str | None = None  # nombre del receso si es una fila de receso


@dataclass
class Bloque:
    fila: int
    filas: int
    columna: int
    titulo: str
    detalle: str
    color: str
    asignaciones: list[Asignacion] = field(default_factory=list)


@dataclass
class Cuadricula:
    titulo: str
    columnas: list[str]  # códigos de día
    filas: list[FilaCuadricula]
    bloques: list[Bloque]
    proporcional: bool = False


def _filas_de_nivel(
    nivel: Nivel, franjas: list[Franja]
) -> tuple[list[FilaCuadricula], dict[int, int]]:
    """Filas de franjas con recesos intercalados y mapa índice de franja → fila."""
    del_dia = sorted(
        (f for f in franjas if f.nivel_id == nivel.id and f.dia == nivel.dias[0]),
        key=lambda f: f.indice,
    )
    filas: list[FilaCuadricula] = []
    fila_de: dict[int, int] = {}
    anterior: Franja | None = None
    for franja in del_dia:
        if anterior is not None and anterior.fin < franja.inicio:
            receso = next(
                (r for r in nivel.recesos if r.inicio < franja.inicio and anterior.fin < r.fin),
                None,
            )
            filas.append(
                FilaCuadricula(
                    etiqueta=f"{a_hhmm(anterior.fin)}–{a_hhmm(franja.inicio)}",
                    inicio=anterior.fin,
                    fin=franja.inicio,
                    receso=receso.nombre if receso else "Receso",
                )
            )
        fila_de[franja.indice] = len(filas)
        filas.append(
            FilaCuadricula(
                etiqueta=f"{a_hhmm(franja.inicio)}–{a_hhmm(franja.fin)}",
                inicio=franja.inicio,
                fin=franja.fin,
            )
        )
        anterior = franja
    return filas, fila_de


def _ordenar_dias(dias: set[str]) -> list[str]:
    return sorted(dias, key=DIAS_VALIDOS.index)


def _bloques_por_franja(
    asignaciones: list[Asignacion],
    columnas: list[str],
    fila_de: dict[int, int],
    textos: dict[int, tuple[str, str, str]],
) -> list[Bloque]:
    """Un bloque por (día, franja); ``textos`` da (título, detalle, color) por asignación."""
    por_celda: dict[tuple[str, int], list[int]] = defaultdict(list)
    for i, a in enumerate(asignaciones):
        if a.dia in columnas and a.indice in fila_de:
            por_celda[(a.dia, a.indice)].append(i)
    bloques = []
    for (dia, indice), indices in por_celda.items():
        titulos = [textos[i] for i in indices]
        bloques.append(
            Bloque(
                fila=fila_de[indice],
                filas=1,
                columna=columnas.index(dia),
                titulo="\n".join(t[0] for t in titulos) if len(titulos) > 1 else titulos[0][0],
                detalle="" if len(titulos) > 1 else titulos[0][1],
                color=titulos[0][2] if len(titulos) == 1 else "#E0E0E0",
                asignaciones=[asignaciones[i] for i in indices],
            )
        )
    return bloques


def cuadricula_grupo(
    datos: DatosEscuela, franjas: list[Franja], asignaciones: list[Asignacion], grupo_id: int
) -> Cuadricula:
    grupo = datos.grupo(grupo_id)
    nivel = datos.nivel_de_grupo(grupo)
    filas, fila_de = _filas_de_nivel(nivel, franjas)
    propias = [a for a in asignaciones if a.grupo_id == grupo_id]
    nombres = {p.id: p.nombre for p in datos.profesores}
    textos = {}
    for i, a in enumerate(propias):
        asignatura = datos.asignatura(a.asignatura_id)
        textos[i] = (asignatura.nombre, nombres.get(a.profesor_id, "?"), asignatura.color)
    return Cuadricula(
        titulo=f"Grupo {datos.nombre_grupo(grupo)} · {nivel.nombre}",
        columnas=list(nivel.dias),
        filas=filas,
        bloques=_bloques_por_franja(propias, list(nivel.dias), fila_de, textos),
    )


def niveles_de_profesor(
    datos: DatosEscuela, asignaciones: list[Asignacion], profesor_id: int
) -> list[Nivel]:
    """Niveles en que el profesor da clase (o, si no tiene clases, los que atiende)."""
    ids = {a.nivel_id for a in asignaciones if a.profesor_id == profesor_id}
    if not ids:
        profesor = datos.profesor(profesor_id)
        ids = {datos.grado(g).nivel_id for g in profesor.grados}
    return [n for n in datos.niveles if n.id in ids]


def cuadricula_profesor(
    datos: DatosEscuela, franjas: list[Franja], asignaciones: list[Asignacion], profesor_id: int
) -> Cuadricula:
    profesor = datos.profesor(profesor_id)
    propias = [a for a in asignaciones if a.profesor_id == profesor_id]
    niveles = niveles_de_profesor(datos, asignaciones, profesor_id)
    textos = {}
    for i, a in enumerate(propias):
        asignatura = datos.asignatura(a.asignatura_id)
        textos[i] = (
            asignatura.nombre,
            datos.nombre_grupo(datos.grupo(a.grupo_id)),
            asignatura.color,
        )
    titulo = f"Profesor: {profesor.nombre}"
    if len(niveles) <= 1:
        if not niveles:
            return Cuadricula(titulo, [], [], [])
        nivel = niveles[0]
        filas, fila_de = _filas_de_nivel(nivel, franjas)
        return Cuadricula(
            titulo=f"{titulo} · {nivel.nombre}",
            columnas=list(nivel.dias),
            filas=filas,
            bloques=_bloques_por_franja(propias, list(nivel.dias), fila_de, textos),
        )

    # Varios niveles: escala de tiempo proporcional.
    ids = {n.id for n in niveles}
    relevantes = [f for f in franjas if f.nivel_id in ids]
    inicio = (min(f.inicio for f in relevantes) // PASO_PROPORCIONAL) * PASO_PROPORCIONAL
    fin = math.ceil(max(f.fin for f in relevantes) / PASO_PROPORCIONAL) * PASO_PROPORCIONAL
    filas = [
        FilaCuadricula(etiqueta=a_hhmm(t), inicio=t, fin=t + PASO_PROPORCIONAL)
        for t in range(inicio, fin, PASO_PROPORCIONAL)
    ]
    columnas = _ordenar_dias({d for n in niveles for d in n.dias})
    por_clave = {(f.nivel_id, f.dia, f.indice): f for f in relevantes}
    bloques = []
    for i, a in enumerate(propias):
        franja = por_clave.get((a.nivel_id, a.dia, a.indice))
        if franja is None or a.dia not in columnas:
            continue
        fila = (franja.inicio - inicio) // PASO_PROPORCIONAL
        ultima = math.ceil((franja.fin - inicio) / PASO_PROPORCIONAL)
        titulo_a, detalle, color = textos[i]
        bloques.append(
            Bloque(
                fila=fila,
                filas=max(1, ultima - fila),
                columna=columnas.index(a.dia),
                titulo=titulo_a,
                detalle=f"{detalle} · {a_hhmm(franja.inicio)}–{a_hhmm(franja.fin)}",
                color=color,
                asignaciones=[a],
            )
        )
    return Cuadricula(
        titulo=f"{titulo} · {', '.join(n.nombre for n in niveles)}",
        columnas=columnas,
        filas=filas,
        bloques=bloques,
        proporcional=True,
    )


def cuadricula_espacio(
    datos: DatosEscuela,
    franjas: list[Franja],
    asignaciones: list[Asignacion],
    tipo: str,
    nivel_id: int,
) -> Cuadricula:
    """Ocupación por franja de los espacios de ``tipo`` en un nivel."""
    nivel = datos.nivel(nivel_id)
    filas, fila_de = _filas_de_nivel(nivel, franjas)
    requieren = {a.id for a in datos.asignaturas if a.espacio_requerido == tipo}
    propias = [a for a in asignaciones if a.asignatura_id in requieren and a.nivel_id == nivel_id]
    textos = {}
    for i, a in enumerate(propias):
        asignatura = datos.asignatura(a.asignatura_id)
        textos[i] = (
            f"{datos.nombre_grupo(datos.grupo(a.grupo_id))} · {asignatura.nombre}",
            "",
            asignatura.color,
        )
    cantidad = datos.capacidad_espacios().get(tipo, 0)
    return Cuadricula(
        titulo=f"Espacio «{tipo}» ({cantidad}) · {nivel.nombre}",
        columnas=list(nivel.dias),
        filas=filas,
        bloques=_bloques_por_franja(propias, list(nivel.dias), fila_de, textos),
    )


def espacios_usados(datos: DatosEscuela) -> list[tuple[str, int]]:
    """Pares (tipo de espacio, nivel) que aparecen en el plan de estudios."""
    pares: set[tuple[str, int]] = set()
    for grupo in datos.grupos:
        nivel_id = datos.grado(grupo.grado_id).nivel_id
        for a in datos.plan_de_grado(grupo.grado_id):
            tipo = datos.asignatura(a).espacio_requerido
            if tipo:
                pares.add((tipo, nivel_id))
    orden = {n.id: i for i, n in enumerate(datos.niveles)}
    return sorted(pares, key=lambda p: (p[0], orden.get(p[1], 0)))
