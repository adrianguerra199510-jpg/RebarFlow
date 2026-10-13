"""Imagen de una barra comercial con la secuencia de piezas que se cortan de ella.

Cada pieza es un tramo proporcional a su largo (color por largo distinto, con su medida en metros) y el retal
final se dibuja rayado: en verde si es reutilizable (≥ ``min_reusable_mm``) y en gris si es desperdicio.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from engine.cutting_optimizer import CutPattern

_PIECE_COLORS = ((31, 56, 100), (46, 117, 182), (68, 114, 196), (91, 155, 213), (48, 84, 150), (143, 170, 220))
_REUSABLE = (198, 224, 180)
_SCRAP = (217, 217, 217)
_OUTLINE = (89, 89, 89)
_OUTLINE_DARK = (170, 178, 192)
_SUPERSAMPLE = 3


def _text_color(fill: tuple[int, int, int]) -> tuple[int, int, int]:
    luminance = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    return (255, 255, 255) if luminance < 150 else (40, 40, 40)


def render_pattern_image(pattern: CutPattern, width: int, height: int, min_reusable_mm: float = 0.0,
                         dark: bool = False) -> Image.Image:
    ss = _SUPERSAMPLE
    w, h = width * ss, height * ss
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(8 * ss, round(h * 0.42)))
    margin = ss
    inner_w = w - 2 * margin
    scale = inner_w / pattern.stock_length_mm
    colors: dict[float, tuple[int, int, int]] = {}
    x = float(margin)
    for length in pattern.cuts:
        fill = colors.setdefault(length, _PIECE_COLORS[len(colors) % len(_PIECE_COLORS)])
        right = x + length * scale
        draw.rectangle((x, margin, right, h - margin), fill=fill, outline=(255, 255, 255), width=ss)
        text = f"{length / 1000:.2f}"
        text_w = draw.textlength(text, font=font)
        if right - x > text_w + 4 * ss:
            draw.text(((x + right) / 2, h / 2), text, fill=_text_color(fill), font=font, anchor="mm")
        x = right
    remnant = pattern.remnant_mm
    if remnant > 1e-6:
        fill = _REUSABLE if min_reusable_mm > 0 and remnant >= min_reusable_mm - 1e-6 else _SCRAP
        left, right = x, w - margin
        draw.rectangle((left, margin, right, h - margin), fill=fill)
        for offset in range(-h, int(right - left), 6 * ss):  # rayado diagonal
            draw.line((left + offset, h - margin, left + offset + h, margin), fill=(150, 150, 150), width=max(1, ss // 2))
        draw.rectangle((left, margin, right, h - margin), outline=(255, 255, 255), width=ss)
        text = f"{remnant / 1000:.2f}"
        if right - left > draw.textlength(text, font=font) + 4 * ss:
            draw.text(((left + right) / 2, h / 2), text, fill=(40, 40, 40), font=font, anchor="mm")
    draw.rectangle((margin, margin, w - margin, h - margin), outline=_OUTLINE_DARK if dark else _OUTLINE, width=ss)
    return image.resize((width, height), Image.LANCZOS)


@lru_cache(maxsize=1024)
def render_pattern_png(pattern: CutPattern, width: int = 420, height: int = 34, min_reusable_mm: float = 0.0,
                       dark: bool = False) -> bytes:
    """PNG (bytes) de la barra comercial cortada según ``pattern``; se guarda en caché."""
    buffer = BytesIO()
    render_pattern_image(pattern, width, height, min_reusable_mm, dark).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
