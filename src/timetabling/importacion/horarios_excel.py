"""Creado con Claude. Importa asignaturas, grupos y plan de estudios desde un cuadro de horarios.

El cuadro es un libro de Excel con una hoja por grado («kinder», «Prepa», «1st» … «11th»).
En cada hoja, cada grupo es un bloque de columnas con los días (Monday … Friday) y, a su
izquierda, la columna de horas («8:00-8:40»). Encima del bloque va el nombre del grupo
(«1A», «PPB»…). Lo que viene después de «Horarios de Examen» se ignora.

De cada grupo se cuentan las sesiones semanales de cada asignatura. Los recesos (Lunch,
Snack, Playground, Recess) y las tutorías no cuentan. El plan de estudios es por grado,
así que cuando los grupos de un mismo grado difieren se toma el valor más frecuente (el
mayor si hay empate) y se avisa.

La importación se hace sobre un proyecto que ya tiene sus niveles y grados: no crea
niveles ni grados, solo asignaturas, grupos y filas del plan.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from timetabling.dominio.modelos import (
    NOMBRES_DIAS,
    Asignatura,
    DatosEscuela,
    Evento,
    Grado,
    Grupo,
    PlanEstudios,
    a_hhmm,
)
from timetabling.nucleo.franjas import generar_franjas_nivel
from timetabling.persistencia.repositorio import Repositorio

_DIAS = {"monday": "L", "tuesday": "M", "wednesday": "X", "thursday": "J", "friday": "V"}
_RECESOS = ("lunch", "snack", "playground", "recess", "receso", "recreo")
_FIN_TABLA = "examen"

# Nombre unificado de las asignaturas que aparecen escritas de varias formas.
_ALIAS = {
    "tecnologia": "Tecnología",
    "technology": "Tecnología",
    "tecnology": "Tecnología",
    "caracter": "Carácter",
    "character": "Carácter",
    "science lab": "Science Lab",
    "gym": "Gym",
    "values": "Values",
    "valores": "Values",
    # Variantes y errores de escritura del cuadro de maestros.
    "tecno": "Tecnología",
    "wiritng": "Writing",
    "sceince": "Science",
    "socales": "Sociales",
    "literatura": "Literature",
    "geografia": "Geography",
    "artistica": "Educacion Artistica",
    "algebra 1": "Algebra I",
    "algebra 2": "Algebra II",
}

# Nombre de la hoja → posibles nombres del grado en el proyecto.
_ORDINALES = [
    "primero",
    "segundo",
    "tercero",
    "cuarto",
    "quinto",
    "sexto",
    "septimo",
    "octavo",
    "noveno",
    "decimo",
    "undecimo",
]

_COLORES = [
    "#E57373", "#64B5F6", "#81C784", "#FFB74D", "#BA68C8", "#4DB6AC", "#F06292",
    "#A1887F", "#7986CB", "#AED581", "#FFD54F", "#4FC3F7", "#9575CD", "#FF8A65",
    "#90A4AE", "#DCE775", "#F48FB1", "#80CBC4", "#CE93D8", "#BCAAA4",
]  # fmt: skip


def clave(texto: str) -> str:
    """Forma comparable de un nombre: sin acentos, minúsculas y espacios simples."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_acentos.lower().split())


def es_tutoria(texto: str) -> bool:
    k = clave(texto)
    return k.startswith("tutoria") or "tutoring" in k


def es_receso(texto: str) -> bool:
    k = clave(texto)
    return any(palabra in k for palabra in _RECESOS)


def nombre_asignatura(texto: str) -> str:
    """Nombre limpio y unificado de una celda (ya descartados recesos y tutorías)."""
    limpio = " ".join(texto.split())
    return _ALIAS.get(clave(limpio), limpio)


def _a_minutos_12h(hora: str) -> int:
    """«1:10» → 13:10. El cuadro usa reloj de 12 h sin a. m./p. m.: antes de las 7 es tarde."""
    h, m = (int(x) for x in hora.split(":"))
    if h < 7:
        h += 12
    return h * 60 + m


def _rango(texto: object) -> tuple[int, int] | None:
    if not isinstance(texto, str):
        return None
    coincidencia = re.fullmatch(r"\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*", texto)
    if not coincidencia:
        return None
    return _a_minutos_12h(coincidencia[1]), _a_minutos_12h(coincidencia[2])


@dataclass
class Sesion:
    dia: str
    inicio: int
    fin: int
    asignatura: str


@dataclass
class GrupoLeido:
    seccion: str
    sesiones: list[Sesion] = field(default_factory=list)
    tutorias: int = 0

    def conteo(self) -> Counter[str]:
        return Counter(s.asignatura for s in self.sesiones)

    def maximo_diario(self) -> dict[str, int]:
        por_dia = Counter((s.asignatura, s.dia) for s in self.sesiones)
        maximo: dict[str, int] = defaultdict(int)
        for (asignatura, _), n in por_dia.items():
            maximo[asignatura] = max(maximo[asignatura], n)
        return maximo


@dataclass
class HojaLeida:
    hoja: str
    grupos: list[GrupoLeido]
    # Celdas vacías pintadas de celeste: la hora cívica (día, inicio, fin).
    eventos: set[tuple[str, int, int]] = field(default_factory=set)


def es_celeste(color: str | None) -> bool:
    """Relleno celeste/cian (``FF00FFFF``, ``FF66FFFF``…): poco rojo, mucho verde y azul."""
    if not color or not re.fullmatch(r"[0-9A-Fa-f]{8}", color):
        return False
    r, g, b = (int(color[i : i + 2], 16) for i in (2, 4, 6))
    return r < 0x80 and g >= 0xC0 and b >= 0xC0


def _texto(celda: object) -> str:
    return str(celda).strip() if celda is not None else ""


def leer_hoja(
    nombre: str, filas: list[list[object]], rellenos: list[list[str | None]] | None = None
) -> HojaLeida:
    """Interpreta una hoja del cuadro (ver el docstring del módulo). ``rellenos`` es el
    color de fondo (ARGB) de cada celda, para reconocer la hora cívica."""
    encabezado = next(
        (i for i, fila in enumerate(filas) if any(clave(_texto(c)) == "monday" for c in fila)),
        None,
    )
    if encabezado is None:
        return HojaLeida(nombre, [])
    fin = next(
        (
            i
            for i, fila in enumerate(filas)
            if i > encabezado and any(_FIN_TABLA in clave(_texto(c)) for c in fila)
        ),
        len(filas),
    )
    lunes = [j for j, c in enumerate(filas[encabezado]) if clave(_texto(c)) == "monday"]
    grupos = []
    eventos: set[tuple[str, int, int]] = set()
    for numero, j in enumerate(lunes):
        dias = {
            k: _DIAS[clave(_texto(filas[encabezado][k]))]
            for k in range(j, min(j + 5, len(filas[encabezado])))
            if clave(_texto(filas[encabezado][k])) in _DIAS
        }
        # Nombre del grupo: la primera celda con texto encima del bloque. Se usa su última
        # letra como sección («1A» → «A», «PPB» → «B»); si no hay, por orden (A, B, C…).
        etiqueta = ""
        for i in range(encabezado - 1, -1, -1):
            etiqueta = next((_texto(filas[i][k]) for k in dias if _texto(filas[i][k])), "")
            if etiqueta:
                break
        letra = re.search(r"([A-Za-z])\s*$", etiqueta) if len(lunes) > 1 else None
        seccion = letra[1].upper() if letra else chr(ord("A") + numero)
        grupo = GrupoLeido(seccion)
        for i_fila in range(encabezado + 1, fin):
            fila = filas[i_fila]
            rango = _rango(fila[j - 1]) if j > 0 else None
            if rango is None:
                continue
            for k, dia in dias.items():
                texto = _texto(fila[k]) if k < len(fila) else ""
                if not texto and rellenos is not None:
                    colores = rellenos[i_fila] if i_fila < len(rellenos) else []
                    if k < len(colores) and es_celeste(colores[k]):
                        eventos.add((dia, *rango))
                if not texto or es_receso(texto):
                    continue
                if es_tutoria(texto):
                    grupo.tutorias += 1
                    continue
                grupo.sesiones.append(Sesion(dia, *rango, nombre_asignatura(texto)))
        grupos.append(grupo)
    return HojaLeida(nombre, grupos, eventos)


def _color(celda: object) -> str | None:
    relleno = getattr(celda, "fill", None)
    if relleno is None or not relleno.fill_type:
        return None
    color = relleno.fgColor
    return color.rgb if color is not None and color.type == "rgb" else None


def leer_libro(ruta: str | Path) -> list[HojaLeida]:
    libro = openpyxl.load_workbook(ruta, data_only=True)
    try:
        hojas = []
        for hoja in libro.worksheets:
            celdas = [list(f) for f in hoja.iter_rows()]
            hojas.append(
                leer_hoja(
                    hoja.title,
                    [[c.value for c in f] for f in celdas],
                    [[_color(c) for c in f] for f in celdas],
                )
            )
        return hojas
    finally:
        libro.close()


def nombres_grado(hoja: str) -> set[str]:
    """Claves con las que puede llamarse en el proyecto el grado de una hoja."""
    k = clave(hoja)
    numero = re.match(r"(\d+)", k)
    if numero:
        n = int(numero[1])
        nombres = {str(n), f"{n}o", f"{n}.o", f"{n}º", f"{n}.º", k}
        if 1 <= n <= len(_ORDINALES):
            nombres.add(_ORDINALES[n - 1])
        return nombres
    return {k}


@dataclass
class Informe:
    asignaturas_nuevas: list[str] = field(default_factory=list)
    asignaturas_renombradas: list[tuple[str, str]] = field(default_factory=list)
    grupos_nuevos: list[str] = field(default_factory=list)
    filas_plan: int = 0
    tutorias_omitidas: int = 0
    eventos_nuevos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _plan_grado(
    grado: Grado, hoja: HojaLeida, informe: Informe
) -> tuple[dict[str, int], dict[str, int]]:
    """Sesiones semanales y máximo diario por asignatura para un grado."""
    conteos = [g.conteo() for g in hoja.grupos]
    asignaturas = sorted(set().union(*conteos))
    plan: dict[str, int] = {}
    for asignatura in asignaturas:
        valores = [c.get(asignatura, 0) for c in conteos]
        frecuencia = Counter(valores).most_common()
        mayor_frecuencia = frecuencia[0][1]
        plan[asignatura] = max(v for v, n in frecuencia if n == mayor_frecuencia)
        if len(set(valores)) > 1:
            detalle = ", ".join(
                f"{g.seccion}={v}" for g, v in zip(hoja.grupos, valores, strict=True)
            )
            informe.avisos.append(
                f"{grado.nombre}: los grupos difieren en {asignatura} ({detalle}); "
                f"se usó {plan[asignatura]}"
            )
    maximo: dict[str, int] = defaultdict(int)
    for g in hoja.grupos:
        for asignatura, n in g.maximo_diario().items():
            maximo[asignatura] = max(maximo[asignatura], n)
    return {a: h for a, h in plan.items() if h > 0}, maximo


def _revisar_horas(datos: DatosEscuela, grado: Grado, hoja: HojaLeida, informe: Informe) -> None:
    """Avisa si alguna clase del cuadro no coincide con una franja del nivel del grado."""
    nivel = datos.nivel(grado.nivel_id)
    franjas = {(f.dia, f.inicio, f.fin) for f in generar_franjas_nivel(nivel)}
    fuera = sorted(
        {
            (s.inicio, s.fin)
            for g in hoja.grupos
            for s in g.sesiones
            if (s.dia, s.inicio, s.fin) not in franjas
        }
    )
    if fuera:
        horas = ", ".join(f"{a_hhmm(i)}-{a_hhmm(f)}" for i, f in fuera)
        informe.avisos.append(
            f"{grado.nombre}: el cuadro tiene clases en horas que no son franjas del nivel "
            f"«{nivel.nombre}» ({horas})"
        )


def importar(repo: Repositorio, hojas: list[HojaLeida]) -> Informe:
    """Crea o actualiza asignaturas, grupos y plan de estudios en el proyecto abierto."""
    informe = Informe()
    datos = repo.cargar_datos()
    grados_por_nombre = {clave(g.nombre): g for g in datos.grados}

    emparejadas: list[tuple[Grado, HojaLeida]] = []
    for hoja in hojas:
        if not any(g.sesiones for g in hoja.grupos):
            continue
        grado = next(
            (grados_por_nombre[n] for n in nombres_grado(hoja.hoja) if n in grados_por_nombre),
            None,
        )
        if grado is None:
            informe.avisos.append(
                f"Hoja «{hoja.hoja}»: no hay un grado con ese nombre en el proyecto; se omitió"
            )
            continue
        emparejadas.append((grado, hoja))
        informe.tutorias_omitidas += sum(g.tutorias for g in hoja.grupos)

    planes = {grado.id: _plan_grado(grado, hoja, informe) for grado, hoja in emparejadas}

    # Asignaturas: se reutilizan las existentes (comparando sin acentos ni mayúsculas) y se
    # renombran a la forma unificada; las que faltan se crean.
    existentes = {clave(a.nombre): a for a in datos.asignaturas}
    maximo_global: dict[str, int] = defaultdict(int)
    for _, maximo in planes.values():
        for nombre, n in maximo.items():
            maximo_global[nombre] = max(maximo_global[nombre], n)
    ids: dict[str, int] = {}
    colores_usados = {a.color for a in datos.asignaturas}
    libres = [c for c in _COLORES if c not in colores_usados] or _COLORES
    for nombre in sorted(maximo_global):
        actual = existentes.get(clave(nombre))
        maximo = maximo_global[nombre]
        if actual is None:
            nueva = Asignatura(
                nombre=nombre,
                max_horas_dia=max(maximo, 1),
                color=libres[len(informe.asignaturas_nuevas) % len(libres)],
            )
            actual = repo.guardar_asignatura(nueva)
            informe.asignaturas_nuevas.append(nombre)
        else:
            cambios: dict[str, object] = {}
            if actual.nombre != nombre:
                informe.asignaturas_renombradas.append((actual.nombre, nombre))
                cambios["nombre"] = nombre
            if maximo > actual.max_horas_dia:
                informe.avisos.append(
                    f"{nombre}: el cuadro tiene hasta {maximo} sesiones en un día; se subió "
                    f"el máximo diario de {actual.max_horas_dia} a {maximo}"
                )
                cambios["max_horas_dia"] = maximo
            if cambios:
                actual = repo.guardar_asignatura(actual.model_copy(update=cambios))
        assert actual.id is not None
        ids[nombre] = actual.id

    # Grupos y plan.
    grupos_existentes = {(g.grado_id, clave(g.seccion)) for g in datos.grupos}
    plan_existente: dict[int, set[int]] = defaultdict(set)
    for item in datos.plan:
        plan_existente[item.grado_id].add(item.asignatura_id)
    for grado, hoja in emparejadas:
        assert grado.id is not None
        for g in hoja.grupos:
            if (grado.id, clave(g.seccion)) not in grupos_existentes:
                repo.guardar_grupo(Grupo(grado_id=grado.id, seccion=g.seccion))
                grupos_existentes.add((grado.id, clave(g.seccion)))
                informe.grupos_nuevos.append(f"{grado.nombre} {g.seccion}")
        plan, _ = planes[grado.id]
        for nombre, horas in plan.items():
            repo.guardar_plan(
                PlanEstudios(grado_id=grado.id, asignatura_id=ids[nombre], horas_semanales=horas)
            )
            informe.filas_plan += 1
        # Lo que estaba en el plan del grado y ya no aparece en el cuadro se quita.
        for asignatura_id in plan_existente[grado.id] - {ids[n] for n in plan}:
            repo.guardar_plan(
                PlanEstudios(grado_id=grado.id, asignatura_id=asignatura_id, horas_semanales=0)
            )
        _revisar_horas(datos, grado, hoja, informe)
    _importar_eventos(repo, emparejadas, informe)
    informe.avisos.extend(asistencia_por_defecto(repo))
    return informe


def _importar_eventos(
    repo: Repositorio, emparejadas: list[tuple[Grado, HojaLeida]], informe: Informe
) -> None:
    """Crea en cada nivel los eventos (hora cívica) marcados en sus hojas, si no existen."""
    por_nivel: dict[int, set[tuple[str, int, int]]] = defaultdict(set)
    for grado, hoja in emparejadas:
        por_nivel[grado.nivel_id] |= hoja.eventos
    for nivel in repo.listar_niveles():
        nuevos = [
            Evento(dia=dia, inicio=inicio, fin=fin)
            for dia, inicio, fin in sorted(por_nivel.get(nivel.id, set()))  # type: ignore[arg-type]
            if not any(e.toca(dia, inicio, fin) for e in nivel.eventos)
        ]
        if not nuevos:
            continue
        repo.guardar_nivel(nivel.model_copy(update={"eventos": [*nivel.eventos, *nuevos]}))
        for e in nuevos:
            informe.eventos_nuevos.append(
                f"{e.nombre} · {nivel.nombre}: {NOMBRES_DIAS[e.dia]} {a_hhmm(e.inicio)}–"
                f"{a_hhmm(e.fin)}"
            )


def asistencia_por_defecto(repo: Repositorio) -> list[str]:
    """Los profesores que dan clase en un solo nivel asisten a todos los eventos de ese
    nivel (se agregan, nunca se quitan). Devuelve avisos con los que dan clase en varios
    niveles con eventos, que deben elegir a mano en «Profesores»."""
    datos = repo.cargar_datos()
    avisos = []
    for profesor in datos.profesores:
        niveles = datos.niveles_de(profesor)
        con_eventos = [n for n in datos.niveles if n.id in niveles and n.eventos]
        if len(niveles) == 1 and con_eventos:
            ids = {e.id for e in con_eventos[0].eventos if e.id is not None}
            if not ids <= profesor.eventos:
                repo.guardar_profesor(
                    profesor.model_copy(update={"eventos": profesor.eventos | ids})
                )
        elif len(con_eventos) > 1 or (len(niveles) > 1 and con_eventos):
            ya = [
                e.nombre + " · " + n.nombre
                for n in con_eventos
                for e in n.eventos
                if e.id in profesor.eventos
            ]
            elegidos = ", ".join(ya) if ya else "ninguno"
            avisos.append(
                f"{profesor.nombre} da clase en "
                f"{', '.join(n.nombre for n in datos.niveles if n.id in niveles)}: elija en "
                f"«Profesores» a qué horas cívicas asiste (ahora: {elegidos})"
            )
    return avisos


def importar_archivo(proyecto: str | Path, excel: str | Path) -> Informe:
    hojas = leer_libro(excel)
    with Repositorio.abrir(proyecto) as repo:
        return importar(repo, hojas)
