"""Creado con Claude. Editor de disponibilidad: cuadrícula semanal de intervalos de 15 min.

El usuario arrastra para marcar un rectángulo (días × horas) como ``disponible`` o
``preferible_no``, o para borrarlo. En tono tenue se superponen las franjas de los niveles
que atiende el profesor, como referencia: una banda de color por nivel en el borde
izquierdo de cada día, con un segmento por franja.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from timetabling.dominio.modelos import (
    DIAS_SEMANA,
    NOMBRES_DIAS,
    Disponibilidad,
    Franja,
    TipoDisponibilidad,
    a_hhmm,
)

INTERVALO = 15
COLORES = {
    TipoDisponibilidad.DISPONIBLE: QColor("#66BB6A"),
    TipoDisponibilidad.PREFERIBLE_NO: QColor("#FFB74D"),
}
_COLORES_NIVEL = [QColor("#1E88E5"), QColor("#8E24AA"), QColor("#00897B"), QColor("#F4511E")]

Celda = tuple[str, int]  # (día, índice de intervalo)
ANCHO_BANDA = 5


class EditorDisponibilidad(QWidget):
    cambiado = Signal()

    MARGEN_IZQ = 48
    ALTO_ENCABEZADO = 22
    ALTO_CELDA = 11

    def __init__(self) -> None:
        super().__init__()
        self.dias: list[str] = list(DIAS_SEMANA)
        self.inicio = 7 * 60
        self.fin = 15 * 60
        self.celdas: dict[Celda, TipoDisponibilidad] = {}
        self.referencia: list[tuple[int, Franja]] = []  # (índice de nivel, franja)
        self.modo: TipoDisponibilidad | None = TipoDisponibilidad.DISPONIBLE
        self.dia_actual: str = self.dias[0]
        self._origen: Celda | None = None
        self._antes: dict[Celda, TipoDisponibilidad] = {}
        self.setMouseTracking(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # --- Configuración --------------------------------------------------------------

    @property
    def intervalos(self) -> int:
        return (self.fin - self.inicio) // INTERVALO

    def configurar(self, dias: list[str], inicio: int, fin: int) -> None:
        """Fija los días y el rango horario (se redondea a múltiplos de 15 minutos)."""
        self.dias = dias or list(DIAS_SEMANA)
        self.inicio = (inicio // INTERVALO) * INTERVALO
        self.fin = max(self.inicio + INTERVALO, math.ceil(fin / INTERVALO) * INTERVALO)
        if self.dia_actual not in self.dias:
            self.dia_actual = self.dias[0]
        self.updateGeometry()
        self.update()

    def color_nivel(self, indice: int) -> QColor:
        return QColor(_COLORES_NIVEL[indice % len(_COLORES_NIVEL)])

    def poner_referencia(self, franjas_por_nivel: list[list[Franja]]) -> None:
        self.referencia = [(i, f) for i, lista in enumerate(franjas_por_nivel) for f in lista]
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - nombre de Qt
        return QSize(520, self.ALTO_ENCABEZADO + self.intervalos * self.ALTO_CELDA + 1)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - nombre de Qt
        return QSize(300, self.sizeHint().height())

    # --- Conversión con el dominio --------------------------------------------------

    def poner_disponibilidad(self, rangos: list[Disponibilidad]) -> None:
        """Marca los intervalos completamente cubiertos por cada rango. ``preferible_no``
        tiene prioridad donde se superponen."""
        self.celdas = {}
        orden = sorted(rangos, key=lambda r: r.tipo == TipoDisponibilidad.PREFERIBLE_NO)
        for rango in orden:
            if rango.dia not in self.dias:
                continue
            primero = math.ceil((rango.inicio - self.inicio) / INTERVALO)
            ultimo = (rango.fin - self.inicio) // INTERVALO
            for k in range(max(0, primero), min(self.intervalos, ultimo)):
                self.celdas[(rango.dia, k)] = rango.tipo
        self.update()

    def disponibilidad(self) -> list[Disponibilidad]:
        """Rangos resultantes, fusionando intervalos contiguos del mismo tipo."""
        rangos: list[Disponibilidad] = []
        for dia in self.dias:
            k = 0
            while k < self.intervalos:
                tipo = self.celdas.get((dia, k))
                if tipo is None:
                    k += 1
                    continue
                inicio = k
                while k < self.intervalos and self.celdas.get((dia, k)) == tipo:
                    k += 1
                rangos.append(
                    Disponibilidad(
                        dia=dia,
                        inicio=self.inicio + inicio * INTERVALO,
                        fin=self.inicio + k * INTERVALO,
                        tipo=tipo,
                    )
                )
        return rangos

    # --- Edición --------------------------------------------------------------------

    def pintar(self, dia: str, inicio: int, fin: int, tipo: TipoDisponibilidad | None) -> None:
        """Marca (o borra, con ``tipo=None``) los intervalos de ``[inicio, fin)``."""
        primero = max(0, (inicio - self.inicio) // INTERVALO)
        ultimo = min(self.intervalos, math.ceil((fin - self.inicio) / INTERVALO))
        for k in range(primero, ultimo):
            self._marcar((dia, k), tipo)
        self.update()
        self.cambiado.emit()

    def _marcar(self, celda: Celda, tipo: TipoDisponibilidad | None) -> None:
        if tipo is None:
            self.celdas.pop(celda, None)
        else:
            self.celdas[celda] = tipo

    def copiar_dia_a_semana(self, dia: str | None = None) -> None:
        origen = dia or self.dia_actual
        for destino in self.dias:
            if destino == origen:
                continue
            for k in range(self.intervalos):
                self._marcar((destino, k), self.celdas.get((origen, k)))
        self.update()
        self.cambiado.emit()

    def limpiar(self) -> None:
        self.celdas = {}
        self.update()
        self.cambiado.emit()

    # --- Geometría ------------------------------------------------------------------

    def _ancho_dia(self) -> float:
        return max(1.0, (self.width() - self.MARGEN_IZQ - 1) / max(1, len(self.dias)))

    def _celda_en(self, punto: QPoint) -> Celda | None:
        x = punto.x() - self.MARGEN_IZQ
        y = punto.y() - self.ALTO_ENCABEZADO
        if x < 0 or y < 0:
            return None
        columna = int(x // self._ancho_dia())
        fila = int(y // self.ALTO_CELDA)
        if columna >= len(self.dias) or fila >= self.intervalos:
            return None
        return (self.dias[columna], fila)

    def _rect(self, columna: int, desde_min: int, hasta_min: int) -> QRectF:
        y0 = self.ALTO_ENCABEZADO + (desde_min - self.inicio) / INTERVALO * self.ALTO_CELDA
        y1 = self.ALTO_ENCABEZADO + (hasta_min - self.inicio) / INTERVALO * self.ALTO_CELDA
        x = self.MARGEN_IZQ + columna * self._ancho_dia()
        return QRectF(x, y0, self._ancho_dia(), y1 - y0)

    # --- Ratón ----------------------------------------------------------------------

    def mousePressEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - nombre de Qt
        celda = self._celda_en(evento.position().toPoint())
        if celda is None:
            return
        self._origen = celda
        self.dia_actual = celda[0]
        self._antes = dict(self.celdas)
        self._aplicar_rectangulo(celda)

    def mouseMoveEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - nombre de Qt
        if self._origen is None:
            return
        celda = self._celda_en(evento.position().toPoint())
        if celda is not None:
            self._aplicar_rectangulo(celda)

    def mouseReleaseEvent(self, evento: QMouseEvent) -> None:  # noqa: N802 - nombre de Qt
        if self._origen is not None:
            self._origen = None
            self.cambiado.emit()

    def _aplicar_rectangulo(self, hasta: Celda) -> None:
        assert self._origen is not None
        self.celdas = dict(self._antes)
        c0, c1 = sorted((self.dias.index(self._origen[0]), self.dias.index(hasta[0])))
        f0, f1 = sorted((self._origen[1], hasta[1]))
        for columna in range(c0, c1 + 1):
            for fila in range(f0, f1 + 1):
                self._marcar((self.dias[columna], fila), self.modo)
        self.update()

    # --- Dibujo ---------------------------------------------------------------------

    def paintEvent(self, evento: QPaintEvent) -> None:  # noqa: N802 - nombre de Qt
        pintor = QPainter(self)
        paleta = self.palette()
        pintor.fillRect(self.rect(), paleta.base())
        ancho = self._ancho_dia()
        texto = paleta.text().color()
        tenue = QColor(texto)
        tenue.setAlpha(40)

        # Celdas marcadas
        for (dia, k), tipo in self.celdas.items():
            if dia not in self.dias:
                continue
            rect = self._rect(
                self.dias.index(dia), self.inicio + k * INTERVALO, self.inicio + (k + 1) * INTERVALO
            )
            pintor.fillRect(rect, COLORES[tipo])

        # Franjas de referencia: una banda tenue por nivel en el borde izquierdo de cada
        # día, con un segmento por franja (no tapa la disponibilidad marcada).
        for indice_nivel, franja in self.referencia:
            if franja.dia not in self.dias:
                continue
            color = QColor(_COLORES_NIVEL[indice_nivel % len(_COLORES_NIVEL)])
            color.setAlpha(170)
            rect = self._rect(self.dias.index(franja.dia), franja.inicio, franja.fin)
            x = rect.left() + 2 + indice_nivel * (ANCHO_BANDA + 1)
            segmento = QRectF(x, rect.top() + 1, ANCHO_BANDA, rect.height() - 2)
            pintor.fillRect(segmento, color)

        # Rejilla y rótulos
        pintor.setPen(QPen(tenue, 1))
        for k in range(self.intervalos + 1):
            y = self.ALTO_ENCABEZADO + k * self.ALTO_CELDA
            minuto = self.inicio + k * INTERVALO
            if minuto % 60 == 0:
                pintor.setPen(QPen(texto, 1))
                pintor.drawText(
                    QRectF(0, y - 7, self.MARGEN_IZQ - 4, 14),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    a_hhmm(minuto),
                )
                linea = QColor(texto)
                linea.setAlpha(90)
                pintor.setPen(QPen(linea, 1))
            else:
                pintor.setPen(QPen(tenue, 1))
            pintor.drawLine(int(self.MARGEN_IZQ), int(y), int(self.width() - 1), int(y))
        for columna, dia in enumerate(self.dias):
            x = self.MARGEN_IZQ + columna * ancho
            pintor.setPen(QPen(tenue, 1))
            pintor.drawLine(int(x), self.ALTO_ENCABEZADO, int(x), self.height())
            pintor.setPen(QPen(texto, 1))
            fuente = pintor.font()
            fuente.setBold(dia == self.dia_actual)
            pintor.setFont(fuente)
            pintor.drawText(
                QRectF(x, 0, ancho, self.ALTO_ENCABEZADO),
                Qt.AlignmentFlag.AlignCenter,
                NOMBRES_DIAS.get(dia, dia),
            )
        pintor.end()
