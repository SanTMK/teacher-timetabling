"""Creado con Claude. Revisión independiente de una solución contra las restricciones duras.

No reutiliza las estructuras del modelo CP-SAT: trabaja directamente con los datos
del dominio y la lista de ``Asignacion``, con cálculos propios de horas y traslapes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from timetabling.dominio.modelos import Asignacion, DatosEscuela, Franja, a_hhmm
from timetabling.nucleo.franjas import generar_franjas_nivel


@dataclass(frozen=True)
class Violacion:
    codigo: str  # "D1" … "D13"
    mensaje: str

    def __str__(self) -> str:
        return f"[{self.codigo}] {self.mensaje}"


class _Contexto:
    def __init__(self, datos: DatosEscuela, asignaciones: list[Asignacion]) -> None:
        self.datos = datos
        self.asignaciones = asignaciones
        self.franjas: dict[tuple[int, str, int], Franja] = {}
        for nivel in datos.niveles:
            for f in generar_franjas_nivel(nivel):
                self.franjas[(f.nivel_id, f.dia, f.indice)] = f
        self.grupos = {g.id: g for g in datos.grupos}
        self.grados = {g.id: g for g in datos.grados}
        self.asignaturas = {a.id: a for a in datos.asignaturas}
        self.profesores = {p.id: p for p in datos.profesores}
        self.niveles = {n.id: n for n in datos.niveles}

    def franja(self, a: Asignacion) -> Franja | None:
        return self.franjas.get((a.nivel_id, a.dia, a.indice))

    def nombre_grupo(self, grupo_id: int) -> str:
        grupo = self.grupos.get(grupo_id)
        if grupo is None:
            return f"grupo {grupo_id}"
        return f"{self.grados[grupo.grado_id].nombre}{grupo.seccion}"

    def nombre_asig(self, asignatura_id: int) -> str:
        a = self.asignaturas.get(asignatura_id)
        return a.nombre if a else f"asignatura {asignatura_id}"

    def nombre_prof(self, profesor_id: int) -> str:
        p = self.profesores.get(profesor_id)
        return p.nombre if p else f"profesor {profesor_id}"

    def describir(self, a: Asignacion) -> str:
        f = self.franja(a)
        hora = f"{a_hhmm(f.inicio)}-{a_hhmm(f.fin)}" if f else f"franja {a.indice}"
        return (
            f"{self.nombre_asig(a.asignatura_id)} con {self.nombre_prof(a.profesor_id)} "
            f"en {self.nombre_grupo(a.grupo_id)} el {a.dia} {hora}"
        )


def verificar(datos: DatosEscuela, asignaciones: list[Asignacion]) -> list[Violacion]:
    """Devuelve la lista de violaciones (vacía si la solución cumple todo)."""
    cx = _Contexto(datos, asignaciones)
    violaciones: list[Violacion] = []
    for revision in (
        _referencias,
        _d1_curricular,
        _d2_un_maestro,
        _d3_un_lugar,
        _d4_competencia,
        _d5_disponibilidad,
        _d6_continuidad,
        _d7_carga,
        _d8_consecutivas,
        _d9_espacios,
        _d10_maximo_diario,
        _d11_bloque_doble,
        _d12_sin_huecos,
        _d13_fijas,
    ):
        violaciones.extend(revision(cx))
    return violaciones


def _referencias(cx: _Contexto) -> list[Violacion]:
    """Cada asignación apunta a entidades existentes y a una franja del nivel del grupo."""
    v: list[Violacion] = []
    for a in cx.asignaciones:
        grupo = cx.grupos.get(a.grupo_id)
        if (
            grupo is None
            or a.asignatura_id not in cx.asignaturas
            or a.profesor_id not in cx.profesores
        ):
            v.append(Violacion("D1", f"Asignación con referencias inexistentes: {a}"))
            continue
        if cx.grados[grupo.grado_id].nivel_id != a.nivel_id or cx.franja(a) is None:
            v.append(Violacion("D1", f"Franja inexistente para el grupo: {cx.describir(a)}"))
    return v


def _d1_curricular(cx: _Contexto) -> list[Violacion]:
    impartidas = Counter((a.grupo_id, a.asignatura_id) for a in cx.asignaciones)
    v: list[Violacion] = []
    exigidas: dict[tuple[int, int], int] = {}
    for grupo in cx.datos.grupos:
        for item in cx.datos.plan:
            if item.grado_id == grupo.grado_id and item.horas_semanales > 0:
                exigidas[(grupo.id, item.asignatura_id)] = item.horas_semanales
    for clave in set(exigidas) | set(impartidas):
        if exigidas.get(clave, 0) != impartidas.get(clave, 0):
            g, a = clave
            v.append(
                Violacion(
                    "D1",
                    f"{cx.nombre_asig(a)} en {cx.nombre_grupo(g)}: {impartidas.get(clave, 0)} "
                    f"horas asignadas de {exigidas.get(clave, 0)} exigidas",
                )
            )
    return v


def _d2_un_maestro(cx: _Contexto) -> list[Violacion]:
    cuenta = Counter((a.grupo_id, a.nivel_id, a.dia, a.indice) for a in cx.asignaciones)
    return [
        Violacion("D2", f"{cx.nombre_grupo(g)} tiene {n} clases el {d} en la franja {i + 1}")
        for (g, _n, d, i), n in cuenta.items()
        if n > 1
    ]


def _d3_un_lugar(cx: _Contexto) -> list[Violacion]:
    margen = cx.datos.configuracion.margen_traslado_min
    por_prof_dia: dict[tuple[int, str], list[Asignacion]] = defaultdict(list)
    for a in cx.asignaciones:
        por_prof_dia[(a.profesor_id, a.dia)].append(a)
    v: list[Violacion] = []
    for clases in por_prof_dia.values():
        for i, a in enumerate(clases):
            fa = cx.franja(a)
            for b in clases[i + 1 :]:
                fb = cx.franja(b)
                if fa is None or fb is None:
                    continue
                m = margen if a.nivel_id != b.nivel_id else 0
                if fa.inicio < fb.fin + m and fb.inicio < fa.fin + m:
                    v.append(Violacion("D3", f"Choque: {cx.describir(a)} y {cx.describir(b)}"))
    return v


def _d4_competencia(cx: _Contexto) -> list[Violacion]:
    v: list[Violacion] = []
    for a in cx.asignaciones:
        p = cx.profesores.get(a.profesor_id)
        grupo = cx.grupos.get(a.grupo_id)
        if p is None or grupo is None:
            continue
        if a.asignatura_id not in p.asignaturas or grupo.grado_id not in p.grados:
            v.append(Violacion("D4", f"Profesor no habilitado: {cx.describir(a)}"))
    return v


def _d5_disponibilidad(cx: _Contexto) -> list[Violacion]:
    v: list[Violacion] = []
    for a in cx.asignaciones:
        p = cx.profesores.get(a.profesor_id)
        f = cx.franja(a)
        if p is None or f is None:
            continue
        minutos_libres: set[int] = set()
        for d in p.disponibilidad:
            if d.dia == a.dia:
                minutos_libres.update(range(d.inicio, d.fin))
        if not set(range(f.inicio, f.fin)) <= minutos_libres:
            v.append(Violacion("D5", f"Fuera de la disponibilidad: {cx.describir(a)}"))
    return v


def _d6_continuidad(cx: _Contexto) -> list[Violacion]:
    profesores: dict[tuple[int, int], set[int]] = defaultdict(set)
    for a in cx.asignaciones:
        profesores[(a.grupo_id, a.asignatura_id)].add(a.profesor_id)
    return [
        Violacion(
            "D6",
            f"{cx.nombre_asig(asig)} en {cx.nombre_grupo(g)} la imparten {len(ps)} profesores",
        )
        for (g, asig), ps in profesores.items()
        if len(ps) > 1
    ]


def _d7_carga(cx: _Contexto) -> list[Violacion]:
    semanal: Counter[int] = Counter()
    diaria: Counter[tuple[int, str]] = Counter()
    for a in cx.asignaciones:
        f = cx.franja(a)
        if f is None:
            continue
        semanal[a.profesor_id] += f.fin - f.inicio
        diaria[(a.profesor_id, a.dia)] += f.fin - f.inicio
    v: list[Violacion] = []
    for p_id, minutos in semanal.items():
        p = cx.profesores.get(p_id)
        if p and minutos > p.carga_max_semanal_min:
            v.append(
                Violacion("D7", f"{p.nombre}: {minutos} min/semana > {p.carga_max_semanal_min}")
            )
    for (p_id, dia), minutos in diaria.items():
        p = cx.profesores.get(p_id)
        if p and minutos > p.carga_max_diaria_min:
            v.append(
                Violacion("D7", f"{p.nombre}: {minutos} min el {dia} > {p.carga_max_diaria_min}")
            )
    return v


def _contiguas(f1: Franja, f2: Franja) -> bool:
    """Consecutivas sin ningún intervalo (receso) entre ellas."""
    return (
        f1.nivel_id == f2.nivel_id
        and f1.dia == f2.dia
        and f2.indice == f1.indice + 1
        and f1.fin == f2.inicio
    )


def _rachas(franjas: list[Franja]) -> list[int]:
    """Longitudes de las rachas de franjas contiguas (la lista debe venir ordenada)."""
    rachas: list[int] = []
    for i, f in enumerate(franjas):
        if i and _contiguas(franjas[i - 1], f):
            rachas[-1] += 1
        else:
            rachas.append(1)
    return rachas


def _d8_consecutivas(cx: _Contexto) -> list[Violacion]:
    por_prof: dict[tuple[int, int, str], list[Franja]] = defaultdict(list)
    for a in cx.asignaciones:
        f = cx.franja(a)
        if f is not None:
            por_prof[(a.profesor_id, a.nivel_id, a.dia)].append(f)
    v: list[Violacion] = []
    for (p_id, _n, dia), franjas in por_prof.items():
        p = cx.profesores.get(p_id)
        if p is None:
            continue
        mayor = max(_rachas(sorted(franjas, key=lambda f: f.indice)))
        if mayor > p.max_consecutivas:
            v.append(
                Violacion(
                    "D8",
                    f"{p.nombre} tiene {mayor} clases seguidas el {dia} "
                    f"(máximo {p.max_consecutivas})",
                )
            )
    return v


def _d9_espacios(cx: _Contexto) -> list[Violacion]:
    """Clases simultáneas (traslape real de horario) por tipo de espacio ≤ cantidad."""
    capacidad: Counter[str] = Counter()
    for e in cx.datos.espacios:
        capacidad[e.tipo] += e.cantidad
    por_tipo_dia: dict[tuple[str, str], list[Franja]] = defaultdict(list)
    for a in cx.asignaciones:
        asignatura = cx.asignaturas.get(a.asignatura_id)
        f = cx.franja(a)
        if asignatura and asignatura.espacio_requerido and f is not None:
            por_tipo_dia[(asignatura.espacio_requerido, a.dia)].append(f)
    v: list[Violacion] = []
    for (tipo, dia), franjas in por_tipo_dia.items():
        for f in franjas:
            simultaneas = sum(1 for o in franjas if o.inicio <= f.inicio < o.fin)
            if simultaneas > capacidad[tipo]:
                v.append(
                    Violacion(
                        "D9",
                        f"{simultaneas} clases usan espacios «{tipo}» el {dia} a las "
                        f"{a_hhmm(f.inicio)}; solo hay {capacidad[tipo]}",
                    )
                )
                break
    return v


def _por_grupo_asig_dia(cx: _Contexto) -> dict[tuple[int, int, str], list[Franja]]:
    resultado: dict[tuple[int, int, str], list[Franja]] = defaultdict(list)
    for a in cx.asignaciones:
        f = cx.franja(a)
        if f is not None:
            resultado[(a.grupo_id, a.asignatura_id, a.dia)].append(f)
    for franjas in resultado.values():
        franjas.sort(key=lambda f: f.indice)
    return resultado


def _d10_maximo_diario(cx: _Contexto) -> list[Violacion]:
    v: list[Violacion] = []
    for (g, a_id, dia), franjas in _por_grupo_asig_dia(cx).items():
        asignatura = cx.asignaturas.get(a_id)
        if asignatura is None:
            continue
        if len(franjas) > asignatura.max_horas_dia:
            v.append(
                Violacion(
                    "D10",
                    f"{asignatura.nombre} en {cx.nombre_grupo(g)} tiene {len(franjas)} horas el "
                    f"{dia} (máximo {asignatura.max_horas_dia})",
                )
            )
        elif asignatura.max_horas_dia == 2 and len(franjas) == 2:
            if not _contiguas(franjas[0], franjas[1]):
                v.append(
                    Violacion(
                        "D10",
                        f"Las dos horas de {asignatura.nombre} en {cx.nombre_grupo(g)} el {dia} "
                        "no son consecutivas",
                    )
                )
    return v


def _d11_bloque_doble(cx: _Contexto) -> list[Violacion]:
    sueltas: Counter[tuple[int, int]] = Counter()
    for (g, a_id, _dia), franjas in _por_grupo_asig_dia(cx).items():
        asignatura = cx.asignaturas.get(a_id)
        if asignatura and asignatura.bloque_doble.value == "obligatorio":
            sueltas[(g, a_id)] += sum(r % 2 for r in _rachas(franjas))
    v: list[Violacion] = []
    for (g, a_id), cuantas in sueltas.items():
        horas = sum(
            p.horas_semanales
            for p in cx.datos.plan
            if p.asignatura_id == a_id and p.grado_id == cx.grupos[g].grado_id
        )
        if cuantas > horas % 2:
            v.append(
                Violacion(
                    "D11",
                    f"{cx.nombre_asig(a_id)} en {cx.nombre_grupo(g)} tiene {cuantas} horas sin "
                    "formar bloque doble",
                )
            )
    return v


def _d12_sin_huecos(cx: _Contexto) -> list[Violacion]:
    ocupadas: dict[tuple[int, str], set[int]] = defaultdict(set)
    for a in cx.asignaciones:
        ocupadas[(a.grupo_id, a.dia)].add(a.indice)
    v: list[Violacion] = []
    for (g, dia), indices in ocupadas.items():
        grupo = cx.grupos.get(g)
        if grupo is None:
            continue
        nivel = cx.niveles[cx.grados[grupo.grado_id].nivel_id]
        if nivel.sin_huecos_alumnos and indices != set(range(len(indices))):
            v.append(
                Violacion(
                    "D12",
                    f"{cx.nombre_grupo(g)} tiene huecos el {dia} (franjas ocupadas: "
                    f"{', '.join(str(i + 1) for i in sorted(indices))})",
                )
            )
    return v


def _d13_fijas(cx: _Contexto) -> list[Violacion]:
    v: list[Violacion] = []
    for fija in cx.datos.asignaciones_fijas:
        cumple = any(
            a.grupo_id == fija.grupo_id
            and a.asignatura_id == fija.asignatura_id
            and a.dia == fija.dia
            and a.indice == fija.indice_franja
            and (fija.profesor_id is None or a.profesor_id == fija.profesor_id)
            for a in cx.asignaciones
        )
        if not cumple:
            v.append(
                Violacion(
                    "D13",
                    f"No se respetó la asignación fija de {cx.nombre_asig(fija.asignatura_id)} "
                    f"en {cx.nombre_grupo(fija.grupo_id)} el {fija.dia}, franja "
                    f"{fija.indice_franja + 1}",
                )
            )
    return v
