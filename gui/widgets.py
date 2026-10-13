"""Widgets reutilizables: imágenes de formas, panel de detalle de una barra."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from core.rebar import Rebar
from core.shape_codes import ShapeCode
from engine.bbs_calculator import ScheduleLine
from engine.cutting_optimizer import CutPattern
from exporters.cutting_images import render_pattern_png
from exporters.shape_images import render_shape_png
from gui import style

_DPR = 2  # el PNG se genera al doble de resolución para que se vea nítido en pantallas densas


def shape_pixmap(shape: ShapeCode, width: int, height: int, rebar: Rebar | None = None) -> QPixmap:
    """Pixmap del esquema de ``shape`` de ``width`` x ``height`` píxeles lógicos (con ``rebar``, rotula los ganchos).

    Se dibuja con la paleta del tema actual (trazos claros en el modo nocturno)."""
    pixmap = QPixmap()
    pixmap.loadFromData(render_shape_png(shape, _DPR * width, _DPR * height, rebar, style.current().dark))
    pixmap.setDevicePixelRatio(_DPR)
    return pixmap


def pattern_pixmap(pattern: CutPattern, width: int, height: int, min_reusable_mm: float = 0.0) -> QPixmap:
    """Pixmap de una barra comercial cortada según ``pattern``."""
    pixmap = QPixmap()
    pixmap.loadFromData(render_pattern_png(pattern, _DPR * width, _DPR * height, min_reusable_mm, style.current().dark))
    pixmap.setDevicePixelRatio(_DPR)
    return pixmap


class ShapePreview(QLabel):
    """Etiqueta que muestra el esquema de una forma, o un texto si no hay forma válida."""

    def __init__(self, width: int = 420, height: int = 158, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = (width, height)
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("shapePreview")

    def set_shape(self, shape: ShapeCode | None, placeholder: str = "", rebar: Rebar | None = None) -> None:
        if shape is None:
            self.setPixmap(QPixmap())
            self.setText(placeholder)
        else:
            self.setText("")
            self.setPixmap(shape_pixmap(shape, *self._size, rebar))


def _row(label: str, value: str) -> str:
    return f"<tr><td style='color:{style.current().muted}; padding-right:10px'>{label}</td><td><b>{value}</b></td></tr>"


class BarDetailPanel(QFrame):
    """Panel lateral con el dibujo grande y el desglose del cálculo de la barra seleccionada."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.title = QLabel()
        self.title.setObjectName("detailTitle")
        self.preview = ShapePreview(340, 128)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setWordWrap(True)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.title)
        layout.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.details, stretch=1)
        self.show_line(None)

    def show_line(self, line: ScheduleLine | None) -> None:
        if line is None:
            self.title.setText("Detalle de barra")
            self.preview.set_shape(None, "Seleccione una barra\npara ver su esquema y el\ndesglose de la longitud de corte")
            self.details.setText("")
            return
        cut = line.group.cut
        dims = " · ".join(f"{k} = {v:,.0f}" for k, v in line.shape.dimensions().items())
        rows = [
            _row("Forma", escape(line.shape.label)),
            _row("Cotas (mm)", dims),
            _row("Σ cotas", f"{cut.dimension_sum_mm:,.1f} mm"),
            _row("Ajuste por dobleces", f"{cut.bend_adjustment_mm:+,.1f} mm"),
            _row("Ganchos (° · mm)", line.hook_text or "—"),
            _row("Extensiones de gancho", f"{cut.extension_mm:,.1f} mm"),
            *([_row("Couplers", escape(line.coupler_text))] if cut.couplers else []),
            _row("Longitud de corte", f"{cut.total_mm:,.1f} → {line.cut_length_mm:,.0f} mm"),
            _row("Peso unitario", f"{line.unit_weight_kg:,.2f} kg"),
            _row("Barras", f"{line.group.quantity} × {line.element.quantity} elem. = {line.total_bars}"),
            _row("Longitud / peso total", f"{line.total_length_m:,.2f} m · {line.total_weight_kg:,.2f} kg"),
        ]
        html = f"<table cellspacing='3'>{''.join(rows)}</table>"
        theme = style.current()
        html += "".join(f"<p style='color:{theme.muted}'>{escape(note)}</p>" for note in cut.notes)
        html += "".join(f"<p style='color:{theme.red}'><b>Aviso:</b> {escape(w)}</p>" for w in cut.warnings)
        if line.group.description:
            html += f"<p><i>{escape(line.group.description)}</i></p>"
        self.title.setText(f"Marca {escape(line.mark)}  ·  {escape(line.rebar.label)}  ·  {escape(line.rebar.grade.name)}")
        self.preview.set_shape(line.shape, rebar=line.rebar)
        self.details.setText(html)
