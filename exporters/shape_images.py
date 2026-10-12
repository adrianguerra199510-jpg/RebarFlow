"""Imágenes PNG de las formas de doblado, con sus cotas, para planillas e interfaz.

Una sola implementación alimenta las tres salidas (Excel, PDF y la interfaz gráfica), de modo
que la barra se vea igual en todas. El dibujo se hace sobrescalado y se reduce para suavizar
los bordes; el fondo es transparente.

Los rótulos se dibujan según su tipo: cotas de los tramos (gris oscuro), largo de la extensión de un
gancho (ámbar, con prefijo «G») y ángulos de los dobleces (gris, más pequeños). El renderizador mide
cada texto y deja margen suficiente para que ninguno se corte en el borde de la imagen.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from core.rebar import Rebar
from core.shape_codes import ShapeCode
from core.sketch import DimLabel, Sketch

#: Proporción ancho:alto de las celdas de esquema en las planillas (8:3).
ASPECT = 8 / 3
BAR_COLOR = (31, 56, 100, 255)
TEXT_COLOR = (70, 70, 70, 255)
HOOK_COLOR = (176, 85, 4, 255)
ANGLE_COLOR = (110, 110, 110, 255)

_SUPERSAMPLE = 4
_SMALL_FONT = 0.78  # los rótulos de gancho y de ángulo van algo más pequeños que las cotas


def render_sketch(sketch: Sketch, width: int, height: int, *, bar_color: tuple[int, ...] = BAR_COLOR,
                  text_color: tuple[int, ...] = TEXT_COLOR, ref_height: int | None = None) -> Image.Image:
    """Dibuja ``sketch`` en una imagen RGBA transparente de ``width`` x ``height`` píxeles.

    ``ref_height`` fija la altura de referencia que escala el texto y el trazo; por defecto la altura
    de la imagen con un tope de 150 px, para que los dibujos grandes no engrosen sin límite.
    """
    ss = _SUPERSAMPLE
    w, h = width * ss, height * ss
    ref = (ref_height or min(height, 150)) * ss
    font_px = max(8 * ss, round(ref * 0.21))
    fonts = {"dim": ImageFont.load_default(size=font_px)}
    small = ImageFont.load_default(size=max(7 * ss, round(font_px * _SMALL_FONT)))
    fonts["hook"] = fonts["angle"] = small
    colors = {"dim": text_color, "hook": HOOK_COLOR, "angle": ANGLE_COLOR}
    line_w = max(3 * ss, round(ref * 0.05))
    gap = line_w // 2 + 3 * ss

    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    points = [p for path in sketch.paths for p in path]
    min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
    min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
    span_x, span_y = max_x - min_x, max_y - min_y

    def transform(pad: dict[str, float]):
        avail_w, avail_h = w - pad["l"] - pad["r"], h - pad["t"] - pad["b"]
        scale = min(avail_w / span_x if span_x > 1e-9 else float("inf"),
                    avail_h / span_y if span_y > 1e-9 else float("inf"))
        left = pad["l"] + (avail_w - span_x * scale) / 2
        bottom = pad["b"] + (avail_h - span_y * scale) / 2
        return lambda p: (left + (p[0] - min_x) * scale, h - bottom - (p[1] - min_y) * scale)

    def box(label: DimLabel, to_px) -> tuple[float, float, float, float]:
        """Caja (x0, y0, x1, y1) que ocupará el texto del rótulo, y su ancla."""
        x, y = to_px(label.at)
        left, top, right, bottom = draw.textbbox((0, 0), label.text, font=fonts[label.kind], anchor="lt")
        tw, th = right - left, bottom - top
        sx, sy = label.side
        if abs(sy) >= abs(sx):
            return (x - tw / 2, y - gap - th, x + tw / 2, y - gap) if sy > 0 else (x - tw / 2, y + gap, x + tw / 2, y + gap + th)
        return (x + gap, y - th / 2, x + gap + tw, y + th / 2) if sx > 0 else (x - gap - tw, y - th / 2, x - gap, y + th / 2)

    # Margen inicial pequeño; se agranda con cada texto que se saldría de la imagen.
    pad = {"l": 6.0 * ss, "r": 6.0 * ss, "t": 6.0 * ss, "b": 6.0 * ss}
    for _ in range(6):
        to_px = transform(pad)
        boxes = [box(label, to_px) for label in sketch.labels]
        over = {"l": max([0.0] + [-b[0] for b in boxes]), "r": max([0.0] + [b[2] - w for b in boxes]),
                "t": max([0.0] + [-b[1] for b in boxes]), "b": max([0.0] + [b[3] - h for b in boxes])}
        if all(v < 0.5 for v in over.values()):
            break
        pad = {k: pad[k] + over[k] + 1.0 for k in pad}
    to_px = transform(pad)

    for path in sketch.paths:
        pixels = [to_px(p) for p in path]
        draw.line(pixels, fill=bar_color, width=line_w, joint="curve")
        for x, y in (pixels[0], pixels[-1]):  # extremos redondeados
            draw.ellipse((x - line_w / 2, y - line_w / 2, x + line_w / 2, y + line_w / 2), fill=bar_color)

    for label in sketch.labels:
        x, y = to_px(label.at)
        sx, sy = label.side
        if abs(sy) >= abs(sx):
            anchor, pos = ("mb", (x, y - gap)) if sy > 0 else ("mt", (x, y + gap))
        else:
            anchor, pos = ("lm", (x + gap, y)) if sx > 0 else ("rm", (x - gap, y))
        draw.text(pos, label.text, fill=colors[label.kind], font=fonts[label.kind], anchor=anchor)

    return image.resize((width, height), Image.LANCZOS)


@lru_cache(maxsize=2048)
def render_shape_png(shape: ShapeCode, width: int = 320, height: int = 120, rebar: Rebar | None = None) -> bytes:
    """PNG (bytes) del esquema de ``shape``; con ``rebar`` rotula también el largo de los ganchos.

    Se guarda en caché por forma, tamaño y barra.
    """
    buffer = BytesIO()
    render_sketch(shape.sketch(rebar), width, height).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
