"""Creado con Claude. Exportación de una solución a un libro de Excel listo para imprimir."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import xlsxwriter
from xlsxwriter.worksheet import Worksheet

from timetabling.dominio.cuadricula import (
    Cuadricula,
    cuadricula_espacio,
    cuadricula_grupo,
    cuadricula_profesor,
    espacios_usados,
)
from timetabling.dominio.estadisticas import carga_docente, penalizacion_total
from timetabling.dominio.modelos import (
    NOMBRES_DIAS,
    NOMBRES_PENALIZACIONES,
    DatosEscuela,
    Franja,
    Solucion,
)
from timetabling.exportacion.estilos import Estilos, configurar_impresion, nombre_hoja

FILA_INICIO = 2  # fila 0: título, fila 1: encabezado de días
ALTO_FRANJA = 42
ALTO_RECESO = 16
ALTO_PROPORCIONAL = 6


@dataclass(frozen=True)
class OpcionesExportacion:
    grupos: bool = True
    profesores: bool = True
    espacios: bool = True
    resumen: bool = True


class _Exportador:
    def __init__(
        self, datos: DatosEscuela, solucion: Solucion, franjas: list[Franja], ruta: Path
    ) -> None:
        self.datos = datos
        self.solucion = solucion
        self.franjas = franjas
        self.libro = xlsxwriter.Workbook(str(ruta))
        self.estilos = Estilos(self.libro)
        self.usados: set[str] = set()
        self.fecha = solucion.fecha.strftime("%d/%m/%Y %H:%M")
        self.escuela = datos.configuracion.nombre_escuela

    def hoja(self, nombre: str) -> Worksheet:
        return self.libro.add_worksheet(nombre_hoja(nombre, self.usados))

    # --- Hojas de horario -----------------------------------------------------------

    def escribir_cuadricula(self, nombre: str, cuadricula: Cuadricula) -> Worksheet:
        hoja = self.hoja(nombre)
        e = self.estilos
        columnas = len(cuadricula.columnas)
        ultima_col = columnas  # columna 0 = horas
        hoja.set_column(0, 0, 12)
        hoja.set_column(1, max(1, columnas), 22)
        if columnas:
            hoja.merge_range(0, 0, 0, ultima_col, cuadricula.titulo, e.titulo)
        else:
            hoja.write(0, 0, cuadricula.titulo, e.titulo)
        hoja.set_row(0, 22)
        hoja.write(1, 0, "Hora", e.encabezado)
        for c, dia in enumerate(cuadricula.columnas, start=1):
            hoja.write(1, c, NOMBRES_DIAS.get(dia, dia), e.encabezado)
        hoja.repeat_rows(1)
        hoja.hide_gridlines(2)  # la estructura la dan los bordes

        ocupadas: set[tuple[int, int]] = set()
        for bloque in cuadricula.bloques:
            for f in range(bloque.fila, bloque.fila + bloque.filas):
                ocupadas.add((f, bloque.columna))

        for i, fila in enumerate(cuadricula.filas):
            r = FILA_INICIO + i
            if fila.receso is not None:
                hoja.set_row(r, ALTO_RECESO)
                texto = f"{fila.receso} ({fila.etiqueta})"
                if columnas:
                    hoja.merge_range(r, 0, r, ultima_col, texto, e.receso)
                continue
            if cuadricula.proporcional:
                hoja.set_row(r, ALTO_PROPORCIONAL)
                if fila.inicio % 30 == 0:
                    alto = min(6, len(cuadricula.filas) - i)
                    if alto > 1:
                        hoja.merge_range(r, 0, r + alto - 1, 0, fila.etiqueta, e.hora_proporcional)
                    else:
                        hoja.write(r, 0, fila.etiqueta, e.hora_proporcional)
                vacio = e.vacio_media_hora if fila.inicio % 30 == 0 else e.vacio_proporcional
            else:
                hoja.set_row(r, ALTO_FRANJA)
                hoja.write(r, 0, fila.etiqueta, e.hora)
                vacio = e.vacio
            for c in range(columnas):
                if (i, c) not in ocupadas:
                    hoja.write_blank(r, c + 1, None, vacio)

        for bloque in cuadricula.bloques:
            texto = bloque.titulo + (f"\n{bloque.detalle}" if bloque.detalle else "")
            formato = e.clase(bloque.color, pequeno=cuadricula.proporcional)
            r0 = FILA_INICIO + bloque.fila
            r1 = r0 + bloque.filas - 1
            c = bloque.columna + 1
            if r1 > r0:
                hoja.merge_range(r0, c, r1, c, texto, formato)
            else:
                hoja.write(r0, c, texto, formato)

        configurar_impresion(
            hoja,
            self.escuela,
            cuadricula.titulo,
            self.fecha,
            FILA_INICIO + len(cuadricula.filas),
            ultima_col + 1,
        )
        return hoja

    def grupos(self) -> None:
        for grupo in self.datos.grupos:
            assert grupo.id is not None
            cuadricula = cuadricula_grupo(
                self.datos, self.franjas, self.solucion.asignaciones, grupo.id
            )
            self.escribir_cuadricula(self.datos.nombre_grupo(grupo), cuadricula)

    def profesores(self) -> None:
        for profesor in self.datos.profesores:
            assert profesor.id is not None
            if not any(a.profesor_id == profesor.id for a in self.solucion.asignaciones):
                continue
            cuadricula = cuadricula_profesor(
                self.datos, self.franjas, self.solucion.asignaciones, profesor.id
            )
            self.escribir_cuadricula(profesor.nombre, cuadricula)

    def espacios(self) -> None:
        for tipo, nivel_id in espacios_usados(self.datos):
            cuadricula = cuadricula_espacio(
                self.datos, self.franjas, self.solucion.asignaciones, tipo, nivel_id
            )
            self.escribir_cuadricula(f"{tipo} {self.datos.nivel(nivel_id).nombre}", cuadricula)

    # --- Hojas de resumen -----------------------------------------------------------

    def resumen(self) -> None:
        hoja = self.hoja("Resumen")
        e = self.estilos
        hoja.set_column(0, 0, 50)
        hoja.set_column(1, 3, 14)
        hoja.write(0, 0, "Resumen del horario", e.titulo)
        pesos = self.datos.configuracion.pesos
        total = penalizacion_total(self.solucion.penalizaciones, pesos)
        filas = [
            ("Escuela", self.escuela),
            ("Fecha de generación", self.fecha),
            ("Estado del solver", self.solucion.estado.value),
            ("Tiempo de cómputo (s)", round(self.solucion.tiempo_s, 1)),
            ("Penalización total ponderada", total),
        ]
        if self.solucion.nota:
            filas.append(("Nota", self.solucion.nota))
        for i, (clave, valor) in enumerate(filas, start=2):
            hoja.write(i, 0, clave, e.negrita)
            hoja.write(i, 1, valor)
        r = len(filas) + 3
        for c, texto in enumerate(["Restricción blanda", "Valor", "Peso", "Ponderado"]):
            hoja.write(r, c, texto, e.encabezado)
        valores_pesos = pesos.model_dump()
        incumplidas = []
        for clave, nombre in NOMBRES_PENALIZACIONES.items():
            r += 1
            valor = self.solucion.penalizaciones.get(clave, 0)
            peso = valores_pesos[clave]
            hoja.write(r, 0, nombre, e.celda)
            hoja.write(r, 1, valor, e.numero)
            hoja.write(r, 2, peso, e.numero)
            hoja.write(r, 3, valor * peso, e.numero)
            if valor > 0:
                incumplidas.append(f"{nombre}: {valor}")
        r += 2
        hoja.write(r, 0, "Restricciones blandas incumplidas", e.negrita)
        for texto in incumplidas or ["Ninguna"]:
            r += 1
            hoja.write(r, 0, texto)
        configurar_impresion(hoja, self.escuela, "Resumen", self.fecha, r + 1, 4)

    def carga_docente(self) -> None:
        hoja = self.hoja("CargaDocente")
        e = self.estilos
        encabezados = [
            "Profesor",
            "Minutos asignados",
            "Máximo",
            "Porcentaje",
            "Días con clase",
            "Huecos",
        ]
        hoja.set_column(0, 0, 28)
        hoja.set_column(1, len(encabezados) - 1, 14)
        for c, texto in enumerate(encabezados):
            hoja.write(0, c, texto, e.encabezado)
        cargas = carga_docente(self.datos, self.franjas, self.solucion.asignaciones)
        for r, carga in enumerate(cargas, start=1):
            hoja.write(r, 0, carga.nombre, e.celda)
            hoja.write(r, 1, carga.minutos, e.numero)
            hoja.write(r, 2, carga.maximo, e.numero)
            hoja.write(r, 3, carga.porcentaje / 100, e.porcentaje)
            hoja.write(r, 4, carga.dias, e.numero)
            hoja.write(r, 5, carga.huecos, e.numero)
        hoja.autofilter(0, 0, len(cargas), len(encabezados) - 1)
        hoja.freeze_panes(1, 0)
        configurar_impresion(
            hoja, self.escuela, "Carga docente", self.fecha, len(cargas) + 1, len(encabezados)
        )

    def leyenda(self) -> None:
        hoja = self.hoja("Leyenda")
        e = self.estilos
        hoja.set_column(0, 0, 32)
        hoja.set_column(1, 1, 10)
        hoja.write(0, 0, "Asignatura", e.encabezado)
        hoja.write(0, 1, "Color", e.encabezado)
        for r, asignatura in enumerate(self.datos.asignaturas, start=1):
            hoja.write(r, 0, asignatura.nombre, e.celda)
            hoja.write_blank(r, 1, None, e.muestra(asignatura.color))
        configurar_impresion(
            hoja, self.escuela, "Leyenda", self.fecha, len(self.datos.asignaturas) + 1, 2
        )


def exportar_excel(
    datos: DatosEscuela,
    solucion: Solucion,
    franjas: list[Franja],
    ruta: str | Path,
    opciones: OpcionesExportacion | None = None,
) -> Path:
    """Escribe el libro y devuelve su ruta. ``franjas`` son las franjas de todos los niveles."""
    opciones = opciones or OpcionesExportacion()
    ruta = Path(ruta)
    exportador = _Exportador(datos, solucion, franjas, ruta)
    if opciones.resumen:
        exportador.resumen()
    if opciones.grupos:
        exportador.grupos()
    if opciones.profesores:
        exportador.profesores()
    if opciones.espacios:
        exportador.espacios()
    if opciones.resumen:
        exportador.carga_docente()
    exportador.leyenda()
    exportador.libro.close()
    return ruta
