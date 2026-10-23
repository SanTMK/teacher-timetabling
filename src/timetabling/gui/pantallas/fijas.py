"""Creado con Claude. Pantalla de clases fijas: asignar a mano un profesor (o solo la
asignatura) a un grupo en un día y una hora concretos, antes de generar."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel

from timetabling.dominio.modelos import (
    NOMBRES_DIAS,
    AsignacionFija,
    DatosEscuela,
    Franja,
    a_hhmm,
)
from timetabling.gui.pantallas.base import PantallaListaFormulario
from timetabling.nucleo.franjas import franjas_validas_profesor, generar_franjas_nivel
from timetabling.nucleo.validacion import Problema, validar

CUALQUIERA = "(cualquiera: lo elige el programa)"


def _poner(combo: QComboBox, valor: object) -> None:
    """Selecciona el elemento cuyo dato es ``valor`` (si no está, deja el primero)."""
    indice = combo.findData(valor)
    combo.setCurrentIndex(indice if indice >= 0 else min(0, combo.count() - 1))


def _rellenar(combo: QComboBox, opciones: list[tuple[str, object]]) -> None:
    """Reemplaza las opciones conservando la selección si sigue existiendo."""
    anterior = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for texto, valor in opciones:
        combo.addItem(texto, valor)
    _poner(combo, anterior)
    combo.blockSignals(False)
    combo.currentIndexChanged.emit(combo.currentIndex())


class PantallaFijas(PantallaListaFormulario):
    titulo = "Clases fijas"
    tabla = "asignaciones_fijas"
    texto_nuevo = "Nueva clase fija"

    def __init__(self) -> None:
        super().__init__()
        self._datos = DatosEscuela()
        self._franjas_nivel: dict[int, list[Franja]] = {}
        ayuda = QLabel(
            "Elija grupo, asignatura, día y hora. Si elige un profesor, esa clase la dará "
            "él; con «cualquiera» el programa decide quién. Al generar se respetarán "
            "todas las clases fijas."
        )
        ayuda.setWordWrap(True)
        self.capa_contenido.insertWidget(0, ayuda)
        self.grupo = QComboBox()
        self.asignatura = QComboBox()
        self.profesor = QComboBox()
        self.dia = QComboBox()
        self.hora = QComboBox()
        self.errores.fila(self.formulario, "grupo_id", "Grupo", self.grupo)
        self.errores.fila(self.formulario, "asignatura_id", "Asignatura", self.asignatura)
        self.errores.fila(self.formulario, "profesor_id", "Profesor", self.profesor)
        self.errores.fila(self.formulario, "dia", "Día", self.dia)
        self.errores.fila(self.formulario, "indice_franja", "Hora", self.hora)
        self.capa_contenido.addStretch()
        self.grupo.currentIndexChanged.connect(self._al_cambiar_grupo)
        self.asignatura.currentIndexChanged.connect(self._al_cambiar_asignatura)
        self.profesor.currentIndexChanged.connect(self._actualizar_horas)
        self.dia.currentIndexChanged.connect(self._actualizar_horas)

    # --- Opciones en cascada: grupo → asignatura/día → profesor → hora ---------------

    def _grado_id(self) -> int | None:
        grupo_id = self.grupo.currentData()
        return None if grupo_id is None else self._datos.grupo(grupo_id).grado_id

    def _al_cambiar_grupo(self) -> None:
        grado_id = self._grado_id()
        asignaturas: list[tuple[str, object]] = []
        dias: list[tuple[str, object]] = []
        if grado_id is not None:
            plan = self._datos.plan_de_grado(grado_id)
            asignaturas = [
                (f"{a.nombre} ({plan[a.id]} h/semana)", a.id)
                for a in self._datos.asignaturas
                if a.id in plan
            ]
            nivel = self._datos.nivel(self._datos.grado(grado_id).nivel_id)
            dias = [(NOMBRES_DIAS.get(d, d), d) for d in nivel.dias]
        _rellenar(self.asignatura, asignaturas)
        _rellenar(self.dia, dias)

    def _al_cambiar_asignatura(self) -> None:
        grado_id = self._grado_id()
        asignatura_id = self.asignatura.currentData()
        opciones: list[tuple[str, object]] = [(CUALQUIERA, None)]
        opciones += [
            (p.nombre, p.id)
            for p in self._datos.profesores
            if asignatura_id in p.asignaturas and grado_id in p.grados
        ]
        _rellenar(self.profesor, opciones)

    def _actualizar_horas(self) -> None:
        grado_id = self._grado_id()
        opciones: list[tuple[str, object]] = []
        if grado_id is not None:
            franjas = [
                f
                for f in self._franjas_nivel.get(self._datos.grado(grado_id).nivel_id, [])
                if f.dia == self.dia.currentData()
            ]
            profesor_id = self.profesor.currentData()
            validas = (
                None
                if profesor_id is None
                else franjas_validas_profesor(self._datos.profesor(profesor_id), franjas)
            )
            for f in franjas:
                texto = f"{f.indice + 1}ª hora · {a_hhmm(f.inicio)}–{a_hhmm(f.fin)}"
                if validas is not None and f.id not in validas:
                    texto += " — el profesor no está disponible"
                opciones.append((texto, f.indice))
        _rellenar(self.hora, opciones)

    # --- Lista y formulario ---------------------------------------------------------

    def refrescar(self) -> None:
        assert self.repo is not None
        self._datos = self.repo.cargar_datos()
        self._franjas_nivel = {
            n.id: generar_franjas_nivel(n) for n in self._datos.niveles if n.id is not None
        }
        _rellenar(
            self.grupo,
            [(self._datos.nombre_grupo(g), g.id) for g in self._datos.grupos],
        )
        super().refrescar()

    def _descripcion(self, fija: AsignacionFija) -> str:
        datos = self._datos
        grupo = datos.grupo(fija.grupo_id)
        franja = next(
            (
                f
                for f in self._franjas_nivel.get(datos.grado(grupo.grado_id).nivel_id, [])
                if f.dia == fija.dia and f.indice == fija.indice_franja
            ),
            None,
        )
        hora = a_hhmm(franja.inicio) if franja else f"{fija.indice_franja + 1}ª hora"
        profesor = datos.profesor(fija.profesor_id).nombre if fija.profesor_id else "cualquiera"
        return (
            f"{datos.nombre_grupo(grupo)} · {datos.asignatura(fija.asignatura_id).nombre} · "
            f"{NOMBRES_DIAS.get(fija.dia, fija.dia)} {hora} · {profesor}"
        )

    def elementos(self) -> list[tuple[int, str]]:
        # El número coincide con «Fija #n» de los mensajes de validación.
        return [
            (f.id, f"#{i + 1}  {self._descripcion(f)}")
            for i, f in enumerate(self._datos.asignaciones_fijas)
            if f.id is not None
        ]

    def _problemas(self, fija_id: int) -> list[Problema]:
        return [
            p
            for p in validar(self._datos)
            if p.entidad == "asignaciones_fijas" and p.elemento_id == fija_id
        ]

    def cargar_elemento(self, elemento_id: int | None) -> None:
        fija = next((f for f in self._datos.asignaciones_fijas if f.id == elemento_id), None)
        if fija is None:
            # Elemento nuevo: se conservan las opciones elegidas para capturar varias seguidas.
            self._mostrar_problemas(None)
            return
        _poner(self.grupo, fija.grupo_id)
        _poner(self.asignatura, fija.asignatura_id)
        _poner(self.profesor, fija.profesor_id)
        _poner(self.dia, fija.dia)
        _poner(self.hora, fija.indice_franja)
        self._mostrar_problemas(fija.id)

    def _mostrar_problemas(self, fija_id: int | None, prefijo: str = "") -> None:
        """Muestra en rojo lo que la validación objeta de esta clase fija."""
        problemas = self._problemas(fija_id) if fija_id is not None else []
        if problemas:
            self.estado.setText(prefijo + "\n".join(f"⚠ {p.mensaje}" for p in problemas))
            self.estado.setStyleSheet("color: #C62828;")
        else:
            self.estado.setStyleSheet("")

    def guardar(self) -> bool:
        self.errores.limpiar()
        faltantes = [
            (campo, combo)
            for campo, combo in (
                ("grupo_id", self.grupo),
                ("asignatura_id", self.asignatura),
                ("dia", self.dia),
                ("indice_franja", self.hora),
            )
            if combo.currentData() is None
        ]
        for campo, _ in faltantes:
            self.errores.mostrar(campo, "Campo obligatorio")
        if faltantes:
            return False
        if not super().guardar():
            return False
        self._mostrar_problemas(self.actual_id, "Guardada, pero:\n")
        return True

    def guardar_elemento(self) -> int:
        assert self.repo is not None
        fija = self.repo.guardar_asignacion_fija(
            AsignacionFija(
                id=self.actual_id,
                grupo_id=self.grupo.currentData(),
                asignatura_id=self.asignatura.currentData(),
                profesor_id=self.profesor.currentData(),
                dia=self.dia.currentData(),
                indice_franja=self.hora.currentData(),
            )
        )
        assert fija.id is not None
        self._datos = self.repo.cargar_datos()
        return fija.id

    def eliminar_elemento(self, elemento_id: int) -> None:
        assert self.repo is not None
        self.repo.eliminar_asignacion_fija(elemento_id)
        self._datos = self.repo.cargar_datos()
