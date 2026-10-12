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
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.units import pixels_to_EMU
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

from engine.bbs_calculator import BBSResult, ScheduleLine
from engine.cutting_report import plan_rows, plan_title, stock_comparison
from exporters.cutting_images import render_pattern_png
from exporters.shape_images import render_shape_png

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

# Esquema de la barra: celda de 160 x 60 px (el PNG se genera al doble para que se vea nítido).
_IMG_W, _IMG_H = 160, 60
_IMG_ROW_HEIGHT_PT = 52.0
# Barra comercial del plan de corte: celda de 400 x 30 px.
_PLAN_W, _PLAN_H = 400, 30
_PLAN_ROW_HEIGHT_PT = 27.0


@dataclass
class ExcelExporter:
    """Escribe un :class:`BBSResult` en un archivo ``.xlsx``.

    Attributes:
        project_name: Nombre del proyecto que se muestra en el encabezado.
        author: Responsable del cálculo (opcional).
        issue_date: Fecha de emisión; por defecto, hoy.
        include_shape_images: Inserta el dibujo de cada forma en la planilla.
    """

    project_name: str = "Proyecto"
    author: str = ""
    issue_date: date | None = None
    include_shape_images: bool = True

    def export(self, result: BBSResult, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        self._write_schedule(workbook.active, result)
        self._write_summary(workbook.create_sheet("Resumen"), result)
        self._write_plan(workbook.create_sheet("Plan de corte"), result)
        workbook.save(path)
        return path

    # ------------------------------------------------------------ hoja 1: planilla
    def _write_schedule(self, ws: Worksheet, result: BBSResult) -> None:
        ws.title = "Planilla BBS"
        dim_labels = result.dimension_labels
        images = self.include_shape_images
        headers = (
            ["Marca", "Barra", "Ø (mm)"]
            + (["Esquema"] if images else [])
            + ["Forma"]
            + dim_labels
            + ["Ganchos (° · mm)", "Long. corte (mm)", "Cant. por elem.", "Total barras", "Peso unit. (kg)",
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
                if images:
                    self._add_shape_image(ws, row, col["Esquema"], line)
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

        widths = {"Marca": 8, "Barra": 8, "Ø (mm)": 8, "Esquema": 25, "Forma": 18, "Ganchos (° · mm)": 17, "Long. corte (mm)": 12, "Cant. por elem.": 10,
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
            ("Ganchos (° · mm)", line.hook_text, None, _CENTER),
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
    def _add_shape_image(ws: Worksheet, row: int, column: int, line: ScheduleLine) -> None:
        """Inserta el esquema de ``line`` centrado en la celda (fila alta, columna ``Esquema``)."""
        ws.row_dimensions[row].height = _IMG_ROW_HEIGHT_PT
        image = XLImage(BytesIO(render_shape_png(line.shape, 2 * _IMG_W, 2 * _IMG_H, line.rebar)))
        row_px = _IMG_ROW_HEIGHT_PT * 96 / 72
        image.anchor = OneCellAnchor(
            _from=AnchorMarker(col=column - 1, colOff=pixels_to_EMU(4), row=row - 1,
                               rowOff=pixels_to_EMU(max(0, (row_px - _IMG_H) / 2))),
            ext=XDRPositiveSize2D(pixels_to_EMU(_IMG_W), pixels_to_EMU(_IMG_H)),
        )
        ws.add_image(image)

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
        n_cols = max(11, 2 + n_levels + 1)
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
        reusable = result.diameter_summaries[0].reusable_remnant_mm if result.diameter_summaries else 0.0
        row = self._section(
            ws, row + 1,
            f"2. Sobrante de corte (plan optimizado con barras comerciales de {result.stock_length_mm / 1000:.2f} m; "
            + (f"retal reutilizable desde {reusable / 1000:.2f} m)" if reusable > 0 else "sin retales reutilizables)"),
        )
        row = self._table(
            ws, row,
            ["Barra", "Grado", "Barras comerciales", "Long. comprada (m)", "Long. útil (m)", "Sobrante (m)",
             "Sobrante (kg)", "Sobrante (%)", "Peso a comprar (kg)", "Retal reutilizable (m)", "Desperdicio definitivo (%)"],
            [[s.rebar.designation, s.rebar.grade.name, s.stock_bars, s.purchased_length_m, s.total_length_m,
              s.waste_length_m, s.waste_weight_kg, s.waste_pct, s.purchase_weight_kg, s.reusable_length_m, s.scrap_pct]
             for s in result.diameter_summaries],
            ["@", "@", _FMT_MM, _FMT_2, _FMT_2, _FMT_2, _FMT_2, _FMT_PCT, _FMT_2, _FMT_2, _FMT_PCT],
            total=["TOTAL", None, sum(s.stock_bars for s in result.diameter_summaries),
                   sum(s.purchased_length_m for s in result.diameter_summaries), result.total_length_m,
                   sum(s.waste_length_m for s in result.diameter_summaries), result.total_waste_weight_kg,
                   result.total_waste_pct, result.total_purchase_weight_kg,
                   sum(s.reusable_length_m for s in result.diameter_summaries), result.total_scrap_pct],
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
        row = self._table(
            ws, row,
            ["Barra", *result.levels, "Total"],
            rows,
            ["@", *[_FMT_2] * (n_levels + 1)],
            total=["TOTAL", *level_totals, result.total_weight_kg],
        )

        # 4. Longitud comercial recomendada
        comparisons = stock_comparison(result)
        if comparisons:
            lengths = sorted({o.stock_length_mm for c in comparisons for o in c.options})
            row = self._section(ws, row + 1, "4. Longitud comercial recomendada (barras · sobrante, con el plan optimizado de cada una)")
            rows = []
            for c in comparisons:
                by_length = {o.stock_length_mm: o for o in c.options}
                rows.append([c.summary.rebar.designation, c.summary.rebar.grade.name]
                            + [f"{by_length[l].bars} · {by_length[l].waste_pct:.1%}" if l in by_length else "no caben" for l in lengths]
                            + [f"{c.best_mm / 1000:.2f} m" if c.best_mm else "—"])
            self._table(ws, row, ["Barra", "Grado", *[f"{l / 1000:.2f} m" for l in lengths], "Recomendada"], rows,
                        ["@"] * (len(lengths) + 3), total=None)
            n_cols = max(n_cols, len(lengths) + 3)

        ws.column_dimensions["A"].width = 20
        for c in range(2, n_cols + 1):
            ws.column_dimensions[get_column_letter(c)].width = 16
        ws.sheet_view.showGridLines = False
        _page_setup(ws, None)

    # ------------------------------------------------------- hoja 3: plan de corte
    def _write_plan(self, ws: Worksheet, result: BBSResult) -> None:
        headers = ["Paso", "Barras N°", "Cant.", "Esquema de corte (m)", "Cortes (mm)", "Marcas", "Retal (mm)", "Uso del retal"]
        n_cols = len(headers)
        self._write_title_block(ws, n_cols, "PLAN Y SECUENCIA DE CORTE", result)
        legend = ("Cada barra comercial se corta de izquierda a derecha; el tramo rayado final es el retal "
                  "(verde: reutilizable, gris: desperdicio).")
        ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=n_cols)
        _style(ws.cell(6, 1, legend), _MUTED, Alignment(horizontal="left"))
        row = 8
        if not result.diameter_summaries:
            ws.cell(row, 1, "Sin barras que cortar.")
        for summary in result.diameter_summaries:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
            _style(ws.cell(row, 1, plan_title(summary)), _BOLD, _LEFT, fill=_BAND_FILL)
            for c in range(2, n_cols + 1):
                ws.cell(row, c).border = _BORDER
            ws.row_dimensions[row].height = 20  # alturas fijas: así el programa no reajusta filas ni mueve las imágenes
            row += 1
            rows = plan_rows(summary)
            if not rows:
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
                _style(ws.cell(row, 1, "Todas las piezas se suministran en rollo: no hay barras comerciales que cortar."),
                       _BODY, _LEFT)
                ws.row_dimensions[row].height = 20
                row += 2
                continue
            for c, text in enumerate(headers, start=1):
                _style(ws.cell(row, c, text), _HEADER_FONT, _CENTER, fill=_HEADER_FILL)
            ws.row_dimensions[row].height = 24
            row += 1
            for item in rows:
                values = [(item.step, _CENTER, None), (item.bars_text, _CENTER, None), (item.count, _CENTER, _FMT_MM),
                          (None, _CENTER, None), (item.cuts_text, _LEFT, None), (item.marks_text, _LEFT, None),
                          (item.remnant_mm, _RIGHT, _FMT_MM), (item.remnant_use, _CENTER, None)]
                for c, (value, alignment, fmt) in enumerate(values, start=1):
                    _style(ws.cell(row, c, value), _BODY, alignment, number_format=fmt)
                ws.row_dimensions[row].height = _PLAN_ROW_HEIGHT_PT
                image = XLImage(BytesIO(render_pattern_png(item.pattern, 2 * _PLAN_W, 2 * _PLAN_H, summary.reusable_remnant_mm)))
                row_px = _PLAN_ROW_HEIGHT_PT * 96 / 72
                image.anchor = OneCellAnchor(
                    _from=AnchorMarker(col=3, colOff=pixels_to_EMU(4), row=row - 1,
                                       rowOff=pixels_to_EMU(max(0, (row_px - _PLAN_H) / 2))),
                    ext=XDRPositiveSize2D(pixels_to_EMU(_PLAN_W), pixels_to_EMU(_PLAN_H)),
                )
                ws.add_image(image)
                row += 1
            total_bars = summary.plan.stock_bars
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
            _style(ws.cell(row, 1, "Total"), _BOLD, _RIGHT, fill=_SUBTOTAL_FILL)
            for c in range(3, n_cols + 1):
                _style(ws.cell(row, c), _BOLD, _RIGHT, fill=_SUBTOTAL_FILL)
            ws.cell(row, 3, total_bars).number_format = _FMT_MM
            ws.merge_cells(start_row=row, start_column=5, end_row=row, end_column=n_cols)
            ws.cell(row, 5, f"Sobrante {summary.waste_length_m:,.2f} m  ·  reutilizable {summary.reusable_length_m:,.2f} m  ·  "
                            f"desperdicio {summary.scrap_length_m:,.2f} m").alignment = Alignment(horizontal="left", vertical="center")
            ws.row_dimensions[row].height = 20
            row += 2
        widths = {1: 7, 2: 11, 3: 8, 4: 60, 5: 40, 6: 36, 7: 11, 8: 14}
        for column, width in widths.items():
            ws.column_dimensions[get_column_letter(column)].width = width
        ws.sheet_view.showGridLines = False
        _page_setup(ws, None)

    @staticmethod
    def _section(ws: Worksheet, row: int, title: str) -> int:
        _style(ws.cell(row, 1, title), Font(name=_FONT, size=11, bold=True, color=_NAVY), Alignment(vertical="center"))
        return row + 1

    @staticmethod
    def _table(ws: Worksheet, row: int, headers: list[str], rows: list[list[object]], formats: list[str],
               total: list[object] | None) -> int:
        for c, text in enumerate(headers, start=1):
            _style(ws.cell(row, c, text), _HEADER_FONT, _CENTER, fill=_HEADER_FILL)
        ws.row_dimensions[row].height = 30
        row += 1
        for values in rows:
            for c, (value, fmt) in enumerate(zip(values, formats), start=1):
                _style(ws.cell(row, c, value), _BODY, _LEFT if c == 1 else _RIGHT, number_format=fmt)
            row += 1
        if total is not None:
            for c, (value, fmt) in enumerate(zip(total, formats), start=1):
                _style(ws.cell(row, c, value), _BOLD, _LEFT if c == 1 else _RIGHT, fill=_SUBTOTAL_FILL, number_format=fmt)
            row += 1
        return row

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
