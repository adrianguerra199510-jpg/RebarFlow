"""Iconos de la interfaz, dibujados en código (sin archivos de imagen) para que sigan el tema claro o nocturno.

Todos comparten un lenguaje: **el objeto** (hoja del proyecto, carpeta, disco, cubo del elemento, barra de acero doblada)
con contorno del color de tinta del tema, y **la acción** como una insignia (más verde = nuevo, lápiz = editar, cruz roja =
eliminar). Se dibujan sobre un lienzo de 64 × 64 y se rasterizan en varios tamaños; con :func:`icon` se obtiene un ``QIcon``
con su variante deshabilitada. La paleta se toma del tema activo al pedir el icono: tras cambiar de tema hay que volver a pedirlos.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from gui import style

_CANVAS = 64.0
_SIZES = (16, 20, 24, 32, 48, 64)
_DPR = 2  # los pixmaps se generan al doble de resolución para pantallas densas


@dataclass(frozen=True)
class Colors:
    ink: str  # contornos y trazos principales
    paper: str  # relleno de hojas y ventanas
    fold: str  # esquina doblada, caras claras
    green: str
    amber: str
    amber_dark: str
    blue: str
    red: str
    teal: str


LIGHT_COLORS = Colors(ink="#1F3864", paper="#FFFFFF", fold="#C9D6EE", green="#2E9E5B", amber="#F6BC4B",
                      amber_dark="#DB9120", blue="#2F6FDE", red="#D64545", teal="#1E8E86")
DARK_COLORS = Colors(ink="#B4C8F5", paper="#26324A", fold="#3C4D73", green="#4FD18B", amber="#F6BE5B",
                     amber_dark="#D9993A", blue="#6EA8FF", red="#FF7B7B", teal="#4FD1C5")


def _disabled(c: Colors, dark: bool) -> Colors:
    muted = "#5F6B80" if dark else "#A5AFC2"
    return Colors(ink=muted, paper=c.paper, fold=c.fold, green=muted, amber=muted, amber_dark=muted, blue=muted,
                  red=muted, teal=muted)


def _mix(a: str, b: str, t: float) -> str:
    """Color a ``t`` del camino de ``a`` hacia ``b`` (``#RRGGBB``)."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


# ------------------------------------------------------------------ primitivas
def _pen(color: str, width: float, *, flat: bool = False) -> QPen:
    cap = Qt.PenCapStyle.FlatCap if flat else Qt.PenCapStyle.RoundCap
    return QPen(QColor(color), width, Qt.PenStyle.SolidLine, cap, Qt.PenJoinStyle.RoundJoin)


def _polygon(points: list[tuple[float, float]]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def _page(p: QPainter, c: Colors, x: float = 13, y: float = 6, w: float = 34, h: float = 46, fold: float = 11,
          fill: str | None = None) -> None:
    """Hoja con la esquina superior derecha doblada."""
    body = QPainterPath()
    body.moveTo(x, y)
    body.lineTo(x + w - fold, y)
    body.lineTo(x + w, y + fold)
    body.lineTo(x + w, y + h)
    body.lineTo(x, y + h)
    body.closeSubpath()
    p.setPen(_pen(c.ink, 3))
    p.setBrush(QColor(fill or c.paper))
    p.drawPath(body)
    corner = QPainterPath()
    corner.moveTo(x + w - fold, y)
    corner.lineTo(x + w - fold, y + fold)
    corner.lineTo(x + w, y + fold)
    corner.closeSubpath()
    p.setBrush(QColor(c.fold))
    p.setPen(_pen(c.ink, 2.4))
    p.drawPath(corner)


def _text_lines(p: QPainter, c: Colors, x: float, y: float, w: float, rows: int = 3, gap: float = 6.5) -> None:
    p.setPen(_pen(_mix(c.ink, c.paper, 0.45), 2.6))
    for k in range(rows):
        p.drawLine(QPointF(x, y + gap * k), QPointF(x + w - (7 if k == rows - 1 else 0), y + gap * k))


def _badge(p: QPainter, c: Colors, color: str, glyph: str, cx: float = 46.5, cy: float = 46.5, r: float = 14.0) -> None:
    """Insignia redonda de acción en la esquina inferior derecha, con un aro del color de fondo para separarla."""
    p.setPen(_pen(c.paper, 3.2))
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen("#FFFFFF", 4.2))
    k = r * 0.42
    if glyph == "plus":
        p.drawLine(QPointF(cx - k, cy), QPointF(cx + k, cy))
        p.drawLine(QPointF(cx, cy - k), QPointF(cx, cy + k))
    elif glyph == "cross":
        k *= 0.82
        p.drawLine(QPointF(cx - k, cy - k), QPointF(cx + k, cy + k))
        p.drawLine(QPointF(cx - k, cy + k), QPointF(cx + k, cy - k))
    elif glyph == "check":
        p.drawPolyline(_polygon([(cx - k, cy + 0.1 * k), (cx - 0.25 * k, cy + 0.85 * k), (cx + k, cy - 0.8 * k)]))
    elif glyph == "info":
        p.setPen(_pen("#FFFFFF", 3.8))
        p.drawLine(QPointF(cx, cy - 0.15 * k), QPointF(cx, cy + 0.95 * k))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(cx, cy - 0.95 * k), 2.1, 2.1)
    elif glyph == "star":
        _star(p, cx, cy, r * 0.62, "#FFFFFF")


def _star(p: QPainter, cx: float, cy: float, r: float, color: str) -> None:
    points = []
    for k in range(10):
        radius = r if k % 2 == 0 else r * 0.45
        angle = math.radians(-90 + 36 * k)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(_polygon(points))


def _pencil(p: QPainter, c: Colors, cx: float = 44, cy: float = 44, scale: float = 1.0) -> None:
    """Lápiz con la punta hacia abajo a la izquierda, con un contorno del color de fondo."""
    p.save()
    p.translate(cx, cy)
    p.rotate(135)
    p.scale(scale, scale)
    body = QPainterPath()
    body.addRoundedRect(QRectF(-6, -5.5, 26, 11), 1.6, 1.6)
    tip = _polygon([(19, -5.5), (30, 0), (19, 5.5)])
    p.setPen(_pen(c.paper, 6.5))
    p.setBrush(QColor(c.paper))
    p.drawPath(body)
    p.drawPolygon(tip)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c.amber))
    p.drawPath(body)
    p.setBrush(QColor(_mix(c.red, c.paper, 0.15)))
    p.drawRoundedRect(QRectF(-6, -5.5, 6, 11), 1.6, 1.6)
    p.setBrush(QColor(c.fold))
    p.drawPolygon(tip)
    p.setBrush(QColor(c.ink))
    p.drawPolygon(_polygon([(26, -1.7), (30, 0), (26, 1.7)]))
    p.restore()


def _folder(p: QPainter, c: Colors) -> None:
    back = _polygon([(5, 14), (23, 14), (29, 21), (53, 21), (53, 51), (5, 51)])
    p.setPen(_pen(c.ink, 3))
    p.setBrush(QColor(c.amber_dark))
    p.drawPolygon(back)
    p.setBrush(QColor(c.amber))
    p.drawPolygon(_polygon([(5, 51), (12, 29), (60, 29), (53, 51)]))


def _disk(p: QPainter, c: Colors, x: float = 8, y: float = 8, size: float = 48) -> None:
    p.save()
    p.translate(x, y)
    p.scale(size / 48.0, size / 48.0)
    body = QPainterPath()
    body.moveTo(5, 0)
    body.lineTo(40, 0)
    body.lineTo(48, 8)
    body.lineTo(48, 43)
    body.quadTo(48, 48, 43, 48)
    body.lineTo(5, 48)
    body.quadTo(0, 48, 0, 43)
    body.lineTo(0, 5)
    body.quadTo(0, 0, 5, 0)
    p.setPen(_pen(c.ink, 3.2 * 48 / size if size < 48 else 3.2))
    p.setBrush(QColor(c.blue))
    p.drawPath(body)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c.paper))
    p.drawRoundedRect(QRectF(9, 26, 30, 18), 2, 2)
    p.setBrush(QColor(c.fold))
    p.drawRoundedRect(QRectF(11, 3, 24, 14), 2, 2)
    p.setBrush(QColor(c.ink))
    p.drawRoundedRect(QRectF(27, 5.5, 5, 9), 1.2, 1.2)
    p.setPen(_pen(_mix(c.ink, c.paper, 0.5), 2.2))
    p.drawLine(QPointF(14, 32), QPointF(34, 32))
    p.drawLine(QPointF(14, 38), QPointF(28, 38))
    p.restore()


def _cube(p: QPainter, c: Colors, cx: float = 32, cy: float = 31, r: float = 24) -> None:
    """Cubo isométrico: el elemento estructural."""
    h = r * 0.5
    w = r * 0.866
    top = [(cx, cy - r), (cx + w, cy - h), (cx, cy), (cx - w, cy - h)]
    left = [(cx - w, cy - h), (cx, cy), (cx, cy + r), (cx - w, cy + h)]
    right = [(cx, cy), (cx + w, cy - h), (cx + w, cy + h), (cx, cy + r)]
    p.setPen(_pen(c.ink, 2.8))
    for face, color in ((left, c.blue), (right, _mix(c.blue, c.ink, 0.38)), (top, _mix(c.blue, c.paper, 0.62))):
        p.setBrush(QColor(color))
        p.drawPolygon(_polygon(face))


def _bar(p: QPainter, c: Colors) -> None:
    """Barra de refuerzo doblada en L con gancho en la punta y estrías."""
    path = QPainterPath()
    path.moveTo(10, 50)
    path.lineTo(10, 17)
    path.lineTo(38, 17)
    path.lineTo(46, 25)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(c.ink, 9))
    p.drawPath(path)
    ribs = QPen(QColor(_mix(c.ink, c.paper, 0.78)), 9, Qt.PenStyle.CustomDashLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin)
    ribs.setDashPattern([0.22, 1.6])
    p.setPen(ribs)
    p.drawPath(path)


def _trash(p: QPainter, c: Colors) -> None:
    p.setPen(_pen(c.red, 3.4))
    p.setBrush(QColor(_mix(c.red, c.paper, 0.78)))
    body = QPainterPath()
    body.moveTo(16, 21)
    body.lineTo(19, 55)
    body.quadTo(19.3, 58, 22.3, 58)
    body.lineTo(41.7, 58)
    body.quadTo(44.7, 58, 45, 55)
    body.lineTo(48, 21)
    body.closeSubpath()
    p.drawPath(body)
    p.drawLine(QPointF(11, 16), QPointF(53, 16))
    p.drawPolyline(_polygon([(24, 16), (26, 8), (38, 8), (40, 16)]))
    p.setPen(_pen(c.red, 3))
    for x in (26, 32, 38):
        p.drawLine(QPointF(x, 27), QPointF(x + (x - 32) * 0.06, 50))


# ------------------------------------------------------------------ iconos
def _new_project(p: QPainter, c: Colors) -> None:
    _page(p, c)
    _text_lines(p, c, 20, 24, 20)
    _badge(p, c, c.green, "plus")


def _open_project(p: QPainter, c: Colors) -> None:
    _folder(p, c)


def _save_project(p: QPainter, c: Colors) -> None:
    _disk(p, c)


def _save_as(p: QPainter, c: Colors) -> None:
    _disk(p, c, 6, 6, 46)
    _pencil(p, c, 46, 46, 0.95)


def _save_all(p: QPainter, c: Colors) -> None:
    _disk(p, c, 14, 4, 40)
    _disk(p, c, 6, 16, 44)
    _badge(p, c, c.green, "check", 47, 48, 12)


def _edit_project(p: QPainter, c: Colors) -> None:
    _page(p, c)
    _text_lines(p, c, 20, 22, 20)
    _pencil(p, c, 44, 45, 1.05)


def _duplicate_project(p: QPainter, c: Colors) -> None:
    _page(p, c, 22, 5, 33, 40, 10, fill=c.fold)
    _page(p, c, 8, 18, 33, 40, 10)
    _text_lines(p, c, 14, 36, 20, rows=2)


def _close_project(p: QPainter, c: Colors) -> None:
    _page(p, c)
    _text_lines(p, c, 20, 24, 20)
    _badge(p, c, c.red, "cross")


def _sample(p: QPainter, c: Colors) -> None:
    _page(p, c)
    _text_lines(p, c, 20, 24, 20)
    _badge(p, c, c.amber_dark, "star")


def _catalog(p: QPainter, c: Colors) -> None:
    p.setPen(_pen(c.ink, 2.6))
    for (x, y), color in zip(((8, 8), (35, 8), (8, 35), (35, 35)), (c.blue, c.green, c.amber, c.teal)):
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(x, y, 21, 21), 4, 4)


def _bridge(p: QPainter, c: Colors) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(c.blue, 3.2))
    for y in (54, 59):
        p.drawLine(QPointF(5, y), QPointF(59, y))
    p.setPen(_pen(c.ink, 3.4))
    arch = QPainterPath()
    arch.moveTo(8, 36)
    arch.quadTo(32, 8, 56, 36)
    p.drawPath(arch)
    p.setPen(_pen(c.ink, 2.4))
    for x in (20, 32, 44):
        t = (x - 8) / 48.0
        y_arch = (1 - t) ** 2 * 36 + 2 * (1 - t) * t * 8 + t * t * 36
        p.drawLine(QPointF(x, y_arch), QPointF(x, 36))
    p.setPen(_pen(c.ink, 5))
    p.drawLine(QPointF(4, 38), QPointF(60, 38))
    p.setPen(_pen(c.ink, 4))
    for x in (14, 50):
        p.drawLine(QPointF(x, 40), QPointF(x, 52))


def _new_element(p: QPainter, c: Colors) -> None:
    _cube(p, c)
    _badge(p, c, c.green, "plus")


def _edit_element(p: QPainter, c: Colors) -> None:
    _cube(p, c)
    _pencil(p, c, 45, 45)


def _delete_element(p: QPainter, c: Colors) -> None:
    _cube(p, c)
    _badge(p, c, c.red, "cross")


def _new_bar(p: QPainter, c: Colors) -> None:
    _bar(p, c)
    _badge(p, c, c.green, "plus")


def _edit_bar(p: QPainter, c: Colors) -> None:
    _bar(p, c)
    _pencil(p, c, 46, 46)


def _delete_bar(p: QPainter, c: Colors) -> None:
    _bar(p, c)
    _badge(p, c, c.red, "cross")


def _excel(p: QPainter, c: Colors) -> None:
    _page(p, c)
    p.setPen(_pen(c.green, 2.2))
    p.setBrush(QColor(_mix(c.green, c.paper, 0.86)))
    p.drawRect(QRectF(19, 20, 22, 24))
    p.setBrush(QColor(c.green))
    p.drawRect(QRectF(19, 20, 22, 6.5))
    p.drawLine(QPointF(30, 26.5), QPointF(30, 44))
    p.drawLine(QPointF(19, 35), QPointF(41, 35))
    badge = QRectF(32, 34, 25, 25)
    p.setPen(_pen(c.paper, 3.2))
    p.setBrush(QColor(c.green))
    p.drawRoundedRect(badge, 6, 6)
    p.setPen(_pen("#FFFFFF", 4))
    k = 6.2
    cx, cy = badge.center().x(), badge.center().y()
    p.drawLine(QPointF(cx - k, cy - k), QPointF(cx + k, cy + k))
    p.drawLine(QPointF(cx - k, cy + k), QPointF(cx + k, cy - k))


def _pdf(p: QPainter, c: Colors) -> None:
    _page(p, c)
    _text_lines(p, c, 20, 20, 20, rows=2)
    band = QRectF(5, 30, 44, 20)
    p.setPen(_pen(c.paper, 3.2))
    p.setBrush(QColor(c.red))
    p.drawRoundedRect(band, 4, 4)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(15)
    p.setFont(font)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(band, Qt.AlignmentFlag.AlignCenter, "PDF")


def _detail(p: QPainter, c: Colors) -> None:
    window = QRectF(6, 9, 52, 44)
    p.setPen(_pen(c.ink, 3))
    p.setBrush(QColor(c.paper))
    p.drawRoundedRect(window, 5, 5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c.fold))
    p.drawRect(QRectF(37, 19.5, 19.5, 31.5))
    p.setBrush(QColor(c.ink))
    p.drawRect(QRectF(7.5, 10.5, 49, 8))
    p.setBrush(QColor(c.paper))
    for k in range(3):
        p.drawEllipse(QPointF(13 + 5.5 * k, 14.5), 1.6, 1.6)
    _text_lines(p, c, 12, 26, 20, rows=3, gap=7)
    _badge(p, c, c.blue, "info", 47, 44, 11.5)


def _chevron(direction: int) -> Callable[[QPainter, Colors], None]:
    def draw(p: QPainter, c: Colors) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.blue))
        p.drawEllipse(QPointF(32, 32), 25, 25)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen("#FFFFFF", 6))
        d = 7 * direction
        p.drawPolyline(_polygon([(32 - d, 19), (32 + d, 32), (32 - d, 45)]))
    return draw


def _project_node(p: QPainter, c: Colors) -> None:
    """Raíz del árbol: el proyecto (una carpeta de obra con su hoja)."""
    _folder(p, c)


def _group_node(p: QPainter, c: Colors) -> None:
    p.setPen(_pen(c.ink, 3))
    p.setBrush(QColor(_mix(c.fold, c.paper, 0.1)))
    p.drawPolygon(_polygon([(5, 15), (23, 15), (29, 22), (59, 22), (59, 50), (5, 50)]))
    p.setBrush(QColor(c.fold))
    p.drawPolygon(_polygon([(5, 50), (5, 28), (59, 28), (59, 50)]))


_DRAWINGS: dict[str, Callable[[QPainter, Colors], None]] = {
    "new_project": _new_project, "open_project": _open_project, "save_project": _save_project,
    "save_as": _save_as, "save_all": _save_all, "edit_project": _edit_project,
    "duplicate_project": _duplicate_project, "close_project": _close_project,
    "sample": _sample, "catalog": _catalog, "bridge": _bridge,
    "new_element": _new_element, "edit_element": _edit_element, "delete_element": _delete_element,
    "new_bar": _new_bar, "edit_bar": _edit_bar, "delete_bar": _delete_bar,
    "export_excel": _excel, "export_pdf": _pdf, "detail": _detail,
    "next_project": _chevron(1), "previous_project": _chevron(-1),
    "project": _project_node, "group": _group_node, "element": _cube,
}

NAMES = tuple(_DRAWINGS)


def render(name: str, size: int, *, dark: bool | None = None, enabled: bool = True) -> QPixmap:
    """Pixmap cuadrado de ``size`` × ``size`` píxeles lógicos (se genera a ``_DPR`` veces esa resolución)."""
    dark = style.current().dark if dark is None else dark
    colors = DARK_COLORS if dark else LIGHT_COLORS
    if not enabled:
        colors = _disabled(colors, dark)
    pixmap = QPixmap(size * _DPR, size * _DPR)
    pixmap.setDevicePixelRatio(_DPR)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                           | QPainter.RenderHint.SmoothPixmapTransform)
    painter.scale(size / _CANVAS, size / _CANVAS)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    try:
        _DRAWINGS[name](painter, colors)
    finally:
        painter.end()
    return pixmap


@lru_cache(maxsize=None)
def _icon(name: str, dark: bool) -> QIcon:
    icon = QIcon()
    for size in _SIZES:
        icon.addPixmap(render(name, size, dark=dark), QIcon.Mode.Normal)
        icon.addPixmap(render(name, size, dark=dark, enabled=False), QIcon.Mode.Disabled)
    return icon


def icon(name: str) -> QIcon:
    """Icono ``name`` con los colores del tema actual (y su variante deshabilitada)."""
    if name not in _DRAWINGS:
        raise KeyError(f"No hay un icono llamado {name!r}")
    return _icon(name, style.current().dark)

