"""Creado con Claude. Importa profesores y su asignación por grupo desde el cuadro de maestros.

El cuadro es un libro de Excel con bloques de horario, uno por maestro: una fila con los
días (Monday … Friday) y, justo encima, el nombre del maestro. Cada celda dice qué da en
esa hora: «ESPAÑOL 3A», «Grammar 10B», «Math PPA»… A veces solo trae el grupo
(«8A (8:00-8:45)»); entonces se usa la asignatura que más da ese maestro. Las celdas sin
grupo se asignan al único grado de un solo grupo que tenga esa asignatura (el Kinder).

De ahí salen, para cada maestro, sus asignaturas, sus grados y qué asignatura da a cada
grupo (el «profesor por grupo» que respeta el generador). Los horarios del cuadro no se
importan: el generador los vuelve a calcular.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from timetabling.dominio.modelos import (
    DIAS_SEMANA,
    DatosEscuela,
    Disponibilidad,
    DocenteAsignado,
    Grupo,
    Profesor,
    a_minutos,
)
from timetabling.importacion.horarios_excel import (
    asistencia_por_defecto,
    clave,
    es_receso,
    es_tutoria,
    nombre_asignatura,
    nombres_grado,
)
from timetabling.persistencia.repositorio import Repositorio

_GRUPO = re.compile(r"(?<!\d)(PP\s*[AB]|1[01]\s*[A-C]|[1-9]\s*[A-C])(?![A-Za-z0-9])", re.I)
_HORAS = re.compile(r"\(?\s*\d{1,2}\s*[:_-]\s*\d{0,2}[^A-Za-z]*\)?")
_TITULO = re.compile(r"^\s*(mrs|mr|ms|miss)\.?\s*", re.I)
_TITULOS = {"mrs": "Mrs.", "mr": "Mr.", "ms": "Ms.", "miss": "Miss"}
_SIN_PROFESOR = ("biblioteca",)

# Jornada por defecto de los maestros nuevos (el cuadro no dice su disponibilidad).
INICIO_DISPONIBLE = a_minutos("07:00")
FIN_DISPONIBLE = a_minutos("16:00")


def _texto(celda: object) -> str:
    return " ".join(str(celda).split()) if celda is not None else ""


def nombre_maestro(texto: str) -> str:
    """«MS. MINSY» y «Ms.Minsy» → «Ms. Minsy»."""
    titulo = _TITULO.match(texto)
    resto = texto[titulo.end() :] if titulo else texto
    nombre = " ".join(p.capitalize() for p in resto.split())
    if titulo:
        return f"{_TITULOS[titulo[1].lower()]} {nombre}"
    return nombre


def clave_maestro(texto: str) -> str:
    return clave(_TITULO.sub("", texto))


@dataclass
class Celda:
    texto: str
    asignatura: str | None  # None si la celda solo trae el grupo
    grupos: list[str]  # «PPA», «3B», «10A»…


@dataclass
class BloqueMaestro:
    nombre: str
    celdas: list[Celda] = field(default_factory=list)
    otras: list[str] = field(default_factory=list)  # actividades que no son clase


def leer_celda(texto: str) -> Celda | None:
    """Interpreta una celda; ``None`` si es receso o está vacía."""
    if not texto or es_receso(texto):
        return None
    grupos = [re.sub(r"\s+", "", g).upper() for g in _GRUPO.findall(texto)]
    resto = _GRUPO.sub(" ", texto)
    resto = _HORAS.sub(" ", resto)
    resto = re.sub(r"[(),]", " ", resto)
    resto = " ".join(resto.split()).strip(" -/")
    return Celda(texto, nombre_asignatura(resto) if resto else None, grupos)


def leer_hoja(filas: list[list[object]]) -> list[BloqueMaestro]:
    bloques: list[BloqueMaestro] = []
    ancho = max((len(f) for f in filas), default=0)
    filas = [list(f) + [None] * (ancho - len(f)) for f in filas]

    def es_encabezado(i: int, j: int) -> bool:
        return 0 <= i < len(filas) and any(
            clave(_texto(filas[i][k])) == "monday" for k in range(j, min(j + 5, ancho))
        )

    for i, fila in enumerate(filas):
        for j, celda in enumerate(fila):
            if clave(_texto(celda)) != "monday":
                continue
            columnas = range(j, min(j + 5, ancho))
            nombre = ""
            for arriba in (i - 1, i - 2):
                if arriba >= 0:
                    nombre = next(
                        (_texto(filas[arriba][k]) for k in columnas if _texto(filas[arriba][k])), ""
                    )
                if nombre:
                    break
            bloque = BloqueMaestro(nombre)
            for k in range(i + 1, len(filas)):
                # Termina donde empieza el siguiente bloque (su nombre va una fila arriba).
                if es_encabezado(k, j) or es_encabezado(k + 1, j):
                    break
                for c in columnas:
                    texto = _texto(filas[k][c])
                    leida = leer_celda(texto)
                    if leida is None:
                        continue
                    if leida.grupos or (leida.asignatura and not es_tutoria(texto)):
                        if es_tutoria(texto):
                            bloque.otras.append(texto)
                        else:
                            bloque.celdas.append(leida)
                    else:
                        bloque.otras.append(texto)
            bloques.append(bloque)
    return bloques


def leer_libro(ruta: str | Path) -> list[BloqueMaestro]:
    libro = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    try:
        return [
            b
            for hoja in libro.worksheets
            for b in leer_hoja([list(f) for f in hoja.iter_rows(values_only=True)])
        ]
    finally:
        libro.close()


@dataclass
class Informe:
    profesores_nuevos: list[str] = field(default_factory=list)
    profesores_actualizados: list[str] = field(default_factory=list)
    asignaciones: int = 0
    avisos: list[str] = field(default_factory=list)


class _Resolutor:
    """Traduce grupos y asignaturas del cuadro a ids del proyecto."""

    def __init__(self, datos: DatosEscuela) -> None:
        self.datos = datos
        self.grados = {clave(g.nombre): g for g in datos.grados}
        self.asignaturas = {clave(a.nombre): a for a in datos.asignaturas}
        por_grado: dict[int, list[Grupo]] = defaultdict(list)
        for g in datos.grupos:
            por_grado[g.grado_id].append(g)
        self.unicos = [gs[0] for gs in por_grado.values() if len(gs) == 1]

    def grupo(self, token: str) -> Grupo | None:
        numero, seccion = token[:-1], token[-1]
        hoja = "prepa" if numero == "PP" else numero
        grado = next((self.grados[n] for n in nombres_grado(hoja) if n in self.grados), None)
        if grado is None:
            return None
        return next(
            (
                g
                for g in self.datos.grupos
                if g.grado_id == grado.id and clave(g.seccion) == seccion.lower()
            ),
            None,
        )

    def asignatura(self, nombre: str) -> int | None:
        a = self.asignaturas.get(clave(nombre))
        return a.id if a else None

    def grupo_sin_letra(self, asignatura_id: int) -> Grupo | None:
        """El único grupo de un grado de un solo grupo que tiene esa asignatura."""
        candidatos = [
            g for g in self.unicos if asignatura_id in self.datos.plan_de_grado(g.grado_id)
        ]
        return candidatos[0] if len(candidatos) == 1 else None


def importar(repo: Repositorio, bloques: list[BloqueMaestro]) -> Informe:
    informe = Informe()
    datos = repo.cargar_datos()
    r = _Resolutor(datos)

    # (clave del maestro) → nombre y sesiones por (grupo, asignatura).
    nombres: dict[str, str] = {}
    sesiones: dict[str, Counter[tuple[int, int]]] = defaultdict(Counter)
    no_resueltas: Counter[str] = Counter()
    otras: Counter[str] = Counter()
    solo_grupo: dict[str, Counter[str]] = defaultdict(Counter)  # maestro → grupo → sesiones
    sin_grupo: dict[str, Counter[int]] = defaultdict(Counter)  # maestro → asignatura → sesiones
    for bloque in bloques:
        if not bloque.nombre or any(p in clave(bloque.nombre) for p in _SIN_PROFESOR):
            continue
        if not bloque.celdas:
            continue
        k = clave_maestro(bloque.nombre)
        nombres.setdefault(k, nombre_maestro(bloque.nombre))
        conocidas = Counter(c.asignatura for c in bloque.celdas if c.asignatura and c.grupos)
        principal = conocidas.most_common(1)[0][0] if conocidas else None
        for texto in bloque.otras:
            if not es_tutoria(texto):
                otras[f"{nombres[k]}: {texto}"] += 1
        for celda in bloque.celdas:
            asignatura = celda.asignatura or principal
            if asignatura is None:
                for token in celda.grupos:
                    solo_grupo[k][token] += 1
                continue
            asignatura_id = r.asignatura(asignatura)
            if asignatura_id is None:
                if celda.grupos:
                    no_resueltas[f"{nombres[k]}: «{celda.texto}»"] += 1
                else:
                    otras[f"{nombres[k]}: {celda.texto}"] += 1
                continue
            if celda.grupos:
                grupos = [r.grupo(t) for t in celda.grupos]
            else:
                grupos = [r.grupo_sin_letra(asignatura_id)]
            for token, grupo in zip(celda.grupos or ["?"], grupos, strict=True):
                if grupo is None or grupo.id is None:
                    if celda.grupos:
                        no_resueltas[f"{nombres[k]}: «{celda.texto}» (grupo {token})"] += 1
                    else:
                        sin_grupo[k][asignatura_id] += 1
                    continue
                if asignatura_id not in datos.plan_de_grado(grupo.grado_id):
                    no_resueltas[
                        f"{nombres[k]}: «{celda.texto}» ({datos.asignatura(asignatura_id).nombre}"
                        f" no está en el plan de {datos.grado(grupo.grado_id).nombre})"
                    ] += 1
                    continue
                sesiones[k][(grupo.id, asignatura_id)] += 1

    # Celdas con solo el grupo y sin ninguna asignatura conocida del maestro: se deduce la
    # asignatura si en ese grupo hay exactamente una con esas horas y sin maestro.
    cubiertas = {c for conteo in sesiones.values() for c in conteo}
    for k, por_grupo in solo_grupo.items():
        for token, n in sorted(por_grupo.items()):
            grupo = r.grupo(token)
            opciones = (
                [
                    a
                    for a, h in datos.plan_de_grado(grupo.grado_id).items()
                    if h == n and (grupo.id, a) not in cubiertas
                ]
                if grupo is not None and grupo.id is not None
                else []
            )
            if grupo is None or grupo.id is None or len(opciones) != 1:
                no_resueltas[f"{nombres[k]}: «{token}» sin asignatura"] += n
                continue
            sesiones[k][(grupo.id, opciones[0])] += n
            cubiertas.add((grupo.id, opciones[0]))
            informe.avisos.append(
                f"{nombres[k]} solo anota el grupo {token}: se dedujo que da "
                f"{datos.asignatura(opciones[0]).nombre} (la única de {n} h/semana sin maestro)"
            )

    # Celdas con la asignatura pero sin grupo: si los grupos sin maestro que tienen esas
    # horas son todos del mismo grado, se habilita al maestro en ese grado sin fijarle grupo
    # (el generador elige cuál le toca).
    habilitar: dict[str, set[tuple[int, int]]] = defaultdict(set)  # maestro → (asig., grado)
    for k, por_asignatura in sin_grupo.items():
        for asignatura_id, n in sorted(por_asignatura.items()):
            nombre = datos.asignatura(asignatura_id).nombre
            grupos_libres = [
                g
                for g in datos.grupos
                if datos.plan_de_grado(g.grado_id).get(asignatura_id) == n
                and (g.id, asignatura_id) not in cubiertas
            ]
            grados = {g.grado_id for g in grupos_libres}
            if len(grados) != 1:
                no_resueltas[f"{nombres[k]}: «{nombre}» sin grupo"] += n
                continue
            grado_id = grados.pop()
            habilitar[k].add((asignatura_id, grado_id))
            opciones = " o ".join(datos.nombre_grupo(g) for g in grupos_libres)
            informe.avisos.append(
                f"{nombres[k]} anota {n} h de {nombre} sin grupo: se habilitó para {nombre} en "
                f"{datos.grado(grado_id).nombre} ({opciones}); fije el grupo en «Profesores por "
                "grupo» o deje que el generador elija"
            )

    # Cada (grupo, asignatura) queda con el maestro que más sesiones da de ella.
    candidatos: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)
    for k, conteo in sesiones.items():
        for clase, n in conteo.items():
            candidatos[clase].append((n, k))
    elegido: dict[tuple[int, int], str] = {}
    for clase, lista in candidatos.items():
        lista.sort(key=lambda t: (-t[0], nombres[t[1]]))
        elegido[clase] = lista[0][1]
        if len(lista) > 1:
            grupo, asignatura = datos.grupo(clase[0]), datos.asignatura(clase[1])
            detalle = ", ".join(f"{nombres[m]} ({n})" for n, m in lista)
            informe.avisos.append(
                f"{asignatura.nombre} en {datos.nombre_grupo(grupo)} la dan varios maestros "
                f"({detalle}); se asignó a {nombres[lista[0][1]]}"
            )

    # Profesores: se crean o se completan (sin quitar lo que ya tenían).
    existentes = {clave_maestro(p.nombre): p for p in datos.profesores}
    ids: dict[str, int] = {}
    for k in sorted(set(sesiones) | set(habilitar), key=lambda m: nombres[m]):
        clases = [c for c in sesiones[k] if elegido.get(c) == k] or list(sesiones[k])
        asignaturas = {a for _, a in clases} | {a for a, _ in habilitar[k]}
        grados = {datos.grupo(g).grado_id for g, _ in clases} | {g for _, g in habilitar[k]}
        actual = existentes.get(k)
        if actual is None:
            nuevo = Profesor(
                nombre=nombres[k],
                asignaturas=asignaturas,
                grados=grados,
                disponibilidad=[
                    Disponibilidad(dia=d, inicio=INICIO_DISPONIBLE, fin=FIN_DISPONIBLE)
                    for d in DIAS_SEMANA
                ],
            )
            actual = repo.guardar_profesor(nuevo)
            informe.profesores_nuevos.append(nombres[k])
        elif not (asignaturas <= actual.asignaturas and grados <= actual.grados):
            actual = repo.guardar_profesor(
                actual.model_copy(
                    update={
                        "asignaturas": actual.asignaturas | asignaturas,
                        "grados": actual.grados | grados,
                    }
                )
            )
            informe.profesores_actualizados.append(actual.nombre)
        assert actual.id is not None
        ids[k] = actual.id

    for (grupo_id, asignatura_id), k in sorted(elegido.items()):
        repo.asignar_docente(
            DocenteAsignado(grupo_id=grupo_id, asignatura_id=asignatura_id, profesor_id=ids[k])
        )
        informe.asignaciones += 1

    # Comparación con el plan de estudios.
    for grupo in sorted(datos.grupos, key=lambda g: (g.grado_id, g.seccion)):
        assert grupo.id is not None
        for asignatura_id, horas in datos.plan_de_grado(grupo.grado_id).items():
            k = elegido.get((grupo.id, asignatura_id))
            nombre = f"{datos.asignatura(asignatura_id).nombre} en {datos.nombre_grupo(grupo)}"
            if k is None:
                if not any((asignatura_id, grupo.grado_id) in h for h in habilitar.values()):
                    informe.avisos.append(f"{nombre}: ningún maestro la tiene en el cuadro")
                continue
            dadas = sum(sesiones[m][(grupo.id, asignatura_id)] for m in sesiones)
            if dadas != horas:
                informe.avisos.append(
                    f"{nombre}: el plan pide {horas} h/semana y el cuadro de maestros tiene {dadas}"
                )
    for texto, n in sorted(no_resueltas.items()):
        veces = f" ({n} veces)" if n > 1 else ""
        informe.avisos.append(f"Celda no reconocida — {texto}{veces}")
    for texto, n in sorted(otras.items()):
        veces = f" ({n} veces)" if n > 1 else ""
        informe.avisos.append(f"Actividad que no es clase (se omitió) — {texto}{veces}")
    informe.avisos.extend(asistencia_por_defecto(repo))
    return informe


def importar_archivo(proyecto: str | Path, excel: str | Path) -> Informe:
    bloques = leer_libro(excel)
    with Repositorio.abrir(proyecto) as repo:
        return importar(repo, bloques)
