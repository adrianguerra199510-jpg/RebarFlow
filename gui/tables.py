"""Tablas de la interfaz: planilla de barras (con esquemas) y resumen consolidado."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from engine.bbs_calculator import BBSResult, ElementSchedule, LinePart, ScheduleLine
from engine.cutting_report import plan_rows, plan_title, stock_comparison
from gui import style
from gui.widgets import pattern_pixmap, shape_pixmap

IMG_W, IMG_H = 208, 78

_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_CENTER = Qt.AlignmentFlag.AlignCenter


def _color(name: str) -> QColor:
    """Color del tema actual (``band``, ``subtotal``, ``header``, ``red``, ``green``…)."""
    return QColor(getattr(style.current(), name))


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

    FIXED = ["Marca", "Barra", "Esquema"]
    TAIL = ["Cant. por elem.", "Total barras", "Long. corte (mm)", "Peso unit. (kg)", "Long. total (m)", "Peso total (kg)"]
    _HEADER_BREAKS = {"Cant. por elem.": "Cant.\npor elem.", "Total barras": "Total\nbarras",
                      "Long. corte (mm)": "Long. corte\n(mm)", "Peso unit. (kg)": "Peso unit.\n(kg)",
                      "Long. total (m)": "Long. total\n(m)", "Peso total (kg)": "Peso total\n(kg)"}

    def __init__(self, grouped: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grouped = grouped
        self._lines: dict[int, ScheduleLine] = {}
        self._parts: dict[int, LinePart] = {}
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setIconSize(QSize(IMG_W, IMG_H))
        self.setShowGrid(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def line_for_row(self, row: int) -> ScheduleLine | None:
        """Marca de la fila; en la fila de una sub-marca (``A1.1``), la marca que la reúne (``A1``)."""
        return self._lines.get(row)

    def part_for_row(self, row: int) -> LinePart | None:
        """Sub-marca de la fila, o ``None`` si es la fila de una marca."""
        return self._parts.get(row)

    def row_of(self, mark: str) -> int | None:
        return next((row for row, line in self._lines.items() if line.mark == mark), None)

    def populate(self, schedules: Sequence[ElementSchedule]) -> None:
        headers = self.FIXED + self.TAIL
        col = {name: i for i, name in enumerate(headers)}
        n_cols = len(headers)
        self.clear()
        self._lines = {}
        self._parts = {}
        self.setColumnCount(n_cols)
        self.setHorizontalHeaderLabels([self._HEADER_BREAKS.get(h, h) for h in headers])
        self.clearSpans()

        n_rows = sum(len(s.lines) + sum(len(line.parts) for line in s.lines) + (2 if self.grouped else 1) for s in schedules) + (1 if self.grouped and schedules else 0)
        self.setRowCount(n_rows)
        row = 0
        for schedule in schedules:
            element = schedule.element
            if self.grouped:
                band = element.heading
                self.setSpan(row, 0, 1, n_cols)
                self.setItem(row, 0, _item(band, bold=True, bg=_color("band")))
                self.setRowHeight(row, 26)
                row += 1
            for line in schedule.lines:
                self._fill_line(row, line, col)
                self._lines[row] = line
                row += 1
                for part in line.parts:  # sub-marcas: las barras en las que se divide la marca (A1.1, A1.2…)
                    self._fill_part(row, line, part, col)
                    self._lines[row] = line
                    self._parts[row] = part
                    row += 1
            self.setSpan(row, 0, 1, col["Total barras"] + 1)
            self.setItem(row, 0, _item(f"Subtotal {element.name}", _RIGHT, bold=True, bg=_color("subtotal")))
            self._fill_totals(row, col, schedule.total_length_m, schedule.total_weight_kg, _color("subtotal"), None)
            self.setRowHeight(row, 26)
            row += 1
        if self.grouped and schedules:
            length = sum(s.total_length_m for s in schedules)
            weight = sum(s.total_weight_kg for s in schedules)
            self.setSpan(row, 0, 1, col["Total barras"] + 1)
            self.setItem(row, 0, _item("TOTAL GENERAL", _RIGHT, bold=True, fg=QColor(style.current().header_text), bg=_color("header")))
            self._fill_totals(row, col, length, weight, _color("header"), QColor(style.current().header_text))
            self.setRowHeight(row, 28)

        widths = {"Marca": 60, "Barra": 54, "Esquema": IMG_W + 16, "Cant. por elem.": 76,
                  "Total barras": 66, "Long. corte (mm)": 92, "Peso unit. (kg)": 84, "Long. total (m)": 88,
                  "Peso total (kg)": 88}
        for name, index in col.items():
            self.setColumnWidth(index, widths.get(name, 58))
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(44)
        header.setFixedHeight(42)

    def _fill_line(self, row: int, line: ScheduleLine, col: dict[str, int]) -> None:
        self.setRowHeight(row, IMG_H + 8)
        mark = _item(line.mark, _CENTER, bold=True, fg=_color("red") if line.warnings else None)
        if line.warnings:  # el aviso de norma sale en la marca (en rojo) y en el detalle de la barra
            mark.setToolTip("\n".join(f"AVISO: {w}" for w in line.warnings))
        self.setItem(row, col["Marca"], mark)
        self.setItem(row, col["Barra"], _item(line.rebar.designation, _CENTER))
        picture = _item("", _CENTER)
        picture.setIcon(QIcon(shape_pixmap(line.shape, IMG_W, IMG_H, line.rebar)))
        self.setItem(row, col["Esquema"], picture)
        self.setItem(row, col["Cant. por elem."], _item(line.group.quantity, _CENTER))
        self.setItem(row, col["Total barras"], _item(f"{line.total_bars:,}", _CENTER))
        if line.parts:  # los largos y pesos van en las sub-filas; aquí solo se anuncia de qué se compone
            for name in ("Long. corte (mm)", "Peso unit. (kg)", "Long. total (m)", "Peso total (kg)"):
                self.setItem(row, col[name], _item(""))
            tip = mark.toolTip()
            mark.setToolTip((tip + "\n" if tip else "") + f"Se arma con {line.parts_text}")
            return
        self.setItem(row, col["Long. corte (mm)"], _item(f"{line.cut_length_mm:,.0f}", _RIGHT))
        self.setItem(row, col["Peso unit. (kg)"], _item(f"{line.unit_weight_kg:,.2f}", _RIGHT))
        self.setItem(row, col["Long. total (m)"], _item(f"{line.total_length_m:,.2f}", _RIGHT))
        self.setItem(row, col["Peso total (kg)"], _item(f"{line.total_weight_kg:,.2f}", _RIGHT, bold=True))

    def _fill_part(self, row: int, line: ScheduleLine, part: LinePart, col: dict[str, int]) -> None:
        """Fila de una sub-marca: una barra recta con la rosca de cada extremo y sus propios pesos."""
        self.setRowHeight(row, IMG_H + 8)
        bg = _color("subtotal")
        self.setItem(row, col["Marca"], _item(part.mark, _CENTER, bold=True, bg=bg))
        self.setItem(row, col["Barra"], _item(line.rebar.designation, _CENTER, bg=bg))
        picture = _item("", _CENTER, bg=bg)
        picture.setIcon(QIcon(shape_pixmap(part.shape, IMG_W, IMG_H, line.rebar)))
        self.setItem(row, col["Esquema"], picture)
        self.setItem(row, col["Cant. por elem."], _item(part.count * line.group.quantity, _CENTER, bg=bg))
        self.setItem(row, col["Total barras"], _item(f"{part.total_bars:,}", _CENTER, bg=bg))
        self.setItem(row, col["Long. corte (mm)"], _item(f"{part.length_mm:,.0f}", _RIGHT, bg=bg))
        self.setItem(row, col["Peso unit. (kg)"], _item(f"{part.unit_weight_kg:,.2f}", _RIGHT, bg=bg))
        self.setItem(row, col["Long. total (m)"], _item(f"{part.total_length_m:,.2f}", _RIGHT, bg=bg))
        self.setItem(row, col["Peso total (kg)"], _item(f"{part.total_weight_kg:,.2f}", _RIGHT, bold=True, bg=bg))
        self.item(row, col["Marca"]).setToolTip(f"Sub-marca de {line.mark}: {part.thread_text or 'sin rosca'}")

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


def _data_table(headers: list[str], rows: list[list[str]], total: list[str] | None) -> QTableWidget:
    table = QTableWidget(len(rows) + (1 if total is not None else 0), len(headers))
    table.setHorizontalHeaderLabels([_wrap_header(h) for h in headers])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setFixedHeight(42)
    table.horizontalHeader().setStyleSheet("QHeaderView::section { font-size: 9pt; }")
    for r, values in enumerate(rows + ([total] if total is not None else [])):
        is_total = total is not None and r == len(rows)
        for c, value in enumerate(values):
            table.setItem(r, c, _item(value, _LEFT if c == 0 else _RIGHT, bold=is_total, bg=_color("subtotal") if is_total else None))
        table.setRowHeight(r, 26)
    table.setFixedHeight(42 + 26 * table.rowCount() + 4)
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

        number = 1
        section(f"{number}. Peso neto por diámetro", _data_table(
            ["Barra", "Ø (mm)", "Grado", "Masa (kg/m)", "Total barras", "Long. total (m)", "Peso neto (kg)", "% del total"],
            [[s.rebar.designation, f"{s.rebar.diameter_mm:.1f}", s.rebar.grade.name, f"{s.rebar.linear_mass_kg_m:.3f}",
              n(s.total_bars, 0), n(s.total_length_m), n(s.total_weight_kg),
              f"{s.total_weight_kg / result.total_weight_kg:.1%}" if result.total_weight_kg else "0.0%"] for s in summaries],
            ["TOTAL", "", "", "", n(sum(s.total_bars for s in summaries), 0), n(result.total_length_m),
             n(result.total_weight_kg), "100.0%"],
        ))
        number += 1
        reusable = summaries[0].reusable_remnant_mm
        section(
            f"{number}. Sobrante de corte (plan optimizado con barras de {result.stock_length_mm / 1000:.2f} m; "
            + (f"retal reutilizable desde {reusable / 1000:.2f} m)" if reusable > 0 else "sin retales reutilizables)"),
            _data_table(
                ["Barra", "Grado", "Barras comerciales", "Long. comprada (m)", "Long. útil (m)", "Sobrante (m)",
                 "Sobrante (kg)", "Sobrante (%)", "Peso a comprar (kg)", "Retal reutilizable (m)", "Desperdicio definitivo (%)"],
                [[s.rebar.designation, s.rebar.grade.name, n(s.stock_bars, 0), n(s.purchased_length_m), n(s.total_length_m),
                  n(s.waste_length_m), n(s.waste_weight_kg), f"{s.waste_pct:.1%}", n(s.purchase_weight_kg),
                  n(s.reusable_length_m), f"{s.scrap_pct:.1%}"] for s in summaries],
                ["TOTAL", "", n(sum(s.stock_bars for s in summaries), 0), n(sum(s.purchased_length_m for s in summaries)),
                 n(result.total_length_m), n(sum(s.waste_length_m for s in summaries)), n(result.total_waste_weight_kg),
                 f"{result.total_waste_pct:.1%}", n(result.total_purchase_weight_kg),
                 n(sum(s.reusable_length_m for s in summaries)), f"{result.total_scrap_pct:.1%}"],
            ),
        )
        number += 1
        if result.has_level_groups:  # el consolidado por nivel / estructura solo tiene sentido con dos o más grupos
            by_level = result.weight_by_level_and_diameter()
            multi_grade = len({s.rebar.designation for s in summaries}) != len(summaries)
            section(f"{number}. Consolidado por {result.group_label.lower()} (peso neto, kg)", _data_table(
                ["Barra", *[result.level_title(level) for level in result.levels], "Total"],
                [[f"{s.rebar.designation} · {s.rebar.grade.name}" if multi_grade else s.rebar.designation,
                  *[n(by_level[level].get(s.rebar, 0.0)) for level in result.levels], n(s.total_weight_kg)] for s in summaries],
                ["TOTAL", *[n(sum(by_level[level].values())) for level in result.levels], n(result.total_weight_kg)],
            ))
            number += 1
        comparisons = stock_comparison(result)
        if comparisons:
            lengths = sorted({o.stock_length_mm for c in comparisons for o in c.options})
            rows = []
            for c in comparisons:
                by_length = {o.stock_length_mm: o for o in c.options}
                rows.append([c.summary.rebar.designation, c.summary.rebar.grade.name]
                            + [f"{by_length[l].bars} · {by_length[l].waste_pct:.1%}" if l in by_length else "no caben" for l in lengths]
                            + [f"{c.best_mm / 1000:.2f} m" if c.best_mm else "—"])
            section(f"{number}. Longitud comercial recomendada (barras · sobrante, con el plan optimizado de cada una)",
                    _data_table(["Barra", "Grado", *[f"{l / 1000:.2f} m" for l in lengths], "Recomendada"], rows, None))
            number += 1
        threads = result.thread_rows()
        if threads:
            section(f"{number}. Acopladores y roscas por barra", _data_table(
                ["Barra", "Grado", "Roscas largas", "Roscas cortas", "Acopladores"],
                [[t.rebar.designation, t.rebar.grade.name, n(t.long, 0), n(t.short, 0), n(t.couplers, 0)] for t in threads],
                ["TOTAL", "", n(sum(t.long for t in threads), 0), n(sum(t.short for t in threads), 0),
                 n(sum(t.couplers for t in threads), 0)],
            ))
        layout.addStretch(1)
        self.setWidget(body)


class CuttingPlanTable(QTableWidget):
    """Plan y secuencia de corte por diámetro, con el dibujo de cada barra comercial."""

    HEADERS = ["Paso", "Barras N°", "Cant.", "Esquema de corte (m)", "Cortes (mm)", "Marcas", "Retal (mm)", "Uso del retal"]
    PLAN_W, PLAN_H = 380, 28

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setIconSize(QSize(self.PLAN_W, self.PLAN_H))
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.populate(None)

    def populate(self, result: BBSResult | None) -> None:
        self.clear()
        self.clearSpans()
        self.setHorizontalHeaderLabels(self.HEADERS)
        summaries = result.diameter_summaries if result else ()
        n_rows = sum(1 + max(len(plan_rows(s)), 1) + (1 if s.plan.stock_bars else 0) for s in summaries)
        self.setRowCount(max(n_rows, 1))
        if not summaries:
            self.setSpan(0, 0, 1, len(self.HEADERS))
            self.setItem(0, 0, _item("Aún no hay barras que cortar. Agregue elementos y barras."))
            self.setRowHeight(0, 30)
            return
        row = 0
        for summary in summaries:
            self.setSpan(row, 0, 1, len(self.HEADERS))
            self.setItem(row, 0, _item(plan_title(summary), bold=True, bg=_color("band")))
            self.setRowHeight(row, 28)
            row += 1
            rows = plan_rows(summary)
            if not rows:
                self.setSpan(row, 0, 1, len(self.HEADERS))
                self.setItem(row, 0, _item("Todas las piezas se suministran en rollo: no hay barras comerciales que cortar."))
                self.setRowHeight(row, 26)
                row += 1
                continue
            for item in rows:
                picture = _item("", _CENTER)
                picture.setIcon(QIcon(pattern_pixmap(item.pattern, self.PLAN_W, self.PLAN_H, summary.reusable_remnant_mm)))
                values = (_item(item.step, _CENTER), _item(item.bars_text, _CENTER), _item(item.count, _CENTER), picture,
                          _item(item.cuts_text), _item(item.marks_text), _item(f"{item.remnant_mm:,.0f}", _RIGHT),
                          _item(item.remnant_use, _CENTER, fg=_color("green") if item.remnant_use == "Reutilizable" else None))
                for column, cell in enumerate(values):
                    self.setItem(row, column, cell)
                self.setRowHeight(row, self.PLAN_H + 10)
                row += 1
            self.setSpan(row, 0, 1, 2)
            self.setItem(row, 0, _item("Total", _RIGHT, bold=True, bg=_color("subtotal")))
            self.setItem(row, 2, _item(summary.plan.stock_bars, _CENTER, bold=True, bg=_color("subtotal")))
            self.setSpan(row, 4, 1, len(self.HEADERS) - 4)
            self.setItem(row, 4, _item(
                f"Sobrante {summary.waste_length_m:,.2f} m  ·  reutilizable {summary.reusable_length_m:,.2f} m  ·  "
                f"desperdicio {summary.scrap_length_m:,.2f} m", bold=True, bg=_color("subtotal")))
            self.setItem(row, 3, _item("", bg=_color("subtotal")))
            self.setRowHeight(row, 26)
            row += 1
        for column, width in enumerate((50, 70, 54, self.PLAN_W + 16, 230, 230, 80, 100)):
            self.setColumnWidth(column, width)
        self.horizontalHeader().setFixedHeight(34)
