"""Creado con Claude. Utilidades de color (contraste de texto sobre el color de una asignatura)."""

from __future__ import annotations


def luminancia(color: str) -> float:
    """Luminancia relativa WCAG de un color ``#RRGGBB``."""
    canales = []
    for i in (1, 3, 5):
        c = int(color[i : i + 2], 16) / 255
        canales.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = canales
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def color_texto(fondo: str) -> str:
    """Negro o blanco, el que tenga mayor contraste sobre ``fondo``."""
    lum = luminancia(fondo)
    contraste_negro = (lum + 0.05) / 0.05
    contraste_blanco = 1.05 / (lum + 0.05)
    return "#000000" if contraste_negro >= contraste_blanco else "#FFFFFF"
