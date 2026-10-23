"""Creado con Claude. Revisiones globales de los datos antes de ejecutar el solver."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from timetabling.dominio.modelos import (
    NOMBRES_DIAS,
    BloqueDoble,
    DatosEscuela,
    Franja,
    a_hhmm,
)
from timetabling.nucleo.franjas import (
    franjas_validas_profesor,
    generar_franjas_nivel,
    se_traslapan,
)


class Severidad(StrEnum):
    ERROR = "error"
    ADVERTENCIA = "advertencia"


@dataclass(frozen=True)
class Problema:
    entidad: str  # pantalla/tabla: niveles, grados, grupos, asignaturas, plan, profesores…
    elemento_id: int | None
    elemento: str
    severidad: Severidad
    mensaje: str

    def __str__(self) -> str:
        return f"{self.severidad.value.upper()} [{self.entidad}: {self.elemento}] {self.mensaje}"


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def hay_errores(problemas: list[Problema]) -> bool:
    return any(p.severidad == Severidad.ERROR for p in problemas)


def validar(datos: DatosEscuela) -> list[Problema]:
    """Ejecuta todas las revisiones. Con al menos un ``error`` no debe resolverse."""
    franjas_nivel: dict[int, list[Franja]] = {
        n.id: generar_franjas_nivel(n) for n in datos.niveles if n.id is not None
    }
    problemas: list[Problema] = []
    for revision in (
        _profesor_por_asignatura,
        _horas_caben,
        _capacidad_docente,
        _disponibilidad_util,
        _espacios,
        _asignaciones_fijas,
        _maximo_diario,
        _bloque_doble,
        _incompletos,
    ):
        problemas.extend(revision(datos, franjas_nivel))
    return problemas


def _habilitados(datos: DatosEscuela, asignatura_id: int, grado_id: int) -> list[int]:
    return [
        p.id
        for p in datos.profesores
        if asignatura_id in p.asignaturas and grado_id in p.grados and p.id is not None
    ]


def _profesor_por_asignatura(
    datos: DatosEscuela, franjas_nivel: dict[int, list[Franja]]
) -> list[Problema]:
    """1. Cada (grado, asignatura) del plan tiene al menos un profesor habilitado."""
    problemas = []
    for item in datos.plan:
        if item.horas_semanales <= 0:
            continue
        if not _habilitados(datos, item.asignatura_id, item.grado_id):
            grado = datos.grado(item.grado_id)
            asignatura = datos.asignatura(item.asignatura_id)
            problemas.append(
                Problema(
                    "plan",
                    item.grado_id,
                    f"{grado.nombre} – {asignatura.nombre}",
                    Severidad.ERROR,
                    f"Ningún profesor está habilitado para dar {asignatura.nombre} en "
                    f"{grado.nombre} ({datos.nivel(grado.nivel_id).nombre})",
                )
            )
    return problemas


def _horas_caben(datos: DatosEscuela, franjas_nivel: dict[int, list[Franja]]) -> list[Problema]:
    """2. Las horas del plan de cada grado caben en las franjas semanales de su nivel."""
    problemas = []
    for grado in datos.grados:
        horas = sum(datos.plan_de_grado(grado.id).values())
        disponibles = len(franjas_nivel.get(grado.nivel_id, []))
        if horas > disponibles:
            problemas.append(
                Problema(
                    "plan",
                    grado.id,
                    grado.nombre,
                    Severidad.ERROR,
                    f"El plan de {grado.nombre} suma {horas} horas-clase, pero su nivel solo "
                    f"tiene {disponibles} franjas por semana",
                )
            )
    return problemas


def _capacidad_docente(
    datos: DatosEscuela, franjas_nivel: dict[int, list[Franja]]
) -> list[Problema]:
    """3. Minutos demandados por asignatura y nivel ≤ minutos que pueden ofrecer los
    profesores habilitados (limitados por su carga máxima y su disponibilidad)."""
    problemas = []
    for nivel in datos.niveles:
        grados = [g for g in datos.grados if g.nivel_id == nivel.id]
        demanda: dict[int, int] = defaultdict(int)
        for grupo in datos.grupos:
            if any(g.id == grupo.grado_id for g in grados):
                for a, horas in datos.plan_de_grado(grupo.grado_id).items():
                    demanda[a] += horas * nivel.duracion_min
        for asignatura_id, minutos in demanda.items():
            oferta = 0
            habilitados = 0
            for profesor in datos.profesores:
                if asignatura_id not in profesor.asignaturas:
                    continue
                if not any(g.id in profesor.grados for g in grados):
                    continue
                validas = franjas_validas_profesor(profesor, franjas_nivel.get(nivel.id, []))
                disponibles = sum(
                    f.duracion for f in franjas_nivel.get(nivel.id, []) if f.id in validas
                )
                oferta += min(profesor.carga_max_semanal_min, disponibles)
                habilitados += 1
            # Sin ningún habilitado ya lo reporta la revisión 1.
            if habilitados and minutos > oferta:
                asignatura = datos.asignatura(asignatura_id)
                problemas.append(
                    Problema(
                        "profesores",
                        asignatura_id,
                        f"{asignatura.nombre} ({nivel.nombre})",
                        Severidad.ERROR,
                        f"{asignatura.nombre} en {nivel.nombre.lower()} requiere "
                        f"{_miles(minutos)} min/semana; los profesores habilitados suman "
                        f"{_miles(oferta)}",
                    )
                )
    return problemas


def _disponibilidad_util(
    datos: DatosEscuela, franjas_nivel: dict[int, list[Franja]]
) -> list[Problema]:
    """4. Cada rango de disponibilidad cubre al menos una franja de un nivel atendido."""
    problemas = []
    for profesor in datos.profesores:
        niveles = {datos.grado(g).nivel_id for g in profesor.grados}
        franjas = [f for n in niveles for f in franjas_nivel.get(n, [])]
        for rango in profesor.disponibilidad:
            if not any(
                f.dia == rango.dia and rango.inicio <= f.inicio and f.fin <= rango.fin
                for f in franjas
            ):
                problemas.append(
                    Problema(
                        "profesores",
                        profesor.id,
                        profesor.nombre,
                        Severidad.ADVERTENCIA,
                        f"El rango {NOMBRES_DIAS[rango.dia]} {a_hhmm(rango.inicio)}–"
                        f"{a_hhmm(rango.fin)} no cubre completa ninguna franja de los niveles "
                        "que atiende",
                    )
                )
    return problemas


def _espacios(datos: DatosEscuela, franjas_nivel: dict[int, list[Franja]]) -> list[Problema]:
    """5. Demanda semanal de cada tipo de espacio ≤ franjas × cantidad (por nivel)."""
    capacidad = datos.capacidad_espacios()
    demanda: dict[tuple[str, int], int] = defaultdict(int)
    for grupo in datos.grupos:
        nivel_id = datos.grado(grupo.grado_id).nivel_id
        for a, horas in datos.plan_de_grado(grupo.grado_id).items():
            tipo = datos.asignatura(a).espacio_requerido
            if tipo:
                demanda[(tipo, nivel_id)] += horas
    problemas = []
    for (tipo, nivel_id), clases in demanda.items():
        franjas = len(franjas_nivel.get(nivel_id, []))
        cantidad = capacidad.get(tipo, 0)
        if clases > franjas * cantidad:
            nivel = datos.nivel(nivel_id)
            problemas.append(
                Problema(
                    "espacios",
                    None,
                    tipo,
                    Severidad.ERROR,
                    f"En {nivel.nombre.lower()} se necesitan {clases} clases/semana en espacios "
                    f"de tipo «{tipo}», pero solo hay {cantidad} espacio(s) × {franjas} franjas",
                )
            )
    return problemas


def _asignaciones_fijas(
    datos: DatosEscuela, franjas_nivel: dict[int, list[Franja]]
) -> list[Problema]:
    """6. Asignaciones fijas coherentes y sin choques entre sí."""
    problemas = []
    margen = datos.configuracion.margen_traslado_min
    ubicadas: list[tuple[int, int, int | None, Franja]] = []  # (i, grupo, profesor, franja)

    def problema(i: int, mensaje: str) -> Problema:
        fija = datos.asignaciones_fijas[i]
        return Problema("asignaciones_fijas", fija.id, f"Fija #{i + 1}", Severidad.ERROR, mensaje)

    for i, fija in enumerate(datos.asignaciones_fijas):
        grupo = datos.grupo(fija.grupo_id)
        grado = datos.grado(grupo.grado_id)
        nombre_grupo = datos.nombre_grupo(grupo)
        asignatura = datos.asignatura(fija.asignatura_id)
        if fija.asignatura_id not in datos.plan_de_grado(grado.id):
            problemas.append(
                problema(i, f"{asignatura.nombre} no está en el plan de {grado.nombre}")
            )
        franja = next(
            (
                f
                for f in franjas_nivel.get(grado.nivel_id, [])
                if f.dia == fija.dia and f.indice == fija.indice_franja
            ),
            None,
        )
        if franja is None:
            problemas.append(
                problema(
                    i,
                    f"La franja {fija.indice_franja + 1} del {NOMBRES_DIAS.get(fija.dia, fija.dia)}"
                    f" no existe en el nivel de {nombre_grupo}",
                )
            )
            continue
        if fija.profesor_id is not None:
            profesor = datos.profesor(fija.profesor_id)
            if fija.asignatura_id not in profesor.asignaturas or grado.id not in profesor.grados:
                problemas.append(
                    problema(
                        i,
                        f"{profesor.nombre} no está habilitado para {asignatura.nombre} en "
                        f"{grado.nombre}",
                    )
                )
            if franja.id not in franjas_validas_profesor(profesor, [franja]):
                problemas.append(
                    problema(
                        i,
                        f"{profesor.nombre} no está disponible el "
                        f"{NOMBRES_DIAS[franja.dia]} {a_hhmm(franja.inicio)}",
                    )
                )
        ubicadas.append((i, fija.grupo_id, fija.profesor_id, franja))

    for k, (i, g1, p1, f1) in enumerate(ubicadas):
        for j, g2, p2, f2 in ubicadas[k + 1 :]:
            if g1 == g2 and f1.id == f2.id:
                problemas.append(
                    problema(j, f"Choca con la fija #{i + 1}: mismo grupo y misma franja")
                )
            elif p1 is not None and p1 == p2 and se_traslapan(f1, f2, margen):
                problemas.append(
                    problema(j, f"Choca con la fija #{i + 1}: el profesor estaría en dos lugares")
                )
    return problemas


def _maximo_diario(datos: DatosEscuela, franjas_nivel: dict[int, list[Franja]]) -> list[Problema]:
    """7. ``max_horas_dia × días ≥ horas_semanales``."""
    problemas = []
    for item in datos.plan:
        if item.horas_semanales <= 0:
            continue
        asignatura = datos.asignatura(item.asignatura_id)
        grado = datos.grado(item.grado_id)
        dias = len(datos.nivel(grado.nivel_id).dias)
        if asignatura.max_horas_dia * dias < item.horas_semanales:
            problemas.append(
                Problema(
                    "asignaturas",
                    asignatura.id,
                    asignatura.nombre,
                    Severidad.ERROR,
                    f"{asignatura.nombre} en {grado.nombre} pide {item.horas_semanales} horas, "
                    f"pero con un máximo de {asignatura.max_horas_dia} por día y {dias} días "
                    f"solo caben {asignatura.max_horas_dia * dias}",
                )
            )
    return problemas


def _bloque_doble(datos: DatosEscuela, franjas_nivel: dict[int, list[Franja]]) -> list[Problema]:
    """Bloque doble obligatorio con máximo diario de 1 hora es imposible."""
    return [
        Problema(
            "asignaturas",
            a.id,
            a.nombre,
            Severidad.ERROR,
            f"{a.nombre} exige bloque doble, pero su máximo diario es 1 hora",
        )
        for a in datos.asignaturas
        if a.bloque_doble == BloqueDoble.OBLIGATORIO and a.max_horas_dia < 2
    ]


def _incompletos(datos: DatosEscuela, franjas_nivel: dict[int, list[Franja]]) -> list[Problema]:
    """8. Elementos incompletos (advertencias)."""
    problemas = []
    for grado in datos.grados:
        tiene_grupos = any(g.grado_id == grado.id for g in datos.grupos)
        if not tiene_grupos:
            problemas.append(
                Problema(
                    "grados",
                    grado.id,
                    grado.nombre,
                    Severidad.ADVERTENCIA,
                    f"El grado {grado.nombre} no tiene grupos",
                )
            )
        elif not datos.plan_de_grado(grado.id):
            problemas.append(
                Problema(
                    "plan",
                    grado.id,
                    grado.nombre,
                    Severidad.ADVERTENCIA,
                    f"El grado {grado.nombre} tiene grupos pero no tiene plan de estudios",
                )
            )
    for nivel in datos.niveles:
        if not franjas_nivel.get(nivel.id):
            problemas.append(
                Problema(
                    "niveles",
                    nivel.id,
                    nivel.nombre,
                    Severidad.ADVERTENCIA,
                    f"El nivel {nivel.nombre} no genera ninguna franja",
                )
            )
    for profesor in datos.profesores:
        if not profesor.asignaturas:
            problemas.append(
                Problema(
                    "profesores",
                    profesor.id,
                    profesor.nombre,
                    Severidad.ADVERTENCIA,
                    f"{profesor.nombre} no tiene asignaturas",
                )
            )
        if not profesor.grados:
            problemas.append(
                Problema(
                    "profesores",
                    profesor.id,
                    profesor.nombre,
                    Severidad.ADVERTENCIA,
                    f"{profesor.nombre} no tiene grados habilitados",
                )
            )
        if not profesor.disponibilidad:
            problemas.append(
                Problema(
                    "profesores",
                    profesor.id,
                    profesor.nombre,
                    Severidad.ADVERTENCIA,
                    f"{profesor.nombre} no tiene disponibilidad",
                )
            )
    return problemas
