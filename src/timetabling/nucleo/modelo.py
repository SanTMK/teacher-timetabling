"""Creado con Claude. Variables y restricciones duras del modelo CP-SAT.

``x[g, a, p, s]``: el profesor ``p`` da la asignatura ``a`` al grupo ``g`` en la franja
``s``. Solo se crean las combinaciones permitidas (competencia D4 y disponibilidad D5
quedan garantizadas por la poda). ``y[g, a, p]``: ``p`` está a cargo de ``a`` en ``g``.

Cada restricción se registra bajo una *clave* que identifica su origen. En modo
diagnóstico, todas las restricciones de una misma clave se condicionan a un literal de
suposición, lo que permite a ``diagnostico.py`` identificar un subconjunto en conflicto.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from timetabling.dominio.modelos import (
    BloqueDoble,
    DatosEscuela,
    Franja,
    TipoDisponibilidad,
)
from timetabling.nucleo.franjas import (
    adyacentes,
    cliques_maximales,
    franjas_validas_profesor,
    generar_franjas,
    matriz_traslapes,
)

# Clave de un grupo de restricciones: (tipo, *ids). Tipos usados:
#   ("curricular", g, a)  D1 y D6
#   ("grupo", g)          D2
#   ("profesor", p)       D3
#   ("carga", p)          D7
#   ("consecutivas", p)   D8
#   ("espacio", tipo)     D9
#   ("diaria", g, a)      D10
#   ("bloque", g, a)      D11
#   ("sin_huecos", g)     D12
#   ("fija", indice)      D13
Clave = tuple[object, ...]
ClaveX = tuple[int, int, int, str]


@dataclass
class ModeloHorario:
    """Modelo construido junto con los índices que necesitan objetivo y resolución."""

    datos: DatosEscuela
    modelo: cp_model.CpModel
    franjas: dict[str, Franja]
    franjas_por_nivel_dia: dict[tuple[int, str], list[Franja]]
    traslapes: dict[str, set[str]]
    validas: dict[int, dict[str, TipoDisponibilidad]]
    x: dict[ClaveX, cp_model.IntVar] = field(default_factory=dict)
    y: dict[tuple[int, int, int], cp_model.IntVar] = field(default_factory=dict)
    suposiciones: dict[Clave, cp_model.IntVar] = field(default_factory=dict)
    con_suposiciones: bool = False

    # Índices de x
    por_ga: dict[tuple[int, int], list[ClaveX]] = field(default_factory=lambda: defaultdict(list))
    por_gs: dict[tuple[int, str], list[ClaveX]] = field(default_factory=lambda: defaultdict(list))
    por_ps: dict[tuple[int, str], list[ClaveX]] = field(default_factory=lambda: defaultdict(list))
    por_gap: dict[tuple[int, int, int], list[ClaveX]] = field(
        default_factory=lambda: defaultdict(list)
    )
    cliques: list[frozenset[str]] = field(default_factory=list)

    # Variables auxiliares: z[g,a,s] = 1 si g recibe a en s; o[p,s] = 1 si p da clase en s.
    z: dict[tuple[int, int, str], cp_model.IntVar] = field(default_factory=dict)
    o: dict[tuple[int, str], cp_model.IntVar] = field(default_factory=dict)
    # Horas sueltas (no emparejadas) por (g, a, s) en asignaturas con bloque doble.
    sueltas: dict[tuple[int, int], list[cp_model.IntVar]] = field(default_factory=dict)

    def literal(self, clave: Clave) -> cp_model.IntVar | None:
        if not self.con_suposiciones:
            return None
        if clave not in self.suposiciones:
            nombre = "sup_" + "_".join(str(c) for c in clave)
            self.suposiciones[clave] = self.modelo.new_bool_var(nombre)
        return self.suposiciones[clave]

    def agregar(self, restriccion: cp_model.BoundedLinearExpression | bool, clave: Clave) -> None:
        """Agrega una restricción lineal bajo ``clave``."""
        ct = self.modelo.add(restriccion)
        literal = self.literal(clave)
        if literal is not None:
            ct.only_enforce_if(literal)

    def suma(self, claves: Iterable[ClaveX], coef: dict[ClaveX, int] | None = None) -> object:
        claves = list(claves)
        if coef is None:
            return cp_model.LinearExpr.sum([self.x[k] for k in claves])
        return cp_model.LinearExpr.weighted_sum(
            [self.x[k] for k in claves], [coef[k] for k in claves]
        )


def construir_modelo(datos: DatosEscuela, con_suposiciones: bool = False) -> ModeloHorario:
    """Construye el modelo CP-SAT con todas las restricciones duras."""
    franjas = generar_franjas(datos)
    por_nivel_dia: dict[tuple[int, str], list[Franja]] = defaultdict(list)
    for franja in franjas:
        por_nivel_dia[(franja.nivel_id, franja.dia)].append(franja)
    mh = ModeloHorario(
        datos=datos,
        modelo=cp_model.CpModel(),
        franjas={f.id: f for f in franjas},
        franjas_por_nivel_dia=dict(por_nivel_dia),
        traslapes=matriz_traslapes(franjas, datos.configuracion.margen_traslado_min),
        validas={p.id: franjas_validas_profesor(p, franjas) for p in datos.profesores},
        con_suposiciones=con_suposiciones,
    )
    mh.cliques = cliques_maximales(mh.traslapes)
    _crear_variables(mh)
    _d1_d6_curricular_y_continuidad(mh)
    _d2_un_maestro_por_franja(mh)
    _d3_profesor_en_un_lugar(mh)
    _d7_carga_maxima(mh)
    _d8_clases_consecutivas(mh)
    _d9_espacios(mh)
    _d10_maximo_diario(mh)
    _d11_bloques_dobles(mh)
    _d12_sin_huecos_alumnos(mh)
    _d13_asignaciones_fijas(mh)
    return mh


def franjas_del_dia(mh: ModeloHorario, nivel_id: int, dia: str) -> list[Franja]:
    return sorted(mh.franjas_por_nivel_dia.get((nivel_id, dia), []), key=lambda f: f.indice)


def tramos_consecutivos(franjas: list[Franja]) -> list[list[Franja]]:
    """Divide las franjas ordenadas de un día en tramos sin receso intermedio."""
    tramos: list[list[Franja]] = []
    for f in franjas:
        if tramos and adyacentes(tramos[-1][-1], f):
            tramos[-1].append(f)
        else:
            tramos.append([f])
    return tramos


def _crear_variables(mh: ModeloHorario) -> None:
    datos = mh.datos
    for grupo in datos.grupos:
        grado = datos.grado(grupo.grado_id)
        nivel_id = grado.nivel_id
        for asignatura_id in datos.plan_de_grado(grado.id):
            for profesor in datos.profesores:
                if asignatura_id not in profesor.asignaturas or grado.id not in profesor.grados:
                    continue
                validas = mh.validas[profesor.id]
                franjas_p = [
                    s for s, f in mh.franjas.items() if f.nivel_id == nivel_id and s in validas
                ]
                if not franjas_p:
                    continue
                g, a, p = grupo.id, asignatura_id, profesor.id
                mh.y[(g, a, p)] = mh.modelo.new_bool_var(f"y_{g}_{a}_{p}")
                for s in franjas_p:
                    clave = (g, a, p, s)
                    mh.x[clave] = mh.modelo.new_bool_var(f"x_{g}_{a}_{p}_{s}")
                    mh.por_ga[(g, a)].append(clave)
                    mh.por_gs[(g, s)].append(clave)
                    mh.por_ps[(p, s)].append(clave)
                    mh.por_gap[(g, a, p)].append(clave)
    for (g, a), claves in mh.por_ga.items():
        por_franja: dict[str, list[ClaveX]] = defaultdict(list)
        for k in claves:
            por_franja[k[3]].append(k)
        for s, ks in por_franja.items():
            mh.z[(g, a, s)] = _variable_suma(mh, f"z_{g}_{a}_{s}", ks)
    for (p, s), ks in mh.por_ps.items():
        mh.o[(p, s)] = _variable_suma(mh, f"o_{p}_{s}", ks)


def _variable_suma(mh: ModeloHorario, nombre: str, claves: list[ClaveX]) -> cp_model.IntVar:
    """Variable igual a la suma de ``x``. Normalmente es booleana (D2 y D3 garantizan que la
    suma es ≤ 1); en modo diagnóstico es entera para no imponer esas restricciones fuera de
    sus literales de suposición."""
    if mh.con_suposiciones:
        var = mh.modelo.new_int_var(0, len(claves), nombre)
    else:
        var = mh.modelo.new_bool_var(nombre)
    mh.modelo.add(var == mh.suma(claves))
    return var


def _d1_d6_curricular_y_continuidad(mh: ModeloHorario) -> None:
    """D1: horas semanales exactas. D6: un único profesor por grupo y asignatura."""
    datos = mh.datos
    for grupo in datos.grupos:
        for a, horas in datos.plan_de_grado(grupo.grado_id).items():
            g = grupo.id
            clave = ("curricular", g, a)
            mh.agregar(mh.suma(mh.por_ga[(g, a)]) == horas, clave)
            ys = [v for (gg, aa, _), v in mh.y.items() if gg == g and aa == a]
            mh.agregar(cp_model.LinearExpr.sum(ys) == 1, clave)
            for (gg, aa, p), y in mh.y.items():
                if gg == g and aa == a:
                    # Σ_s x[g,a,p,s] = horas · y[g,a,p]  (implica x ≤ y)
                    mh.agregar(mh.suma(mh.por_gap[(g, a, p)]) == horas * y, clave)


def _d2_un_maestro_por_franja(mh: ModeloHorario) -> None:
    for (g, _s), claves in mh.por_gs.items():
        if len(claves) > 1:
            mh.agregar(mh.suma(claves) <= 1, ("grupo", g))


def _d3_profesor_en_un_lugar(mh: ModeloHorario) -> None:
    """Para cada profesor y cada clique de franjas traslapadas: a lo sumo una clase."""
    for profesor in mh.datos.profesores:
        p = profesor.id
        vistos: set[frozenset[str]] = set()
        for clique in mh.cliques:
            usadas = frozenset(s for s in clique if mh.por_ps.get((p, s)))
            if not usadas or usadas in vistos:
                continue
            vistos.add(usadas)
            claves = [k for s in usadas for k in mh.por_ps[(p, s)]]
            mh.agregar(mh.suma(claves) <= 1, ("profesor", p))


def _d7_carga_maxima(mh: ModeloHorario) -> None:
    for profesor in mh.datos.profesores:
        p = profesor.id
        claves = [k for (pp, _s), ks in mh.por_ps.items() if pp == p for k in ks]
        if not claves:
            continue
        duracion = {k: mh.franjas[k[3]].duracion for k in claves}
        mh.agregar(mh.suma(claves, duracion) <= profesor.carga_max_semanal_min, ("carga", p))
        por_dia: dict[str, list[ClaveX]] = defaultdict(list)
        for k in claves:
            por_dia[mh.franjas[k[3]].dia].append(k)
        for del_dia in por_dia.values():
            total = sum(duracion[k] for k in del_dia)
            if total > profesor.carga_max_diaria_min:
                mh.agregar(
                    mh.suma(del_dia, duracion) <= profesor.carga_max_diaria_min, ("carga", p)
                )


def _d8_clases_consecutivas(mh: ModeloHorario) -> None:
    """En cada ventana de ``max_consecutivas + 1`` franjas consecutivas (mismo nivel y día,
    sin receso intermedio) el profesor tiene a lo sumo ``max_consecutivas`` clases."""
    for profesor in mh.datos.profesores:
        p, n = profesor.id, profesor.max_consecutivas
        for nivel_id, dia in mh.franjas_por_nivel_dia:
            for tramo in tramos_consecutivos(franjas_del_dia(mh, nivel_id, dia)):
                for i in range(len(tramo) - n):
                    ventana = [mh.o[(p, f.id)] for f in tramo[i : i + n + 1] if (p, f.id) in mh.o]
                    if len(ventana) > n:
                        mh.agregar(cp_model.LinearExpr.sum(ventana) <= n, ("consecutivas", p))


def _d9_espacios(mh: ModeloHorario) -> None:
    """Por tipo de espacio y clique de franjas traslapadas: clases que lo requieren ≤ cantidad."""
    capacidad = mh.datos.capacidad_espacios()
    requiere = {a.id: a.espacio_requerido for a in mh.datos.asignaturas if a.espacio_requerido}
    por_tipo_franja: dict[tuple[str, str], list[cp_model.IntVar]] = defaultdict(list)
    for (_g, a, s), var in mh.z.items():
        if a in requiere:
            por_tipo_franja[(requiere[a], s)].append(var)
    tipos = {t for t, _ in por_tipo_franja}
    for tipo in tipos:
        cantidad = capacidad.get(tipo, 0)
        vistos: set[frozenset[str]] = set()
        for clique in mh.cliques:
            usadas = frozenset(s for s in clique if (tipo, s) in por_tipo_franja)
            if not usadas or usadas in vistos:
                continue
            vistos.add(usadas)
            variables = [v for s in usadas for v in por_tipo_franja[(tipo, s)]]
            if len(variables) > cantidad:
                mh.agregar(cp_model.LinearExpr.sum(variables) <= cantidad, ("espacio", tipo))


def _z_por_dia(
    mh: ModeloHorario, g: int, a: int
) -> dict[str, list[tuple[Franja, cp_model.IntVar]]]:
    por_dia: dict[str, list[tuple[Franja, cp_model.IntVar]]] = defaultdict(list)
    for s in {k[3] for k in mh.por_ga.get((g, a), [])}:
        por_dia[mh.franjas[s].dia].append((mh.franjas[s], mh.z[(g, a, s)]))
    for lista in por_dia.values():
        lista.sort(key=lambda par: par[0].indice)
    return por_dia


def _d10_maximo_diario(mh: ModeloHorario) -> None:
    """Máximo de horas diarias por asignatura; si el máximo es 2, deben ser consecutivas."""
    for g, a in mh.por_ga:
        maximo = mh.datos.asignatura(a).max_horas_dia
        for del_dia in _z_por_dia(mh, g, a).values():
            if len(del_dia) > maximo:
                suma = cp_model.LinearExpr.sum([v for _, v in del_dia])
                mh.agregar(suma <= maximo, ("diaria", g, a))
            if maximo == 2:
                for i, (f1, v1) in enumerate(del_dia):
                    for f2, v2 in del_dia[i + 1 :]:
                        if not adyacentes(f1, f2):
                            mh.agregar(v1 + v2 <= 1, ("diaria", g, a))


def _d11_bloques_dobles(mh: ModeloHorario) -> None:
    """Empareja las horas en franjas adyacentes sin receso.

    Para ``obligatorio`` y ``preferido`` se crean variables de par ``b`` y de hora suelta
    ``u`` con ``z[s] = Σ b(pares que contienen s) + u[s]``. En ``obligatorio`` las horas
    sueltas se limitan a ``horas % 2`` (restricción dura); en ``preferido`` se penalizan
    en el objetivo (B8).
    """
    for grupo in mh.datos.grupos:
        g = grupo.id
        for a, horas in mh.datos.plan_de_grado(grupo.grado_id).items():
            modo = mh.datos.asignatura(a).bloque_doble
            if modo == BloqueDoble.NO or (g, a) not in mh.por_ga:
                continue
            sueltas: list[cp_model.IntVar] = []
            for _dia, del_dia in _z_por_dia(mh, g, a).items():
                pares: dict[str, list[cp_model.IntVar]] = defaultdict(list)
                for (f1, _v1), (f2, _v2) in zip(del_dia, del_dia[1:], strict=False):
                    if adyacentes(f1, f2):
                        b = mh.modelo.new_bool_var(f"b_{g}_{a}_{f1.id}")
                        pares[f1.id].append(b)
                        pares[f2.id].append(b)
                for f, v in del_dia:
                    u = mh.modelo.new_bool_var(f"u_{g}_{a}_{f.id}")
                    sueltas.append(u)
                    # Igualdad estructural: no se condiciona a suposiciones.
                    mh.modelo.add(v == cp_model.LinearExpr.sum(pares[f.id]) + u)
            mh.sueltas[(g, a)] = sueltas
            if modo == BloqueDoble.OBLIGATORIO:
                mh.agregar(cp_model.LinearExpr.sum(sueltas) <= horas % 2, ("bloque", g, a))


def _d12_sin_huecos_alumnos(mh: ModeloHorario) -> None:
    """Las clases del día empiezan en la primera franja y son continuas."""
    for grupo in mh.datos.grupos:
        nivel = mh.datos.nivel_de_grupo(grupo)
        if not nivel.sin_huecos_alumnos:
            continue
        g = grupo.id
        for dia in nivel.dias:
            franjas = franjas_del_dia(mh, nivel.id, dia)
            ocupada = [mh.suma(mh.por_gs.get((g, f.id), [])) for f in franjas]
            claves = [mh.por_gs.get((g, f.id), []) for f in franjas]
            for k in range(len(franjas) - 1):
                if claves[k + 1]:
                    mh.agregar(ocupada[k] >= ocupada[k + 1], ("sin_huecos", g))


def _d13_asignaciones_fijas(mh: ModeloHorario) -> None:
    datos = mh.datos
    for i, fija in enumerate(datos.asignaciones_fijas):
        grupo = datos.grupo(fija.grupo_id)
        nivel_id = datos.grado(grupo.grado_id).nivel_id
        s = f"{nivel_id}:{fija.dia}:{fija.indice_franja}"
        claves = [
            k
            for k in mh.por_gs.get((fija.grupo_id, s), [])
            if k[1] == fija.asignatura_id and (fija.profesor_id is None or k[2] == fija.profesor_id)
        ]
        clave = ("fija", i)
        if not claves:
            literal = mh.literal(clave)
            if literal is None:
                mh.modelo.add_bool_or([])  # imposible de cumplir
            else:
                mh.modelo.add_bool_or([literal.Not()])
            continue
        mh.agregar(mh.suma(claves) == 1, clave)
