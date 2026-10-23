"""Creado con Claude. Pruebas de generación de franjas, recesos y traslapes."""

from timetabling.dominio.modelos import (
    Disponibilidad,
    Franja,
    Nivel,
    Receso,
    TipoDisponibilidad,
    a_hhmm,
    a_minutos,
)
from timetabling.nucleo.franjas import (
    adyacentes,
    cliques_maximales,
    generar_franjas_nivel,
    matriz_traslapes,
    separadas_por_receso,
    tipo_disponibilidad,
)


def _nivel(id_: int, inicio: str, fin: str, dur: int, recesos: list[tuple[str, str]]) -> Nivel:
    return Nivel(
        id=id_,
        nombre=f"N{id_}",
        duracion_min=dur,
        inicio_jornada=a_minutos(inicio),
        fin_jornada=a_minutos(fin),
        dias=["L", "M"],
        recesos=[Receso(inicio=a_minutos(a), fin=a_minutos(b)) for a, b in recesos],
    )


def _horas(franjas: list[Franja], dia: str = "L") -> list[str]:
    return [f"{a_hhmm(f.inicio)}-{a_hhmm(f.fin)}" for f in franjas if f.dia == dia]


def test_franjas_sin_receso() -> None:
    franjas = generar_franjas_nivel(_nivel(1, "08:00", "11:00", 50, []))
    assert _horas(franjas) == ["08:00-08:50", "08:50-09:40", "09:40-10:30"]
    assert len(franjas) == 6  # dos días
    assert [f.indice for f in franjas if f.dia == "M"] == [0, 1, 2]


def test_franja_que_choca_con_receso_se_recorre() -> None:
    franjas = generar_franjas_nivel(_nivel(1, "07:30", "13:30", 50, [("10:00", "10:30")]))
    assert _horas(franjas) == [
        "07:30-08:20",
        "08:20-09:10",
        "09:10-10:00",
        "10:30-11:20",
        "11:20-12:10",
        "12:10-13:00",
    ]
    del_lunes = [f for f in franjas if f.dia == "L"]
    assert [f.receso_antes for f in del_lunes] == [False, False, False, True, False, False]
    assert separadas_por_receso(del_lunes[2], del_lunes[3])
    assert not adyacentes(del_lunes[2], del_lunes[3])
    assert adyacentes(del_lunes[3], del_lunes[4])


def test_receso_a_media_franja_deja_hueco() -> None:
    # La tercera franja (09:40-10:30) chocaría con el receso 10:00-10:20.
    franjas = generar_franjas_nivel(_nivel(1, "08:00", "12:00", 50, [("10:00", "10:20")]))
    assert _horas(franjas) == ["08:00-08:50", "08:50-09:40", "10:20-11:10", "11:10-12:00"]
    assert separadas_por_receso(franjas[1], franjas[2])


def test_receso_al_inicio_no_marca_separacion() -> None:
    franjas = generar_franjas_nivel(_nivel(1, "08:00", "10:00", 30, [("08:00", "08:30")]))
    assert _horas(franjas) == ["08:30-09:00", "09:00-09:30", "09:30-10:00"]
    assert not franjas[0].receso_antes


def test_traslapes_entre_niveles_con_margen() -> None:
    a = generar_franjas_nivel(_nivel(1, "08:00", "10:00", 60, []))  # 8-9, 9-10
    b = generar_franjas_nivel(_nivel(2, "09:05", "10:05", 60, []))  # 9:05-10:05
    lunes = [f for f in a + b if f.dia == "L"]
    a0, a1, b0 = lunes
    sin_margen = matriz_traslapes(a + b, 0)
    assert sin_margen[a0.id] == set()  # 8-9 y 9:05-10:05 no se tocan
    assert sin_margen[a1.id] == {b0.id}
    con_margen = matriz_traslapes(a + b, 10)
    assert con_margen[a0.id] == {b0.id}  # 9:00 + 10 min > 9:05
    # El margen no aplica dentro del mismo nivel
    assert a1.id not in con_margen[a0.id]
    # Días distintos nunca se traslapan
    assert all(x.split(":")[1] == a0.dia for x in con_margen[a0.id])


def test_cliques_cubren_todas_las_franjas_y_pares() -> None:
    a = generar_franjas_nivel(_nivel(1, "08:00", "10:00", 60, []))
    b = generar_franjas_nivel(_nivel(2, "08:30", "10:00", 45, []))
    franjas = a + b
    matriz = matriz_traslapes(franjas, 0)
    cliques = cliques_maximales(matriz)
    for f in franjas:
        assert any(f.id in c for c in cliques)
        for otra in matriz[f.id]:
            assert any({f.id, otra} <= c for c in cliques)
    for c in cliques:
        for x in c:
            assert c - {x} <= matriz[x]


def test_disponibilidad_franja_completa_y_tipo() -> None:
    franja = Franja(
        nivel_id=1, dia="L", indice=0, inicio=a_minutos("09:30"), fin=a_minutos("10:20")
    )
    solo_parcial = [Disponibilidad(dia="L", inicio=a_minutos("08:00"), fin=a_minutos("10:00"))]
    assert tipo_disponibilidad(franja, solo_parcial) is None
    contiguos = solo_parcial + [
        Disponibilidad(
            dia="L",
            inicio=a_minutos("10:00"),
            fin=a_minutos("12:00"),
            tipo=TipoDisponibilidad.PREFERIBLE_NO,
        )
    ]
    assert tipo_disponibilidad(franja, contiguos) == TipoDisponibilidad.PREFERIBLE_NO
    completo = [Disponibilidad(dia="L", inicio=a_minutos("07:00"), fin=a_minutos("14:00"))]
    assert tipo_disponibilidad(franja, completo) == TipoDisponibilidad.DISPONIBLE
    otro_dia = [Disponibilidad(dia="M", inicio=a_minutos("07:00"), fin=a_minutos("14:00"))]
    assert tipo_disponibilidad(franja, otro_dia) is None
