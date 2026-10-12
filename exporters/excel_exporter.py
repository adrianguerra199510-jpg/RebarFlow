"""Exportación de la planilla de despiece a Excel con ``openpyxl``.

Genera un libro con dos hojas:

* **Planilla BBS**: barras agrupadas por elemento (con filas de grupo colapsables y subtotal
  por elemento) y total general.
* **Resumen**: peso neto por diámetro, desperdicio de corte y consolidado por nivel.

Las celdas contienen valores calculados por el motor (no fórmulas), de modo que el archivo
se ve igual en Excel, LibreOffice o un visor y no puede divergir del cálculo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

from engine.bbs_calculator import BBSResult, ScheduleLine

_FONT = "Calibri"
_NAVY = "1F3864"
_BAND = "D9E1F2"
_SUBTOTAL = "F2F2F2"
_GRID = "BFBFBF"

_TITLE_FONT = Font(name=_FONT, size=14, bold=True, color=_NAVY)
_HEADER_FONT = Font(name=_FONT, size=10, bold=True, color="FFFFFF")
_BOLD = Font(name=_FONT, size=10, bold=True)
_BODY = Font(name=_FONT, size=10)
_MUTED = Font(name=_FONT, size=10, color="595959")
_WARNING = Font(name=_FONT, size=10, color="C00000")

_HEADER_FILL = PatternFill("solid", fgColor=_NAVY)
_BAND_FILL = PatternFill("solid", fgColor=_BAND)
_SUBTOTAL_FILL = PatternFill("solid", fgColor=_SUBTOTAL)

_THIN = Side(style="thin", color=_GRID)
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
_REMARK = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1)
_RIGHT = Alignment(horizontal="right", vertical="center")

_FMT_MM = "#,##0"
_FMT_2 = "#,##0.00"
_FMT_PCT = "0.0%"


@dataclass
class ExcelExporter:
    """Escribe un :class:`BBSResult` en un archivo ``.xlsx``.

    Attributes:
        project_name: Nombre del proyecto que se muestra en el encabezado.
        author: Responsable del cálculo (opcional).
        issue_date: Fecha de emisión; por defecto, hoy.
    """

    project_name: str = "Proyecto"
    author: str = ""
    issue_date: date | None = None

    def export(self, result: BBSResult, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        self._write_schedule(workbook.active, result)
        self._write_summary(workbook.create_sheet("Resumen"), result)
        workbook.save(path)
        return path

    # ------------------------------------------------------------ hoja 1: planilla
    def _write_schedule(self, ws: Worksheet, result: BBSResult) -> None:
        ws.title = "Planilla BBS"
        dim_labels = _dimension_labels(result.lines)
        headers = (
            ["Marca", "Barra", "Ø (mm)", "Forma"]
            + dim_labels
            + ["Long. corte (mm)", "Cant. por elem.", "Total barras", "Peso unit. (kg)",
               "Long. total (m)", "Peso total (kg)", "Observaciones"]
        )
        n_cols = len(headers)
        col = {name: i + 1 for i, name in enumerate(headers)}

        self._write_title_block(ws, n_cols, "PLANILLA DE DESPIECE DE ACERO DE REFUERZO (BBS)", result)

        header_row = 7
        for c, text in enumerate(headers, start=1):
            _style(ws.cell(header_row, c, text), _HEADER_FONT, _CENTER, fill=_HEADER_FILL)
        ws.row_dimensions[header_row].height = 32

        row = header_row + 1
        for schedule in result.element_schedules:
            element = schedule.element
            band = f"{element.name}  ·  {element.element_type.value}  ·  {element.level}  ·  {element.quantity} und"
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
            _style(ws.cell(row, 1, band), _BOLD, _LEFT, fill=_BAND_FILL)
            for c in range(2, n_cols + 1):
                ws.cell(row, c).border = _BORDER
            row += 1

            first_line = row
            for line in schedule.lines:
                self._write_line(ws, row, line, col, dim_labels)
                row += 1
            if schedule.lines:
                ws.row_dimensions.group(first_line, row - 1, outline_level=1, hidden=False)

            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=col["Total barras"])
            _style(ws.cell(row, 1, f"Subtotal {element.name}"), _BOLD, _RIGHT, fill=_SUBTOTAL_FILL)
            self._write_totals(ws, row, col, n_cols, schedule.total_length_m, schedule.total_weight_kg)
            row += 1

        if result.element_schedules:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=col["Total barras"])
            _style(ws.cell(row, 1, "TOTAL GENERAL"), _HEADER_FONT, _RIGHT, fill=_HEADER_FILL)
            self._write_totals(ws, row, col, n_cols, result.total_length_m, result.total_weight_kg, header=True)

        widths = {"Marca": 8, "Barra": 8, "Ø (mm)": 8, "Forma": 18, "Long. corte (mm)": 12, "Cant. por elem.": 10,
                  "Total barras": 10, "Peso unit. (kg)": 11, "Long. total (m)": 12, "Peso total (kg)": 12,
                  "Observaciones": 52}
        for name, c in col.items():
            ws.column_dimensions[get_column_letter(c)].width = widths.get(name, 9)  # cotas A, B, C…

        ws.freeze_panes = ws.cell(header_row + 1, 1)
        _page_setup(ws, header_row)

    def _write_line(self, ws: Worksheet, row: int, line: ScheduleLine, col: dict[str, int], dim_labels: list[str]) -> None:
        dims = line.shape.dimensions()
        remark = "; ".join(line.notes + tuple(f"⚠ {w}" for w in line.warnings))
        values: list[tuple[str, object, str | None, Alignment]] = [
            ("Marca", line.mark, None, _CENTER),
            ("Barra", line.rebar.designation, None, _CENTER),
            ("Ø (mm)", line.rebar.diameter_mm, "0.0", _CENTER),
            ("Forma", line.shape.label, None, _LEFT),
            *[(label, dims.get(label), _FMT_MM, _RIGHT) for label in dim_labels],
            ("Long. corte (mm)", line.cut_length_mm, _FMT_MM, _RIGHT),
            ("Cant. por elem.", line.group.quantity, _FMT_MM, _CENTER),
            ("Total barras", line.total_bars, _FMT_MM, _CENTER),
            ("Peso unit. (kg)", line.unit_weight_kg, _FMT_2, _RIGHT),
            ("Long. total (m)", line.total_length_m, _FMT_2, _RIGHT),
            ("Peso total (kg)", line.total_weight_kg, _FMT_2, _RIGHT),
            ("Observaciones", remark, None, _REMARK),
        ]
        for name, value, fmt, alignment in values:
            font = _WARNING if name == "Observaciones" and line.warnings else _BODY
            _style(ws.cell(row, col[name], value), font, alignment, number_format=fmt)

    @staticmethod
    def _write_totals(ws: Worksheet, row: int, col: dict[str, int], n_cols: int,
                      length_m: float, weight_kg: float, header: bool = False) -> None:
        font, fill = (_HEADER_FONT, _HEADER_FILL) if header else (_BOLD, _SUBTOTAL_FILL)
        for c in range(1, n_cols + 1):
            cell = ws.cell(row, c)
            cell.border = _BORDER
            cell.fill = fill
        _style(ws.cell(row, col["Long. total (m)"], length_m), font, _RIGHT, fill=fill, number_format=_FMT_2)
        _style(ws.cell(row, col["Peso total (kg)"], weight_kg), font, _RIGHT, fill=fill, number_format=_FMT_2)

    # ------------------------------------------------------------- hoja 2: resumen
    def _write_summary(self, ws: Worksheet, result: BBSResult) -> None:
        n_levels = len(result.levels)
        n_cols = max(9, 2 + n_levels + 1)
        self._write_title_block(ws, n_cols, "RESUMEN Y CONSOLIDADO DE ACERO DE REFUERZO", result)
        row = 7

        # 1. Peso por diámetro
        row = self._section(ws, row, "1. Peso neto por diámetro")
        row = self._table(
            ws, row,
            ["Barra", "Ø (mm)", "Grado", "Masa (kg/m)", "Total barras", "Long. total (m)", "Peso neto (kg)", "% del total"],
            [[s.rebar.designation, s.rebar.diameter_mm, s.rebar.grade.name, s.rebar.linear_mass_kg_m, s.total_bars,
              s.total_length_m, s.total_weight_kg,
              s.total_weight_kg / result.total_weight_kg if result.total_weight_kg else 0.0]
             for s in result.diameter_summaries],
            ["@", "0.0", "@", "0.000", _FMT_MM, _FMT_2, _FMT_2, _FMT_PCT],
            total=["TOTAL", None, None, None, sum(s.total_bars for s in result.diameter_summaries), result.total_length_m,
                   result.total_weight_kg, 1.0 if result.total_weight_kg else 0.0],
        )

        # 2. Desperdicio
        row = self._section(
            ws, row + 1,
            f"2. Desperdicio de corte (barras comerciales de {result.stock_length_mm / 1000:.2f} m, "
            "empaquetado First Fit Decreasing)",
        )
        row = self._table(
            ws, row,
            ["Barra", "Grado", "Barras comerciales", "Long. comprada (m)", "Long. útil (m)", "Desperdicio (m)",
             "Desperdicio (kg)", "Desperdicio (%)", "Peso a comprar (kg)"],
            [[s.rebar.designation, s.rebar.grade.name, s.stock_bars, s.purchased_length_m, s.total_length_m,
              s.waste_length_m, s.waste_weight_kg, s.waste_pct, s.purchase_weight_kg]
             for s in result.diameter_summaries],
            ["@", "@", _FMT_MM, _FMT_2, _FMT_2, _FMT_2, _FMT_2, _FMT_PCT, _FMT_2],
            total=["TOTAL", None, sum(s.stock_bars for s in result.diameter_summaries),
                   sum(s.purchased_length_m for s in result.diameter_summaries), result.total_length_m,
                   sum(s.waste_length_m for s in result.diameter_summaries), result.total_waste_weight_kg,
                   result.total_waste_pct, result.total_purchase_weight_kg],
        )

        # 3. Consolidado por nivel
        row = self._section(ws, row + 1, "3. Consolidado por nivel (peso neto, kg)")
        by_level = result.weight_by_level_and_diameter()
        rebars = [s.rebar for s in result.diameter_summaries]
        multi_grade = len({r.designation for r in rebars}) != len(rebars)
        rows = [
            [f"{rebar.designation} · {rebar.grade.name}" if multi_grade else rebar.designation]
            + [by_level[level].get(rebar, 0.0) for level in result.levels]
            + [sum(by_level[level].get(rebar, 0.0) for level in result.levels)]
            for rebar in rebars
        ]
        level_totals = [sum(by_level[level].values()) for level in result.levels]
        self._table(
            ws, row,
            ["Barra", *result.levels, "Total"],
            rows,
            ["@", *[_FMT_2] * (n_levels + 1)],
            total=["TOTAL", *level_totals, result.total_weight_kg],
        )

        ws.column_dimensions["A"].width = 20
        for c in range(2, n_cols + 1):
            ws.column_dimensions[get_column_letter(c)].width = 16
        ws.sheet_view.showGridLines = False
        _page_setup(ws, None)

    @staticmethod
    def _section(ws: Worksheet, row: int, title: str) -> int:
        _style(ws.cell(row, 1, title), Font(name=_FONT, size=11, bold=True, color=_NAVY), Alignment(vertical="center"))
        return row + 1

    @staticmethod
    def _table(ws: Worksheet, row: int, headers: list[str], rows: list[list[object]], formats: list[str],
               total: list[object]) -> int:
        for c, text in enumerate(headers, start=1):
            _style(ws.cell(row, c, text), _HEADER_FONT, _CENTER, fill=_HEADER_FILL)
        ws.row_dimensions[row].height = 30
        row += 1
        for values in rows:
            for c, (value, fmt) in enumerate(zip(values, formats), start=1):
                _style(ws.cell(row, c, value), _BODY, _LEFT if c == 1 else _RIGHT, number_format=fmt)
            row += 1
        for c, (value, fmt) in enumerate(zip(total, formats), start=1):
            _style(ws.cell(row, c, value), _BOLD, _LEFT if c == 1 else _RIGHT, fill=_SUBTOTAL_FILL, number_format=fmt)
        return row + 1

    # --------------------------------------------------------------- encabezado
    def _write_title_block(self, ws: Worksheet, n_cols: int, title: str, result: BBSResult) -> None:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
        _style(ws.cell(1, 1, title), _TITLE_FONT, Alignment(horizontal="left", vertical="center"))
        ws.row_dimensions[1].height = 26
        issued = (self.issue_date or date.today()).strftime("%d/%m/%Y")
        info = [
            ("Proyecto:", self.project_name),
            ("Fecha:", issued + (f"    Responsable: {self.author}" if self.author else "")),
            ("Criterios:", f"Cotas exteriores · ganchos y dobleces según ACI 318 / NSR-10 · "
                           f"barra comercial {result.stock_length_mm / 1000:.2f} m"),
        ]
        for i, (label, text) in enumerate(info, start=2):
            _style(ws.cell(i, 1, label), _BOLD, Alignment(horizontal="left"))
            ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=n_cols)
            _style(ws.cell(i, 2, text), _MUTED, Alignment(horizontal="left"))


# --------------------------------------------------------------------- helpers
def _style(cell, font: Font, alignment: Alignment, *, fill: PatternFill | None = None,
           number_format: str | None = None):
    cell.font = font
    cell.alignment = alignment
    cell.border = _BORDER
    if fill is not None:
        cell.fill = fill
    if number_format is not None:
        cell.number_format = number_format
    return cell


def _dimension_labels(lines: tuple[ScheduleLine, ...]) -> list[str]:
    """Rótulos de cotas usados por las formas presentes, en orden alfabético (A, B, C…)."""
    labels = {label for line in lines for label in line.shape.dimensions()}
    return sorted(labels, key=lambda s: (len(s), s)) or ["A"]


def _page_setup(ws: Worksheet, header_row: int | None) -> None:
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    if header_row is not None:
        ws.print_title_rows = f"{header_row}:{header_row}"
    ws.oddFooter.center.text = "Página &P de &N"
    ws.oddFooter.left.text = "&A"


def export_bbs_to_excel(result: BBSResult, path: str | Path, project_name: str = "Proyecto",
                        author: str = "") -> Path:
    """Atajo para exportar ``result`` a ``path`` con un :class:`ExcelExporter`."""
    return ExcelExporter(project_name=project_name, author=author).export(result, path)
