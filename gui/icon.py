"""Icono de la aplicación: un estribo con ganchos de 135° en blanco sobre azul marino."""

from __future__ import annotations

import math
from io import BytesIO

from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from core.shape_codes import Stirrup
from core.sketch import Sketch
from exporters.shape_images import render_sketch

_NAVY = (31, 56, 100, 255)
_WHITE = (255, 255, 255, 255)


def app_icon_image(size: int = 256) -> Image.Image:
    """Icono cuadrado RGBA de ``size`` píxeles."""
    master = 512
    icon = Image.new("RGBA", (master, master), (0, 0, 0, 0))
    ImageDraw.Draw(icon).rounded_rectangle((0, 0, master - 1, master - 1), radius=master // 5, fill=_NAVY)
    stirrup = Sketch(Stirrup(300, 300).sketch().paths)  # sin cotas
    inner = round(master * 0.62)
    drawing = render_sketch(stirrup, inner, inner, bar_color=_WHITE, ref_height=round(inner * 1.6))
    offset = (master - inner) // 2
    icon.alpha_composite(drawing, (offset, offset))
    return icon.resize((size, size), Image.LANCZOS)


def app_icon() -> QIcon:
    buffer = BytesIO()
    app_icon_image(256).save(buffer, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue())
    return QIcon(pixmap)


def theme_icon(to_dark: bool, size: int = 32) -> QIcon:
    """Icono del botón de tema: una luna (para pasar al modo nocturno) o un sol (para volver al diurno)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = size / 2.0
    if to_dark:  # luna creciente en azul marino
        color = QColor("#1F3864")
        moon = QPainterPath()
        moon.addEllipse(QPointF(c, c), size * 0.36, size * 0.36)
        cut = QPainterPath()
        cut.addEllipse(QPointF(c + size * 0.17, c - size * 0.12), size * 0.31, size * 0.31)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPath(moon.subtracted(cut))
    else:  # sol ámbar con ocho rayos
        color = QColor("#F4B740")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(c, c), size * 0.20, size * 0.20)
        painter.setPen(QPen(color, size * 0.075, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for k in range(8):
            a = math.radians(45 * k)
            painter.drawLine(QPointF(c + math.cos(a) * size * 0.32, c + math.sin(a) * size * 0.32),
                             QPointF(c + math.cos(a) * size * 0.44, c + math.sin(a) * size * 0.44))
    painter.end()
    return QIcon(pixmap)
