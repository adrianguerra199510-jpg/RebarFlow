"""Exportación de la planilla de despiece a PDF con ``reportlab``.

Cada elemento estructural se imprime como una tabla propia (con su fila de título, encabezado
repetido en cada página, esquema de cada barra y subtotal), seguida de una hoja de resumen con
el peso por diámetro, el desperdicio de corte y el consolidado por nivel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from engine.bbs_calculator import BBSResult, ElementSchedule, ScheduleLine
from exporters.shape_images import render_shape_png

_NAVY = colors.HexColor("#1F3864")
_BAND = colors.HexColor("#D9E1F2")
_SUBTOTAL = colors.HexColor("#F2F2F2")
_GRID = colors.HexColor("#BFBFBF")
_RED = "#C00000"

_PAGE_SIZES = {"letter": LETTER, "a4": A4}
_MARGIN = 28
_IMG_W, _IMG_H = 120, 45  # puntos; proporción 8:3 igual que el PNG

_BASE = ParagraphStyle("base", fontName="Helvetica", fontSize=7.5, leading=9)
_CELL_LEFT = ParagraphStyle("cell_left", parent=_BASE)
_CELL_CENTER = ParagraphStyle("cell_center", parent=_BASE, alignment=1)
_CELL_RIGHT = ParagraphStyle("cell_right", parent=_BASE, alignment=2)
_BOLD_LEFT = ParagraphStyle("bold_left", parent=_BASE, fontName="Helvetica-Bold")
_BOLD_RIGHT = ParagraphStyle("bold_right", parent=_BOLD_LEFT, alignment=2)
_HEADER = ParagraphStyle("header", parent=_BASE, fontName="Helvetica-Bold", textColor=colors.white, alignment=1)
_TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=_NAVY)
_SECTION = ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=_NAVY,
                          spaceBefore=10, spaceAfter=3)
_INFO_LABEL = ParagraphStyle("info_label", parent=_BOLD_LEFT, fontSize=8)
_INFO_TEXT = ParagraphStyle("info_text", parent=_BASE, fontSize=8, textColor=colors.HexColor("#595959"))


def _n(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}"


def _p(text: object, style: ParagraphStyle = _CELL_LEFT) -> Paragraph:
    return Paragraph(escape(str(text)), style)


class _NumberedCanvas(canvas.Canvas):
    """Canvas que dibuja el pie de página con "Página X de Y" una vez conocido el total."""

    footer_left = ""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._saved_pages: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 (API de reportlab)
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        width, _ = self._pagesize
        self.setStrokeColor(_GRID)
        self.setLineWidth(0.5)
        self.line(_MARGIN, 24, width - _MARGIN, 24)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#595959"))
        self.drawString(_MARGIN, 14, self.footer_left)
        self.drawRightString(width - _MARGIN, 14, f"Página {self._pageNumber} de {total}")


@dataclass
class PdfExporter:
    """Escribe un :class:`BBSResult` en un archivo PDF apaisado.

    Attributes:
        project_name: Nombre del proyecto del encabezado y del pie.
        author: Responsable del cálculo (opcional).
        issue_date: Fecha de emisión; por defecto, hoy.
        page_size: ``"letter"`` (carta) o ``"a4"``.
        include_shape_images: Imprime el dibujo de cada forma.
    """

    project_name: str = "Proyecto"
    author: str = ""
    issue_date: date | None = None
    page_size: str = "letter"
    include_shape_images: bool = True

    def export(self, result: BBSResult, path: str | Path) -> Path:
        if self.page_size not in _PAGE_SIZES:
            raise ValueError(f"Tamaño de papel inválido {self.page_size!r} (use 'letter' o 'a4').")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pagesize = landscape(_PAGE_SIZES[self.page_size])
        usable = pagesize[0] - 2 * _MARGIN
        issued = (self.issue_date or date.today()).strftime("%d/%m/%Y")

        doc = SimpleDocTemplate(
            str(path), pagesize=pagesize, leftMargin=_MARGIN, rightMargin=_MARGIN, topMargin=26, bottomMargin=34,
            title=f"Planilla de despiece - {self.project_name}", author=self.author or "RebarFlow",
        )
        story = self._title_block(result, issued, usable)
        dim_labels = result.dimension_labels
        for schedule in result.element_schedules:
            story += [Spacer(1, 8), KeepTogether([self._element_table(schedule, dim_labels, usable)])]
        if result.element_schedules:
            story += [Spacer(1, 6), self._grand_total(result, usable)]
        story += [PageBreak(), *self._summary(result, usable)]

        footer = f"{self.project_name}  ·  {issued}"
        canvas_cls = type("FooterCanvas", (_NumberedCanvas,), {"footer_left": footer})
        doc.build(story, canvasmaker=canvas_cls)
        return path

    # ------------------------------------------------------------------ encabezado
    def _title_block(self, result: BBSResult, issued: str, usable: float) -> list:
        info = [
            [_p("Proyecto:", _INFO_LABEL), _p(self.project_name, _INFO_TEXT)],
            [_p("Fecha:", _INFO_LABEL), _p(issued + (f"    Responsable: {self.author}" if self.author else ""), _INFO_TEXT)],
            [_p("Criterios:", _INFO_LABEL),
             _p("Cotas exteriores · ganchos y dobleces según ACI 318 / NSR-10 · "
                f"barra comercial {result.stock_length_mm / 1000:.2f} m", _INFO_TEXT)],
        ]
        table = Table(info, colWidths=[52, usable - 52])
        table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, _GRID), ("TOPPADDING", (0, 0), (-1, -1), 2),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
        return [Paragraph("PLANILLA DE DESPIECE DE ACERO DE REFUERZO (BBS)", _TITLE), Spacer(1, 4), table]

    # ------------------------------------------------------------ tabla por elemento
    def _columns(self, dim_labels: list[str], usable: float) -> list[tuple[str, float]]:
        columns = [("Marca", 34), ("Barra", 32), ("Ø (mm)", 32)]
        if self.include_shape_images:
            columns.append(("Esquema", _IMG_W + 10))
        columns.append(("Forma", 62))
        columns += [(label, 36) for label in dim_labels]
        columns += [("Long. corte (mm)", 46), ("Cant. por elem.", 36), ("Total barras", 38), ("Peso unit. (kg)", 42),
                    ("Long. total (m)", 46), ("Peso total (kg)", 48)]
        fixed = sum(width for _, width in columns)
        observations = max(usable - fixed, 70)
        columns.append(("Observaciones", observations))
        total = fixed + observations
        scale = usable / total if total > usable else 1.0  # muchas cotas: se comprimen todas las columnas
        return [(name, width * scale) for name, width in columns]

    def _element_table(self, schedule: ElementSchedule, dim_labels: list[str], usable: float) -> Table:
        columns = self._columns(dim_labels, usable)
        names = [name for name, _ in columns]
        n_cols = len(columns)
        element = schedule.element

        band = f"{element.name}  ·  {element.element_type.value}  ·  {element.level}  ·  {element.quantity} und"
        rows: list[list] = [[_p(band, _BOLD_LEFT)] + [""] * (n_cols - 1),
                            [_p(name, _HEADER) for name in names]]
        for line in schedule.lines:
            rows.append(self._line_row(line, names, dim_labels))

        subtotal = [""] * n_cols
        subtotal[0] = _p(f"Subtotal {element.name}", _BOLD_RIGHT)
        subtotal[names.index("Long. total (m)")] = _p(_n(schedule.total_length_m), _BOLD_RIGHT)
        subtotal[names.index("Peso total (kg)")] = _p(_n(schedule.total_weight_kg), _BOLD_RIGHT)
        rows.append(subtotal)

        last = len(rows) - 1
        style = TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("SPAN", (0, 0), (-1, 0)), ("BACKGROUND", (0, 0), (-1, 0), _BAND),
            ("BACKGROUND", (0, 1), (-1, 1), _NAVY),
            ("SPAN", (0, last), (names.index("Total barras"), last)), ("BACKGROUND", (0, last), (-1, last), _SUBTOTAL),
        ])
        table = Table(rows, colWidths=[width for _, width in columns], repeatRows=2)
        table.setStyle(style)
        return table

    def _line_row(self, line: ScheduleLine, names: list[str], dim_labels: list[str]) -> list:
        dims = line.shape.dimensions()
        remark = "<br/>".join(
            [escape(note) for note in line.notes] + [f'<font color="{_RED}">AVISO: {escape(w)}</font>' for w in line.warnings]
        )
        cells: dict[str, object] = {
            "Marca": _p(line.mark, _CELL_CENTER),
            "Barra": _p(line.rebar.designation, _CELL_CENTER),
            "Ø (mm)": _p(f"{line.rebar.diameter_mm:.1f}", _CELL_CENTER),
            "Forma": _p(line.shape.label),
            "Long. corte (mm)": _p(_n(line.cut_length_mm, 0), _CELL_RIGHT),
            "Cant. por elem.": _p(line.group.quantity, _CELL_CENTER),
            "Total barras": _p(line.total_bars, _CELL_CENTER),
            "Peso unit. (kg)": _p(_n(line.unit_weight_kg), _CELL_RIGHT),
            "Long. total (m)": _p(_n(line.total_length_m), _CELL_RIGHT),
            "Peso total (kg)": _p(_n(line.total_weight_kg), _CELL_RIGHT),
            "Observaciones": Paragraph(remark, ParagraphStyle("remark", parent=_BASE, fontSize=6.5, leading=8)),
        }
        for label in dim_labels:
            cells[label] = _p(_n(dims[label], 0), _CELL_RIGHT) if label in dims else ""
        if self.include_shape_images:
            cells["Esquema"] = Image(BytesIO(render_shape_png(line.shape, 3 * _IMG_W, 3 * _IMG_H)),
                                     width=_IMG_W, height=_IMG_H)
        return [cells[name] for name in names]

    @staticmethod
    def _grand_total(result: BBSResult, usable: float) -> Table:
        table = Table(
            [[_p("TOTAL GENERAL", _HEADER), _p(f"Long. total: {_n(result.total_length_m)} m", _HEADER),
              _p(f"Peso total: {_n(result.total_weight_kg)} kg", _HEADER)]],
            colWidths=[usable * 0.3, usable * 0.35, usable * 0.35],
        )
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _NAVY), ("TOPPADDING", (0, 0), (-1, -1), 4),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return table

    # ----------------------------------------------------------------------- resumen
    def _summary(self, result: BBSResult, usable: float) -> list:
        summaries = result.diameter_summaries
        total_pct = 1.0 if result.total_weight_kg else 0.0
        story: list = [Paragraph("RESUMEN Y CONSOLIDADO DE ACERO DE REFUERZO", _TITLE)]

        story += [Paragraph("1. Peso neto por diámetro", _SECTION), self._data_table(
            ["Barra", "Ø (mm)", "Grado", "Masa (kg/m)", "Total barras", "Long. total (m)", "Peso neto (kg)", "% del total"],
            [[s.rebar.designation, f"{s.rebar.diameter_mm:.1f}", s.rebar.grade.name, f"{s.rebar.linear_mass_kg_m:.3f}",
              _n(s.total_bars, 0), _n(s.total_length_m), _n(s.total_weight_kg),
              f"{s.total_weight_kg / result.total_weight_kg:.1%}" if result.total_weight_kg else "0.0%"] for s in summaries],
            ["TOTAL", "", "", "", _n(sum(s.total_bars for s in summaries), 0), _n(result.total_length_m),
             _n(result.total_weight_kg), f"{total_pct:.1%}"],
            usable,
        )]

        story += [Paragraph(
            f"2. Desperdicio de corte (barras comerciales de {result.stock_length_mm / 1000:.2f} m, "
            "empaquetado First Fit Decreasing)", _SECTION), self._data_table(
            ["Barra", "Grado", "Barras comerciales", "Long. comprada (m)", "Long. útil (m)", "Desperdicio (m)",
             "Desperdicio (kg)", "Desperdicio (%)", "Peso a comprar (kg)"],
            [[s.rebar.designation, s.rebar.grade.name, _n(s.stock_bars, 0), _n(s.purchased_length_m),
              _n(s.total_length_m), _n(s.waste_length_m), _n(s.waste_weight_kg), f"{s.waste_pct:.1%}",
              _n(s.purchase_weight_kg)] for s in summaries],
            ["TOTAL", "", _n(sum(s.stock_bars for s in summaries), 0), _n(sum(s.purchased_length_m for s in summaries)),
             _n(result.total_length_m), _n(sum(s.waste_length_m for s in summaries)), _n(result.total_waste_weight_kg),
             f"{result.total_waste_pct:.1%}", _n(result.total_purchase_weight_kg)],
            usable,
        )]

        by_level = result.weight_by_level_and_diameter()
        multi_grade = len({s.rebar.designation for s in summaries}) != len(summaries)
        story += [Paragraph("3. Consolidado por nivel (peso neto, kg)", _SECTION), self._data_table(
            ["Barra", *result.levels, "Total"],
            [[f"{s.rebar.designation} · {s.rebar.grade.name}" if multi_grade else s.rebar.designation,
              *[_n(by_level[level].get(s.rebar, 0.0)) for level in result.levels], _n(s.total_weight_kg)]
             for s in summaries],
            ["TOTAL", *[_n(sum(by_level[level].values())) for level in result.levels], _n(result.total_weight_kg)],
            usable,
        )]
        return story

    @staticmethod
    def _data_table(headers: list[str], rows: list[list[str]], total: list[str], usable: float) -> Table:
        n_cols = len(headers)
        data = [[_p(h, _HEADER) for h in headers]]
        data += [[_p(v, _CELL_LEFT if i == 0 else _CELL_RIGHT) for i, v in enumerate(row)] for row in rows]
        data.append([_p(v, _BOLD_LEFT if i == 0 else _BOLD_RIGHT) for i, v in enumerate(total)])
        width = min(usable, 80 * n_cols)
        table = Table(data, colWidths=[width / n_cols] * n_cols, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, _GRID), ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
            ("BACKGROUND", (0, -1), (-1, -1), _SUBTOTAL), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return table


def export_bbs_to_pdf(result: BBSResult, path: str | Path, project_name: str = "Proyecto", author: str = "") -> Path:
    """Atajo para exportar ``result`` a ``path`` con un :class:`PdfExporter`."""
    return PdfExporter(project_name=project_name, author=author).export(result, path)
