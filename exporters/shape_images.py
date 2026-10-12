"""Imágenes PNG de las formas de doblado, con sus cotas, para planillas e interfaz.

Una sola implementación alimenta las tres salidas (Excel, PDF y la interfaz gráfica), de modo
que la barra se vea igual en todas. El dibujo se hace sobrescalado y se reduce para suavizar
los bordes; el fondo es transparente.

Los rótulos se dibujan según su tipo: cotas de los tramos con su referencia de planilla (gris oscuro,
``A=400``), largo de la extensión de un gancho (ámbar, con prefijo «G») y ángulos de los dobleces (gris,
más pequeños). Las líneas de cota auxiliares (``guides``) van punteadas. El renderizador mide
cada texto y deja margen suficiente para que ninguno se corte en el borde de la imagen.
"""

from __future__ import annotations

import math
from functools import lru_cache
from itertools import pairwise
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
GUIDE_COLOR = (150, 150, 150, 255)

_SUPERSAMPLE = 4
_DIAGONAL = 0.4  # componente mínima en ambos ejes para colocar un rótulo en diagonal
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
    crowd = sum(1 for label in sketch.labels if label.kind == "dim")
    font_px = max(8 * ss, round(ref * 0.21 * (1.0 if crowd <= 5 else max(0.7, 1.0 - 0.07 * (crowd - 5)))))
    fonts = {"dim": ImageFont.load_default(size=font_px)}
    small = ImageFont.load_default(size=max(7 * ss, round(font_px * _SMALL_FONT)))
    fonts["hook"] = fonts["angle"] = small
    colors = {"dim": text_color, "hook": HOOK_COLOR, "angle": ANGLE_COLOR}
    line_w = max(3 * ss, round(ref * 0.05))
    gap = line_w // 2 + 3 * ss

    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    points = [p for path in (*sketch.paths, *sketch.guides) for p in path]
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

    def place(label: DimLabel, to_px, extra: float = 0.0) -> tuple[tuple[float, float, float, float], str, tuple[float, float]]:
        """Caja (x0, y0, x1, y1) del texto de un rótulo, su ancla de Pillow y su posición.

        Con el rótulo desplazado en diagonal (cotas de tramos inclinados, ángulos en un vértice) la esquina más
        cercana de la caja queda junto al punto, de modo que el texto no cruce el tramo; si no, se centra sobre
        el lado dominante. ``extra`` lo aleja más del punto, en su dirección, para esquivar otro rótulo.
        """
        x, y = to_px(label.at)
        sx, sy = label.side
        x, y = x + sx * extra, y - sy * extra
        if abs(sx) > _DIAGONAL and abs(sy) > _DIAGONAL:
            anchor = ("l" if sx > 0 else "r") + ("b" if sy > 0 else "t")
            pos = (x + math.copysign(gap, sx), y - math.copysign(gap, sy))
        elif abs(sy) >= abs(sx):
            anchor, pos = ("mb", (x, y - gap)) if sy > 0 else ("mt", (x, y + gap))
        else:
            anchor, pos = ("lm", (x + gap, y)) if sx > 0 else ("rm", (x - gap, y))
        # La caja es la de la tinta real del texto con ese ancla (la línea de texto es más alta que la tinta).
        return draw.textbbox(pos, label.text, font=fonts[label.kind], anchor=anchor), anchor, pos

    def layout(to_px) -> list[tuple[tuple[float, float, float, float], str, tuple[float, float]]]:
        """Posición de todos los rótulos; uno que pisaría a otro ya colocado se aleja de su punto en pasos."""
        placed: list[tuple[tuple[float, float, float, float], str, tuple[float, float]]] = []
        for label in sketch.labels:
            for k in range(7):
                item = place(label, to_px, k * font_px * 0.5)
                a = item[0]
                if not any(a[0] < b[0][2] and b[0][0] < a[2] and a[1] < b[0][3] and b[0][1] < a[3] for b in placed):
                    break
            placed.append(item)
        return placed

    # Margen inicial pequeño; se agranda con cada texto que se saldría de la imagen.
    pad = {"l": 6.0 * ss, "r": 6.0 * ss, "t": 6.0 * ss, "b": 6.0 * ss}
    for _ in range(6):
        to_px = transform(pad)
        boxes = [item[0] for item in layout(to_px)]
        edge = 2.0 * ss  # los textos no deben tocar el borde de la imagen
        over = {"l": max([0.0] + [edge - b[0] for b in boxes]), "r": max([0.0] + [b[2] - (w - edge) for b in boxes]),
                "t": max([0.0] + [edge - b[1] for b in boxes]), "b": max([0.0] + [b[3] - (h - edge) for b in boxes])}
        if all(v < 0.5 for v in over.values()):
            break
        pad = {k: pad[k] + over[k] + 1.0 for k in pad}
    to_px = transform(pad)

    dash, blank = 6 * ss, 4 * ss
    for guide in sketch.guides:  # líneas de cota punteadas, bajo la barra
        pixels = [to_px(p) for p in guide]
        for (x0, y0), (x1, y1) in pairwise(pixels):
            length = math.hypot(x1 - x0, y1 - y0)
            for start in range(0, int(length), dash + blank):
                a, b = start / length, min(start + dash, length) / length
                draw.line((x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, x0 + (x1 - x0) * b, y0 + (y1 - y0) * b),
                          fill=GUIDE_COLOR, width=max(ss, line_w // 4))

    for path in sketch.paths:
        pixels = [to_px(p) for p in path]
        draw.line(pixels, fill=bar_color, width=line_w, joint="curve")
        for x, y in (pixels[0], pixels[-1]):  # extremos redondeados
            draw.ellipse((x - line_w / 2, y - line_w / 2, x + line_w / 2, y + line_w / 2), fill=bar_color)

    for label, (_, anchor, pos) in zip(sketch.labels, layout(to_px)):
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
