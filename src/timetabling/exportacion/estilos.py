"""Creado con Claude. Formatos de XlsxWriter, nombres de hoja y configuración de impresión."""

from __future__ import annotations

import re
from typing import Any

from xlsxwriter.format import Format
from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from timetabling.dominio.colores import color_texto

GRIS_RECESO = "#D9D9D9"
FONDO_ENCABEZADO = "#DCE6F1"
_PROHIBIDOS = re.compile(r"[\[\]:*?/\\]")
MAX_NOMBRE_HOJA = 31


def nombre_hoja(nombre: str, usados: set[str]) -> str:
    """Nombre válido para Excel: sin ``[]:*?/\\``, ≤ 31 caracteres, sin apóstrofo en los
    extremos y único (sin distinguir mayúsculas). Registra el nombre en ``usados``."""
    base = _PROHIBIDOS.sub("_", nombre).strip().strip("'") or "Hoja"
    base = base[:MAX_NOMBRE_HOJA]
    candidato, n = base, 2
    while candidato.lower() in usados:
        sufijo = f" ({n})"
        candidato = base[: MAX_NOMBRE_HOJA - len(sufijo)] + sufijo
        n += 1
    usados.add(candidato.lower())
    return candidato


def _escapar(texto: str) -> str:
    """Escapa ``&`` para los encabezados y pies de impresión."""
    return texto.replace("&", "&&")


class Estilos:
    """Fábrica de formatos con caché (XlsxWriter no deduplica formatos)."""

    def __init__(self, libro: Workbook) -> None:
        self.libro = libro
        self._cache: dict[tuple[tuple[str, Any], ...], Format] = {}
        self.titulo = self._nuevo(bold=True, font_size=14)
        self.encabezado = self._nuevo(
            bold=True,
            bg_color=FONDO_ENCABEZADO,
            border=1,
            align="center",
            valign="vcenter",
            text_wrap=True,
        )
        self.hora = self._nuevo(
            bold=True, border=1, align="center", valign="vcenter", font_size=9, text_wrap=True
        )
        self.hora_proporcional = self._nuevo(
            border=1, align="right", valign="top", font_size=8, bottom=0, top=1
        )
        self.receso = self._nuevo(
            bg_color=GRIS_RECESO,
            border=1,
            align="center",
            valign="vcenter",
            italic=True,
            font_size=9,
        )
        self.vacio = self._nuevo(border=1)
        self.vacio_proporcional = self._nuevo(left=1, right=1)
        # Primera fila de cada media hora: línea tenue que marca la escala de tiempo.
        self.vacio_media_hora = self._nuevo(left=1, right=1, top=1, top_color="#BFBFBF")
        self.texto = self._nuevo(text_wrap=True, valign="top")
        self.negrita = self._nuevo(bold=True)
        self.celda = self._nuevo(border=1)
        self.numero = self._nuevo(border=1, num_format="#,##0")
        self.porcentaje = self._nuevo(border=1, num_format="0.0%")

    def _nuevo(self, **propiedades: Any) -> Format:
        clave = tuple(sorted(propiedades.items()))
        if clave not in self._cache:
            self._cache[clave] = self.libro.add_format(propiedades)
        return self._cache[clave]

    def clase(self, color: str, pequeno: bool = False) -> Format:
        """Celda de una clase: fondo del color de la asignatura y texto en contraste."""
        return self._nuevo(
            bg_color=color,
            font_color=color_texto(color),
            border=1,
            align="center",
            valign="vcenter",
            text_wrap=True,
            font_size=8 if pequeno else 9,
        )

    def muestra(self, color: str) -> Format:
        return self._nuevo(bg_color=color, border=1)


def configurar_impresion(
    hoja: Worksheet, escuela: str, titulo_hoja: str, fecha: str, filas: int, columnas: int
) -> None:
    """Horizontal, carta, ajuste a una página, márgenes estrechos, encabezado y pie."""
    hoja.set_landscape()
    hoja.set_paper(1)  # carta
    hoja.fit_to_pages(1, 1)
    hoja.set_margins(left=0.25, right=0.25, top=0.6, bottom=0.6)
    hoja.set_header(f"&L&B{_escapar(escuela)}&R{_escapar(titulo_hoja)}", {"margin": 0.25})
    hoja.set_footer(f"&LGenerado: {_escapar(fecha)}&RPágina &P de &N", {"margin": 0.25})
    hoja.print_area(0, 0, max(0, filas - 1), max(0, columnas - 1))
    hoja.center_horizontally()
