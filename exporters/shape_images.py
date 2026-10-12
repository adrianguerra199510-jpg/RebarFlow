"""Imágenes PNG de las formas de doblado, con sus cotas, para planillas e interfaz.

Una sola implementación alimenta las tres salidas (Excel, PDF y la interfaz gráfica), de modo
que la barra se vea igual en todas. El dibujo se hace sobrescalado y se reduce para suavizar
los bordes; el fondo es transparente.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from core.shape_codes import ShapeCode
from core.sketch import Sketch

#: Proporción ancho:alto de las celdas de esquema en las planillas (8:3).
ASPECT = 8 / 3
BAR_COLOR = (31, 56, 100, 255)
TEXT_COLOR = (70, 70, 70, 255)

_SUPERSAMPLE = 4


def render_sketch(sketch: Sketch, width: int, height: int) -> Image.Image:
    """Dibuja ``sketch`` en una imagen RGBA transparente de ``width`` x ``height`` píxeles."""
    ss = _SUPERSAMPLE
    w, h = width * ss, height * ss
    ref = min(height, 150) * ss  # los dibujos grandes no agrandan sin límite el texto ni el trazo
    font_px = max(8 * ss, round(ref * 0.21))
    font = ImageFont.load_default(size=font_px)
    line_w = max(3 * ss, round(ref * 0.05))
    gap = line_w // 2 + 3 * ss

    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Márgenes necesarios para los rótulos de cada lado.
    pad = {"l": 6 * ss, "r": 6 * ss, "t": 6 * ss, "b": 6 * ss}
    for label in sketch.labels:
        text_w = draw.textlength(label.text, font=font)
        sx, sy = label.side
        if sx > 0.5:
            pad["r"] = max(pad["r"], text_w + gap + 2 * ss)
        elif sx < -0.5:
            pad["l"] = max(pad["l"], text_w + gap + 2 * ss)
        if sy > 0.5:
            pad["t"] = max(pad["t"], font_px + gap)
        elif sy < -0.5:
            pad["b"] = max(pad["b"], font_px + gap)

    points = [p for path in sketch.paths for p in path]
    min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
    min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
    span_x, span_y = max_x - min_x, max_y - min_y
    avail_w, avail_h = w - pad["l"] - pad["r"], h - pad["t"] - pad["b"]
    candidates = [avail_w / span_x if span_x > 1e-9 else float("inf"),
                  avail_h / span_y if span_y > 1e-9 else float("inf")]
    scale = min(candidates)
    left = pad["l"] + (avail_w - span_x * scale) / 2
    bottom = pad["b"] + (avail_h - span_y * scale) / 2

    def to_px(point: tuple[float, float]) -> tuple[float, float]:
        return left + (point[0] - min_x) * scale, h - bottom - (point[1] - min_y) * scale

    for path in sketch.paths:
        pixels = [to_px(p) for p in path]
        draw.line(pixels, fill=BAR_COLOR, width=line_w, joint="curve")
        for x, y in (pixels[0], pixels[-1]):  # extremos redondeados
            draw.ellipse((x - line_w / 2, y - line_w / 2, x + line_w / 2, y + line_w / 2), fill=BAR_COLOR)

    for label in sketch.labels:
        x, y = to_px(label.at)
        sx, sy = label.side
        if abs(sy) >= abs(sx):
            anchor, pos = ("mb", (x, y - gap)) if sy > 0 else ("mt", (x, y + gap))
        else:
            anchor, pos = ("lm", (x + gap, y)) if sx > 0 else ("rm", (x - gap, y))
        draw.text(pos, label.text, fill=TEXT_COLOR, font=font, anchor=anchor)

    return image.resize((width, height), Image.LANCZOS)


@lru_cache(maxsize=1024)
def render_shape_png(shape: ShapeCode, width: int = 320, height: int = 120) -> bytes:
    """PNG (bytes) del esquema de ``shape``. Se guarda en caché por forma y tamaño."""
    buffer = BytesIO()
    render_sketch(shape.sketch(), width, height).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
