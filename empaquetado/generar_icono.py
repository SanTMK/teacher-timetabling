"""Creado con Claude. Dibuja el ícono de la aplicación con Qt y lo guarda en varios formatos.

Genera:
* ``src/timetabling/recursos/icono.png`` (512 px, usado por la ventana en tiempo de ejecución)
* ``empaquetado/icono.icns`` (macOS, vía ``iconutil``) y ``empaquetado/icono.ico`` (Windows)

Uso: ``uv run python empaquetado/generar_icono.py``
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
COLORES = ["#E57373", "#64B5F6", "#81C784", "#FFB74D", "#BA68C8", "#4DB6AC", "#F06292"]
# Celdas ocupadas de la cuadrícula 5 × 4 (columna, fila, color)
CLASES = [
    (0, 0, 0),
    (1, 0, 1),
    (2, 0, 2),
    (4, 0, 3),
    (0, 1, 1),
    (2, 1, 4),
    (3, 1, 0),
    (1, 2, 5),
    (3, 2, 2),
    (4, 2, 6),
    (0, 3, 3),
    (2, 3, 5),
    (3, 3, 1),
]


def dibujar(tamano: int) -> QImage:
    imagen = QImage(tamano, tamano, QImage.Format.Format_ARGB32)
    imagen.fill(Qt.GlobalColor.transparent)
    p = QPainter(imagen)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = tamano / 1024

    # Fondo redondeado con degradado
    fondo = QRectF(64 * s, 64 * s, 896 * s, 896 * s)
    degradado = QLinearGradient(fondo.topLeft(), fondo.bottomRight())
    degradado.setColorAt(0, QColor("#2B5797"))
    degradado.setColorAt(1, QColor("#1B3A6B"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(degradado)
    p.drawRoundedRect(fondo, 190 * s, 190 * s)

    # Hoja del calendario
    hoja = QRectF(170 * s, 230 * s, 684 * s, 600 * s)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(hoja, 60 * s, 60 * s)
    p.setBrush(QColor("#C62828"))
    p.drawRoundedRect(QRectF(hoja.left(), hoja.top(), hoja.width(), 130 * s), 60 * s, 60 * s)
    p.drawRect(QRectF(hoja.left(), hoja.top() + 70 * s, hoja.width(), 60 * s))
    # Anillas
    p.setBrush(QColor("#ECEFF1"))
    for x in (330, 694):
        p.drawRoundedRect(QRectF((x - 28) * s, 170 * s, 56 * s, 120 * s), 28 * s, 28 * s)

    # Cuadrícula de clases
    margen, columnas, filas = 40 * s, 5, 4
    zona = QRectF(
        hoja.left() + margen,
        hoja.top() + 130 * s + margen,
        hoja.width() - 2 * margen,
        hoja.height() - 130 * s - 2 * margen,
    )
    hueco = 14 * s
    ancho = (zona.width() - hueco * (columnas - 1)) / columnas
    alto = (zona.height() - hueco * (filas - 1)) / filas
    p.setBrush(QColor("#ECEFF1"))
    for c in range(columnas):
        for f in range(filas):
            p.drawRoundedRect(
                QRectF(
                    zona.left() + c * (ancho + hueco), zona.top() + f * (alto + hueco), ancho, alto
                ),
                14 * s,
                14 * s,
            )
    for c, f, color in CLASES:
        p.setBrush(QColor(COLORES[color]))
        p.drawRoundedRect(
            QRectF(zona.left() + c * (ancho + hueco), zona.top() + f * (alto + hueco), ancho, alto),
            14 * s,
            14 * s,
        )
    p.end()
    return imagen


def main() -> int:
    QGuiApplication(sys.argv)
    recursos = RAIZ / "src" / "timetabling" / "recursos"
    recursos.mkdir(parents=True, exist_ok=True)
    dibujar(512).save(str(recursos / "icono.png"))
    dibujar(256).save(str(RAIZ / "empaquetado" / "icono.ico"), "ICO")

    if shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            conjunto = Path(tmp) / "icono.iconset"
            conjunto.mkdir()
            for base in (16, 32, 128, 256, 512):
                dibujar(base).save(str(conjunto / f"icon_{base}x{base}.png"))
                dibujar(base * 2).save(str(conjunto / f"icon_{base}x{base}@2x.png"))
            subprocess.run(
                [
                    "iconutil",
                    "-c",
                    "icns",
                    str(conjunto),
                    "-o",
                    str(RAIZ / "empaquetado" / "icono.icns"),
                ],
                check=True,
            )
    print("Íconos generados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
