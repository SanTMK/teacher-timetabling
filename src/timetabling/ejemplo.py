"""Creado con Claude. Generador de proyectos de ejemplo (pequeño y mediano).

Los datos son ficticios pero realistas: preescolar, primaria y secundaria con
duraciones y recesos distintos, profesores que atienden varios niveles, espacios
especiales y algunas franjas marcadas como «preferible no».
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from timetabling.dominio.modelos import (
    Asignatura,
    BloqueDoble,
    Configuracion,
    DatosEscuela,
    Disponibilidad,
    Espacio,
    Grado,
    Grupo,
    Nivel,
    PlanEstudios,
    Profesor,
    Receso,
    TipoDisponibilidad,
    a_minutos,
)
from timetabling.persistencia.repositorio import Repositorio


class Tamano(StrEnum):
    PEQUENO = "pequeno"
    MEDIANO = "mediano"


@dataclass(frozen=True)
class _DefAsignatura:
    nombre: str
    color: str
    max_horas_dia: int = 2
    bloque_doble: BloqueDoble = BloqueDoble.NO
    exigente: bool = False
    espacio: str | None = None


_ASIGNATURAS: list[_DefAsignatura] = [
    _DefAsignatura("Lenguaje y comunicación", "#F4B6C2", max_horas_dia=2),
    _DefAsignatura("Pensamiento matemático", "#A8D5E2", max_horas_dia=2),
    _DefAsignatura("Exploración del mundo", "#B5E3B0", max_horas_dia=1),
    _DefAsignatura("Español", "#E57373", exigente=True),
    _DefAsignatura("Matemáticas", "#64B5F6", exigente=True),
    _DefAsignatura("Ciencias", "#81C784", bloque_doble=BloqueDoble.PREFERIDO),
    _DefAsignatura("Historia", "#FFB74D", max_horas_dia=1),
    _DefAsignatura("Geografía", "#A1887F", max_horas_dia=1),
    _DefAsignatura("Formación cívica", "#BA68C8", max_horas_dia=1),
    _DefAsignatura("Inglés", "#4DB6AC", max_horas_dia=1),
    _DefAsignatura("Educación física", "#FFF176", max_horas_dia=1, espacio="patio"),
    _DefAsignatura("Artes", "#F06292", max_horas_dia=1),
    _DefAsignatura("Tecnología", "#90A4AE", max_horas_dia=2, bloque_doble=BloqueDoble.OBLIGATORIO),
    _DefAsignatura("Computación", "#7986CB", max_horas_dia=1, espacio="computo"),
]

_PLAN_PREESCOLAR = {
    "Lenguaje y comunicación": 6,
    "Pensamiento matemático": 5,
    "Exploración del mundo": 4,
    "Artes": 3,
    "Educación física": 2,
    "Inglés": 2,
}
_PLAN_PRIMARIA = {
    "Español": 7,
    "Matemáticas": 7,
    "Ciencias": 3,
    "Historia": 2,
    "Geografía": 2,
    "Formación cívica": 1,
    "Inglés": 3,
    "Educación física": 2,
    "Artes": 2,
}
_PLAN_SECUNDARIA = {
    "Español": 5,
    "Matemáticas": 5,
    "Ciencias": 6,
    "Historia": 3,
    "Geografía": 3,
    "Formación cívica": 2,
    "Inglés": 4,
    "Educación física": 2,
    "Artes": 2,
    "Tecnología": 2,
    "Computación": 2,
}
# Asignaturas que en preescolar y primaria imparte el docente del grupo.
_DEL_TITULAR_PREESCOLAR = [
    "Lenguaje y comunicación",
    "Pensamiento matemático",
    "Exploración del mundo",
    "Artes",
]
_DEL_TITULAR_PRIMARIA = [
    "Español",
    "Matemáticas",
    "Ciencias",
    "Historia",
    "Geografía",
    "Formación cívica",
]

_NOMBRES = [
    "Ana López",
    "Bruno Díaz",
    "Carmen Ruiz",
    "Daniel Ortega",
    "Elena Vargas",
    "Fernando Gil",
    "Gabriela Mora",
    "Héctor Salas",
    "Irene Campos",
    "Jorge Peña",
    "Karla Ríos",
    "Luis Navarro",
    "María Fuentes",
    "Nicolás Herrera",
    "Olga Medina",
    "Pablo Castro",
    "Raquel Silva",
    "Sergio Lara",
    "Teresa Rojas",
    "Ulises Molina",
    "Valeria Soto",
    "Walter Reyes",
    "Ximena Cruz",
    "Yolanda Ibarra",
    "Zacarías Luna",
    "Adriana Paredes",
    "Benito Aguilar",
    "Cecilia Romero",
    "Diego Valdés",
    "Estela Montes",
    "Félix Cordero",
    "Gloria Pineda",
    "Hugo Benítez",
    "Inés Carrillo",
    "Julián Espinoza",
    "Lorena Guzmán",
    "Mario Cabrera",
    "Natalia Bravo",
    "Óscar Delgado",
    "Patricia Acosta",
    "Ramiro Quintero",
    "Sofía Zamora",
    "Tomás Villalobos",
    "Úrsula Jiménez",
    "Víctor Rangel",
    "Wendy Arriaga",
]

_DIAS = ["L", "M", "X", "J", "V"]


def _disponibilidad_completa(inicio: str, fin: str) -> list[Disponibilidad]:
    return [Disponibilidad(dia=d, inicio=a_minutos(inicio), fin=a_minutos(fin)) for d in _DIAS]


def construir_datos(tamano: Tamano = Tamano.PEQUENO) -> DatosEscuela:
    """Construye en memoria los datos de una escuela de ejemplo (con ids asignados)."""
    mediano = tamano == Tamano.MEDIANO
    niveles = [
        Nivel(
            id=1,
            nombre="Preescolar",
            duracion_min=45,
            inicio_jornada=a_minutos("08:00"),
            fin_jornada=a_minutos("12:15"),
            recesos=[Receso(nombre="Recreo", inicio=a_minutos("10:15"), fin=a_minutos("10:45"))],
            sin_huecos_alumnos=True,
        ),
        Nivel(
            id=2,
            nombre="Primaria",
            duracion_min=50,
            inicio_jornada=a_minutos("07:30"),
            fin_jornada=a_minutos("13:30"),
            recesos=[Receso(nombre="Recreo", inicio=a_minutos("10:00"), fin=a_minutos("10:30"))],
        ),
        Nivel(
            id=3,
            nombre="Secundaria",
            duracion_min=50,
            inicio_jornada=a_minutos("07:00"),
            fin_jornada=a_minutos("14:10"),
            recesos=[Receso(nombre="Receso", inicio=a_minutos("10:20"), fin=a_minutos("10:40"))],
        ),
    ]

    asignaturas = [
        Asignatura(
            id=i,
            nombre=d.nombre,
            color=d.color,
            max_horas_dia=d.max_horas_dia,
            bloque_doble=d.bloque_doble,
            exigente=d.exigente,
            espacio_requerido=d.espacio,
        )
        for i, d in enumerate(_ASIGNATURAS, start=1)
    ]
    id_asig = {a.nombre: a.id for a in asignaturas}

    # Grados y grupos por nivel: (nivel_id, nombres de grado, secciones, plan)
    estructura = [
        (1, ["K1", "K2", "K3"] if mediano else ["K3"], "AB" if mediano else "A", _PLAN_PREESCOLAR),
        (
            2,
            [f"{n}°" for n in range(1, 7)] if mediano else ["1°", "2°"],
            "AB" if mediano else "A",
            _PLAN_PRIMARIA,
        ),
        (
            3,
            ["7°", "8°", "9°"] if mediano else ["7°"],
            "ABCD" if mediano else "AB",
            _PLAN_SECUNDARIA,
        ),
    ]
    grados: list[Grado] = []
    grupos: list[Grupo] = []
    plan: list[PlanEstudios] = []
    grados_por_nivel: dict[int, list[int]] = {}
    for nivel_id, nombres, secciones, plan_nivel in estructura:
        for nombre in nombres:
            grado = Grado(id=len(grados) + 1, nivel_id=nivel_id, nombre=nombre)
            grados.append(grado)
            grados_por_nivel.setdefault(nivel_id, []).append(grado.id)
            for asignatura, horas in plan_nivel.items():
                plan.append(
                    PlanEstudios(
                        grado_id=grado.id, asignatura_id=id_asig[asignatura], horas_semanales=horas
                    )
                )
            for seccion in secciones:
                grupos.append(
                    Grupo(id=len(grupos) + 1, grado_id=grado.id, seccion=seccion, estudiantes=25)
                )

    profesores: list[Profesor] = []
    nombres = itertools.chain(_NOMBRES, (f"Docente {i}" for i in itertools.count(1)))

    def nuevo_profesor(
        asigs: list[str],
        grados_hab: list[int],
        carga_semanal: int,
        disponibilidad: list[Disponibilidad] | None = None,
        max_consecutivas: int = 4,
    ) -> Profesor:
        profesor = Profesor(
            id=len(profesores) + 1,
            nombre=next(nombres),
            asignaturas={id_asig[a] for a in asigs},
            grados=set(grados_hab),
            disponibilidad=disponibilidad or _disponibilidad_completa("07:00", "14:30"),
            carga_max_semanal_min=carga_semanal,
            carga_max_diaria_min=360,
            max_consecutivas=max_consecutivas,
        )
        profesores.append(profesor)
        return profesor

    # Titulares de preescolar y primaria: uno por grupo, habilitado para su grado.
    for grupo in grupos:
        nivel_id = next(g.nivel_id for g in grados if g.id == grupo.grado_id)
        if nivel_id == 1:
            titular = nuevo_profesor(
                _DEL_TITULAR_PREESCOLAR,
                [grupo.grado_id],
                1200,
                _disponibilidad_completa("07:45", "12:30"),
                max_consecutivas=5,
            )
            grupo.titular_id = titular.id
        elif nivel_id == 2:
            titular = nuevo_profesor(
                _DEL_TITULAR_PRIMARIA, [grupo.grado_id], 1400, max_consecutivas=5
            )
            grupo.titular_id = titular.id

    def demanda_min(asignatura: str, niveles_ids: list[int]) -> int:
        total = 0
        for grupo in grupos:
            grado = next(g for g in grados if g.id == grupo.grado_id)
            if grado.nivel_id not in niveles_ids:
                continue
            horas = next(
                (
                    p.horas_semanales
                    for p in plan
                    if p.grado_id == grado.id and p.asignatura_id == id_asig[asignatura]
                ),
                0,
            )
            total += horas * next(n.duracion_min for n in niveles if n.id == grado.nivel_id)
        return total

    def especialistas(asigs: list[str], niveles_ids: list[int], carga: int) -> None:
        demanda = sum(demanda_min(a, niveles_ids) for a in asigs)
        cuantos = max(1, math.ceil(demanda / (carga * 0.8)))
        habilitados = [g for n in niveles_ids for g in grados_por_nivel[n]]
        for i in range(cuantos):
            disponibilidad = None
            if i == 0 and len(profesores) % 3 == 0:
                # Un docente por grupo de especialistas prefiere no dar la primera hora.
                disponibilidad = _disponibilidad_completa("08:45", "14:30") + [
                    Disponibilidad(
                        dia=d,
                        inicio=a_minutos("07:00"),
                        fin=a_minutos("08:45"),
                        tipo=TipoDisponibilidad.PREFERIBLE_NO,
                    )
                    for d in _DIAS
                ]
            nuevo_profesor(asigs, habilitados, carga, disponibilidad)

    especialistas(["Educación física"], [1, 2, 3], 1500)
    especialistas(["Inglés"], [1, 2], 1500)
    especialistas(["Artes"], [2, 3], 1500)
    especialistas(["Español"], [3], 1500)
    especialistas(["Matemáticas"], [3], 1500)
    especialistas(["Ciencias"], [3], 1500)
    especialistas(["Historia", "Geografía", "Formación cívica"], [3], 1500)
    especialistas(["Inglés"], [3], 1500)
    especialistas(["Tecnología", "Computación"], [3], 1500)

    espacios = [
        Espacio(id=1, nombre="Patio principal", tipo="patio", cantidad=1),
        Espacio(id=2, nombre="Sala de cómputo", tipo="computo", cantidad=1),
    ]
    if mediano:
        espacios.append(Espacio(id=3, nombre="Gimnasio", tipo="patio", cantidad=1))

    return DatosEscuela(
        configuracion=Configuracion(
            nombre_escuela="Colegio de ejemplo" + (" (mediano)" if mediano else ""),
            margen_traslado_min=10,
            tiempo_limite_s=300,
            hilos=8,
        ),
        niveles=niveles,
        grados=grados,
        grupos=grupos,
        asignaturas=asignaturas,
        plan=plan,
        profesores=profesores,
        espacios=espacios,
    )


def crear_proyecto_ejemplo(
    ruta: str | Path, tamano: Tamano = Tamano.PEQUENO, sobrescribir: bool = False
) -> DatosEscuela:
    """Crea un archivo ``.horario`` con los datos de ejemplo y devuelve los datos."""
    datos = construir_datos(tamano)
    with Repositorio.crear(ruta, sobrescribir=sobrescribir) as repo:
        repo.reemplazar_datos(datos)
        return repo.cargar_datos()
