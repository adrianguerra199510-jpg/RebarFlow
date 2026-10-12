"""Icono de la aplicación: un estribo con ganchos de 135° en blanco sobre azul marino."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw
from PySide6.QtGui import QIcon, QPixmap

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
