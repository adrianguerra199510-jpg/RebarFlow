"""Tablas de la interfaz: planilla de barras (con esquemas) y resumen consolidado."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from engine.bbs_calculator import BBSResult, ElementSchedule, ScheduleLine
from gui.widgets import shape_pixmap

IMG_W, IMG_H = 160, 60
_BAND = QColor("#D9E1F2")
_SUBTOTAL = QColor("#F2F2F2")
_NAVY = QColor("#1F3864")
_RED = QColor("#C00000")

_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_CENTER = Qt.AlignmentFlag.AlignCenter


def _item(text: object, align=_LEFT, *, bold: bool = False, fg: QColor | None = None, bg: QColor | None = None):
    item = QTableWidgetItem(str(text))
    item.setTextAlignment(align)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if bold:
        font = QFont(item.font())
        font.setBold(True)
        item.setFont(font)
    if fg is not None:
        item.setForeground(QBrush(fg))
    if bg is not None:
        item.setBackground(QBrush(bg))
    return item


class ScheduleTable(QTableWidget):
    """Planilla de barras con el esquema de cada forma.

    Con ``grouped=True`` agrupa por elemento (fila de título y subtotal) y añade el total general;
    con ``grouped=False`` muestra las barras de un solo elemento.
    """

    FIXED = ["Marca", "Barra", "Ø (mm)", "Esquema", "Forma"]
    TAIL = ["Cant. por elem.", "Total barras", "Long. corte (mm)", "Peso unit. (kg)", "Long. total (m)",
            "Peso total (kg)", "Observaciones"]
    _HEADER_BREAKS = {"Cant. por elem.": "Cant.\npor elem.", "Total barras": "Total\nbarras",
                      "Long. corte (mm)": "Long. corte\n(mm)", "Peso unit. (kg)": "Peso unit.\n(kg)",
                      "Long. total (m)": "Long. total\n(m)", "Peso total (kg)": "Peso total\n(kg)"}

    def __init__(self, grouped: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grouped = grouped
        self._lines: dict[int, ScheduleLine] = {}
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setIconSize(QSize(IMG_W, IMG_H))
        self.setShowGrid(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def line_for_row(self, row: int) -> ScheduleLine | None:
        return self._lines.get(row)

    def row_of(self, mark: str) -> int | None:
        return next((row for row, line in self._lines.items() if line.mark == mark), None)

    def populate(self, schedules: Sequence[ElementSchedule], dim_labels: list[str]) -> None:
        headers = self.FIXED + dim_labels + self.TAIL
        col = {name: i for i, name in enumerate(headers)}
        n_cols = len(headers)
        self.clear()
        self._lines = {}
        self.setColumnCount(n_cols)
        self.setHorizontalHeaderLabels([self._HEADER_BREAKS.get(h, h) for h in headers])
        self.clearSpans()

        n_rows = sum(len(s.lines) + (2 if self.grouped else 1) for s in schedules) + (1 if self.grouped and schedules else 0)
        self.setRowCount(n_rows)
        row = 0
        for schedule in schedules:
            element = schedule.element
            if self.grouped:
                band = f"{element.name}  ·  {element.element_type.value}  ·  {element.level}  ·  {element.quantity} und"
                self.setSpan(row, 0, 1, n_cols)
                self.setItem(row, 0, _item(band, bold=True, bg=_BAND))
                self.setRowHeight(row, 26)
                row += 1
            for line in schedule.lines:
                self._fill_line(row, line, col, dim_labels)
                self._lines[row] = line
                row += 1
            self.setSpan(row, 0, 1, col["Total barras"] + 1)
            self.setItem(row, 0, _item(f"Subtotal {element.name}", _RIGHT, bold=True, bg=_SUBTOTAL))
            self._fill_totals(row, col, schedule.total_length_m, schedule.total_weight_kg, _SUBTOTAL, None)
            self.setRowHeight(row, 26)
            row += 1
        if self.grouped and schedules:
            length = sum(s.total_length_m for s in schedules)
            weight = sum(s.total_weight_kg for s in schedules)
            self.setSpan(row, 0, 1, col["Total barras"] + 1)
            self.setItem(row, 0, _item("TOTAL GENERAL", _RIGHT, bold=True, fg=QColor("white"), bg=_NAVY))
            self._fill_totals(row, col, length, weight, _NAVY, QColor("white"))
            self.setRowHeight(row, 28)

        widths = {"Marca": 60, "Barra": 54, "Ø (mm)": 66, "Esquema": IMG_W + 16, "Forma": 58, "Cant. por elem.": 76,
                  "Total barras": 66, "Long. corte (mm)": 92, "Peso unit. (kg)": 84, "Long. total (m)": 88,
                  "Peso total (kg)": 88}
        for name, index in col.items():
            self.setColumnWidth(index, widths.get(name, 58))  # cotas A, B, C: 58
        header = self.horizontalHeader()
        header.setSectionResizeMode(col["Observaciones"], QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(44)
        header.setFixedHeight(42)

    def _fill_line(self, row: int, line: ScheduleLine, col: dict[str, int], dim_labels: list[str]) -> None:
        dims = line.shape.dimensions()
        self.setRowHeight(row, IMG_H + 8)
        self.setItem(row, col["Marca"], _item(line.mark, _CENTER, bold=True))
        self.setItem(row, col["Barra"], _item(line.rebar.designation, _CENTER))
        self.setItem(row, col["Ø (mm)"], _item(f"{line.rebar.diameter_mm:.1f}", _CENTER))
        picture = _item("", _CENTER)
        picture.setIcon(QIcon(shape_pixmap(line.shape, IMG_W, IMG_H)))
        self.setItem(row, col["Esquema"], picture)
        self.setItem(row, col["Forma"], _item(line.shape.code, _CENTER, bold=True))
        for label in dim_labels:
            self.setItem(row, col[label], _item(f"{dims[label]:,.0f}" if label in dims else "", _RIGHT))
        self.setItem(row, col["Cant. por elem."], _item(line.group.quantity, _CENTER))
        self.setItem(row, col["Total barras"], _item(f"{line.total_bars:,}", _CENTER))
        self.setItem(row, col["Long. corte (mm)"], _item(f"{line.cut_length_mm:,.0f}", _RIGHT))
        self.setItem(row, col["Peso unit. (kg)"], _item(f"{line.unit_weight_kg:,.2f}", _RIGHT))
        self.setItem(row, col["Long. total (m)"], _item(f"{line.total_length_m:,.2f}", _RIGHT))
        self.setItem(row, col["Peso total (kg)"], _item(f"{line.total_weight_kg:,.2f}", _RIGHT, bold=True))
        remark = "\n".join(list(line.notes) + [f"AVISO: {w}" for w in line.warnings])
        self.setItem(row, col["Observaciones"], _item(remark, fg=_RED if line.warnings else None))

    def _fill_totals(self, row: int, col: dict[str, int], length: float, weight: float, bg: QColor,
                     fg: QColor | None) -> None:
        for name, index in col.items():
            if index > col["Total barras"]:
                self.setItem(row, index, _item("", bg=bg))
        self.setItem(row, col["Long. total (m)"], _item(f"{length:,.2f}", _RIGHT, bold=True, fg=fg, bg=bg))
        self.setItem(row, col["Peso total (kg)"], _item(f"{weight:,.2f}", _RIGHT, bold=True, fg=fg, bg=bg))


def _wrap_header(text: str) -> str:
    """Parte una cabecera larga en dos líneas: antes del paréntesis o en el espacio más cercano al centro."""
    if "\n" in text or len(text) <= 10:
        return text
    if "(" in text:
        return text.replace(" (", "\n(", 1)
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if not spaces:
        return text
    cut = min(spaces, key=lambda i: abs(i - len(text) / 2))
    return text[:cut] + "\n" + text[cut + 1:]


def _data_table(headers: list[str], rows: list[list[str]], total: list[str]) -> QTableWidget:
    table = QTableWidget(len(rows) + 1, len(headers))
    table.setHorizontalHeaderLabels([_wrap_header(h) for h in headers])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setFixedHeight(42)
    table.horizontalHeader().setStyleSheet("QHeaderView::section { font-size: 9pt; }")
    for r, values in enumerate(rows + [total]):
        is_total = r == len(rows)
        for c, value in enumerate(values):
            table.setItem(r, c, _item(value, _LEFT if c == 0 else _RIGHT, bold=is_total, bg=_SUBTOTAL if is_total else None))
        table.setRowHeight(r, 26)
    table.setFixedHeight(42 + 26 * (len(rows) + 1) + 4)
    return table


class SummaryView(QScrollArea):
    """Resumen consolidado: peso por diámetro, desperdicio de corte y totales por nivel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.populate(None)

    def populate(self, result: BBSResult | None) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 10, 14, 14)
        layout.setSpacing(6)
        if result is None or not result.diameter_summaries:
            layout.addWidget(QLabel("Aún no hay barras que resumir. Agregue elementos y barras."))
            layout.addStretch(1)
            self.setWidget(body)
            return

        summaries = result.diameter_summaries
        n = lambda v, d=2: f"{v:,.{d}f}"  # noqa: E731

        def section(text: str, table: QTableWidget) -> None:
            title = QLabel(text)
            title.setObjectName("sectionTitle")
            layout.addWidget(title)
            layout.addWidget(table)

        section("1. Peso neto por diámetro", _data_table(
            ["Barra", "Ø (mm)", "Grado", "Masa (kg/m)", "Total barras", "Long. total (m)", "Peso neto (kg)", "% del total"],
            [[s.rebar.designation, f"{s.rebar.diameter_mm:.1f}", s.rebar.grade.name, f"{s.rebar.linear_mass_kg_m:.3f}",
              n(s.total_bars, 0), n(s.total_length_m), n(s.total_weight_kg),
              f"{s.total_weight_kg / result.total_weight_kg:.1%}" if result.total_weight_kg else "0.0%"] for s in summaries],
            ["TOTAL", "", "", "", n(sum(s.total_bars for s in summaries), 0), n(result.total_length_m),
             n(result.total_weight_kg), "100.0%"],
        ))
        section(f"2. Desperdicio de corte (barras comerciales de {result.stock_length_mm / 1000:.2f} m)", _data_table(
            ["Barra", "Grado", "Barras comerciales", "Comprada (m)", "Long. útil (m)", "Desperdicio (m)",
             "Desperdicio (kg)", "Desperdicio (%)", "A comprar (kg)"],
            [[s.rebar.designation, s.rebar.grade.name, n(s.stock_bars, 0), n(s.purchased_length_m), n(s.total_length_m),
              n(s.waste_length_m), n(s.waste_weight_kg), f"{s.waste_pct:.1%}", n(s.purchase_weight_kg)] for s in summaries],
            ["TOTAL", "", n(sum(s.stock_bars for s in summaries), 0), n(sum(s.purchased_length_m for s in summaries)),
             n(result.total_length_m), n(sum(s.waste_length_m for s in summaries)), n(result.total_waste_weight_kg),
             f"{result.total_waste_pct:.1%}", n(result.total_purchase_weight_kg)],
        ))
        by_level = result.weight_by_level_and_diameter()
        multi_grade = len({s.rebar.designation for s in summaries}) != len(summaries)
        section("3. Consolidado por nivel (peso neto, kg)", _data_table(
            ["Barra", *result.levels, "Total"],
            [[f"{s.rebar.designation} · {s.rebar.grade.name}" if multi_grade else s.rebar.designation,
              *[n(by_level[level].get(s.rebar, 0.0)) for level in result.levels], n(s.total_weight_kg)] for s in summaries],
            ["TOTAL", *[n(sum(by_level[level].values())) for level in result.levels], n(result.total_weight_kg)],
        ))
        layout.addStretch(1)
        self.setWidget(body)
