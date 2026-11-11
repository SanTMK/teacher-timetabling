"""Creado con Claude. Pantalla de clases fijas con arrastrar y soltar: se elige un grupo y se
arrastran asignaturas con su profesor (o «cualquiera») a las horas de la semana, antes de
generar."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
)

from timetabling.dominio.cuadricula import cuadricula_grupo
from timetabling.dominio.modelos import (
    NOMBRES_DIAS,
    AsignacionFija,
    DatosEscuela,
    Franja,
    TipoDisponibilidad,
    a_hhmm,
)
from timetabling.gui.pantallas.base import Pantalla
from timetabling.gui.widgets.arrastre import CuadriculaFijas, Info, Paleta
from timetabling.gui.widgets.vista_horario import ICONO_FIJA
from timetabling.nucleo.franjas import franjas_validas_profesor, generar_franjas, se_traslapan
from timetabling.nucleo.validacion import validar

CUALQUIERA = "cualquiera (lo elige el programa)"
SOMBRA_NO_DISPONIBLE = "#E0E0E0"
SOMBRA_PREFERIBLE_NO = "#FFE0B2"
SOMBRA_OCUPADO = "#FFCDD2"


class PantallaFijas(Pantalla):
    titulo = "Clases fijas"

    def __init__(self) -> None:
        super().__init__()
        self._datos = DatosEscuela()
        self._franjas: list[Franja] = []
        self.grupo = QComboBox()
        self.grupo.currentIndexChanged.connect(self._mostrar_grupo)
        self.paleta = Paleta()
        self.paleta.currentItemChanged.connect(self._sombrear)
        self.paleta.quitar_pedido.connect(self.quitar)
        self.cuadricula = CuadriculaFijas()
        self.cuadricula.soltado.connect(self.colocar)
        self.cuadricula.quitar_pedido.connect(self.quitar)
        self.avisos = QLabel()
        self.avisos.setStyleSheet("color: #C62828;")
        self.avisos.setWordWrap(True)
        ayuda = QLabel(
            "Arrastre un profesor (o «cualquiera») de la izquierda a una hora de la semana. "
            "Para mover una clase, arrástrela a otra hora; para quitarla, devuélvala a la "
            "izquierda o pulse Supr. Al elegir un profesor se sombrean las horas en que no "
            "está disponible (gris), preferiría no (naranja) o ya tiene otra clase fija (rojo)."
        )
        ayuda.setWordWrap(True)

        selector = QHBoxLayout()
        selector.addWidget(QLabel("Grupo:"))
        selector.addWidget(self.grupo, 1)
        divisor = QSplitter()
        divisor.addWidget(self.paleta)
        divisor.addWidget(self.cuadricula)
        divisor.setStretchFactor(1, 3)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(f"<h2>{self.titulo}</h2>"))
        capa.addLayout(selector)
        capa.addWidget(ayuda)
        capa.addWidget(divisor, 1)
        capa.addWidget(self.avisos)

    # --- Datos ----------------------------------------------------------------------

    def refrescar(self) -> None:
        assert self.repo is not None
        self._datos = self.repo.cargar_datos()
        self._franjas = generar_franjas(self._datos)
        anterior = self.grupo.currentData()
        self.grupo.blockSignals(True)
        self.grupo.clear()
        for g in self._datos.grupos:
            self.grupo.addItem(self._datos.nombre_grupo(g), g.id)
        indice = self.grupo.findData(anterior)
        self.grupo.setCurrentIndex(indice if indice >= 0 else min(0, self.grupo.count() - 1))
        self.grupo.blockSignals(False)
        self._mostrar_grupo()

    def _franja(self, fija: AsignacionFija) -> Franja | None:
        nivel_id = self._datos.nivel_de_grupo(self._datos.grupo(fija.grupo_id)).id
        return next(
            (
                f
                for f in self._franjas
                if f.nivel_id == nivel_id and f.dia == fija.dia and f.indice == fija.indice_franja
            ),
            None,
        )

    def _nombre_profesor(self, profesor_id: int | None) -> str:
        return self._datos.profesor(profesor_id).nombre if profesor_id else "cualquiera"

    # --- Dibujo ---------------------------------------------------------------------

    def _mostrar_grupo(self) -> None:
        seleccion = self.paleta.info_seleccionada()
        self.paleta.clear()
        self.cuadricula.setRowCount(0)
        self.avisos.clear()
        grupo_id = self.grupo.currentData()
        if grupo_id is None:
            return
        datos = self._datos
        grado_id = datos.grupo(grupo_id).grado_id
        plan = datos.plan_de_grado(grado_id)
        propias = [f for f in datos.asignaciones_fijas if f.grupo_id == grupo_id]

        for asignatura in datos.asignaturas:
            if asignatura.id not in plan:
                continue
            cuantas = sum(f.asignatura_id == asignatura.id for f in propias)
            padre = self.paleta.agregar_asignatura(
                f"{asignatura.nombre}  ·  {cuantas} de {plan[asignatura.id]} h fijas",
                asignatura.color,
            )
            Paleta.agregar_profesor(
                padre, CUALQUIERA, {"asignatura_id": asignatura.id, "profesor_id": None}
            )
            for p in datos.profesores:
                if asignatura.id in p.asignaturas and grado_id in p.grados:
                    Paleta.agregar_profesor(
                        padre, p.nombre, {"asignatura_id": asignatura.id, "profesor_id": p.id}
                    )
        self.paleta.expandAll()

        self.cuadricula.mostrar(cuadricula_grupo(datos, self._franjas, [], grupo_id))
        problemas: dict[int, list[str]] = {}
        for p in validar(datos):
            if p.entidad == "asignaciones_fijas" and p.elemento_id is not None:
                problemas.setdefault(p.elemento_id, []).append(p.mensaje)
        avisos = []
        for fija in propias:
            assert fija.id is not None
            asignatura = datos.asignatura(fija.asignatura_id)
            profesor = self._nombre_profesor(fija.profesor_id)
            mensajes = problemas.get(fija.id, [])
            marca = "⚠" if mensajes else ICONO_FIJA
            self.cuadricula.poner_clase(
                fija.dia,
                fija.indice_franja,
                f"{marca} {asignatura.nombre}\n{profesor}",
                asignatura.color,
                {
                    "fija_id": fija.id,
                    "asignatura_id": fija.asignatura_id,
                    "profesor_id": fija.profesor_id,
                },
                "\n".join([f"{asignatura.nombre} · {profesor}", *mensajes])
                or "Arrástrela para moverla",
            )
            franja = self._franja(fija)
            cuando = (
                f"{NOMBRES_DIAS.get(fija.dia, fija.dia)} {a_hhmm(franja.inicio)}"
                if franja
                else f"{NOMBRES_DIAS.get(fija.dia, fija.dia)}, hora {fija.indice_franja + 1}"
            )
            avisos += [f"⚠ {asignatura.nombre} ({cuando}): {m}" for m in mensajes]
        self.avisos.setText("\n".join(avisos))
        self.paleta.seleccionar_info(seleccion)
        self._sombrear()

    def _sombrear(self) -> None:
        """Sombrea las horas libres según el profesor elegido en la paleta."""
        grupo_id = self.grupo.currentData()
        if grupo_id is None:
            return
        datos = self._datos
        nivel_id = datos.nivel_de_grupo(datos.grupo(grupo_id)).id
        del_nivel = [f for f in self._franjas if f.nivel_id == nivel_id]
        info = self.paleta.info_seleccionada()
        profesor_id = info.get("profesor_id") if info else None
        if profesor_id is None:
            for f in del_nivel:
                self.cuadricula.sombrear(f.dia, f.indice, None)
            return
        profesor = datos.profesor(profesor_id)
        validas = franjas_validas_profesor(profesor, del_nivel, self._datos.eventos_de(profesor))
        margen = datos.configuracion.margen_traslado_min
        otras = [
            (fija, franja)
            for fija in datos.asignaciones_fijas
            if fija.profesor_id == profesor_id and fija.grupo_id != grupo_id
            for franja in [self._franja(fija)]
            if franja is not None
        ]
        for f in del_nivel:
            choque = next((fija for fija, otra in otras if se_traslapan(f, otra, margen)), None)
            if choque is not None:
                grupo = datos.nombre_grupo(datos.grupo(choque.grupo_id))
                self.cuadricula.sombrear(
                    f.dia,
                    f.indice,
                    SOMBRA_OCUPADO,
                    f"{profesor.nombre} ya tiene clase fija con {grupo}",
                )
            elif f.id not in validas:
                self.cuadricula.sombrear(
                    f.dia, f.indice, SOMBRA_NO_DISPONIBLE, f"{profesor.nombre} no está disponible"
                )
            elif validas[f.id] == TipoDisponibilidad.PREFERIBLE_NO:
                self.cuadricula.sombrear(
                    f.dia, f.indice, SOMBRA_PREFERIBLE_NO, f"{profesor.nombre} preferiría no"
                )
            else:
                self.cuadricula.sombrear(f.dia, f.indice, None)

    # --- Acciones de arrastre -------------------------------------------------------

    def colocar(self, info: Info, dia: str, indice: int) -> None:
        """Crea una clase fija (desde la paleta) o mueve una existente a (día, franja)."""
        assert self.repo is not None
        fija_id = info.get("fija_id")
        if fija_id is not None:
            fija = next(f for f in self._datos.asignaciones_fijas if f.id == fija_id)
            if (fija.dia, fija.indice_franja) == (dia, indice):
                return
            fija = fija.model_copy(update={"dia": dia, "indice_franja": indice})
        else:
            fija = AsignacionFija(
                grupo_id=self.grupo.currentData(),
                asignatura_id=info["asignatura_id"],
                profesor_id=info.get("profesor_id"),
                dia=dia,
                indice_franja=indice,
            )
        self.repo.guardar_asignacion_fija(fija)
        self.datos_cambiados.emit()
        self.refrescar()

    def quitar(self, fija_id: int) -> None:
        assert self.repo is not None
        self.repo.eliminar_asignacion_fija(fija_id)
        self.datos_cambiados.emit()
        self.refrescar()

    def seleccionar(self, entidad: str, elemento_id: int | None) -> None:
        fija = next((f for f in self._datos.asignaciones_fijas if f.id == elemento_id), None)
        if fija is None:
            return
        self.grupo.setCurrentIndex(self.grupo.findData(fija.grupo_id))
        item = self.cuadricula.celda(fija.dia, fija.indice_franja)
        if item is not None:
            self.cuadricula.setCurrentItem(item)
