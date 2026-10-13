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

from core.coupler import coupler_label, coupler_legend
from engine.bbs_calculator import BBSResult, ElementSchedule, ScheduleLine
from engine.cutting_report import plan_rows, plan_title, stock_comparison
from exporters.cutting_images import render_pattern_png
from exporters.logo import fitted_size
from exporters.shape_images import render_shape_png

_NAVY = colors.HexColor("#1F3864")
_BAND = colors.HexColor("#D9E1F2")
_SUBTOTAL = colors.HexColor("#F2F2F2")
_GRID = colors.HexColor("#BFBFBF")
_RED = "#C00000"

_PAGE_SIZES = {"letter": LETTER, "a4": A4}
_MARGIN = 28
_IMG_W, _IMG_H = 200, 75  # puntos; proporción 8:3 igual que el PNG (las cotas van solo en el dibujo)
_PLAN_W, _PLAN_H = 256, 22  # barra comercial del plan de corte (puntos)

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
        info: Datos de encabezado adicionales como ``(rótulo, valor)``: cliente, código de obra, plano…
        logo_png: Logo (PNG) que se imprime arriba a la izquierda de la primera página; vacío = sin logo.
    """

    project_name: str = "Proyecto"
    author: str = ""
    issue_date: date | None = None
    page_size: str = "letter"
    include_shape_images: bool = True
    info: tuple[tuple[str, str], ...] = ()
    logo_png: bytes = b""

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
        frame_height = pagesize[1] - doc.topMargin - doc.bottomMargin
        for schedule in result.element_schedules:
            table = self._element_table(schedule, usable)
            _, height = table.wrap(usable, frame_height)
            # una tabla que cabe en una página no se parte; una más alta empieza donde está y se parte con cabecera repetida
            story += [Spacer(1, 8), KeepTogether([table]) if height < 0.92 * frame_height else table]
        if result.element_schedules:
            story += [Spacer(1, 6), self._grand_total(result, usable)]
        if result.warnings:  # las marcas con aviso van en rojo en la tabla; el texto se lista aquí
            story += [Paragraph("Avisos", ParagraphStyle("warn_title", parent=_SECTION, textColor=colors.HexColor(_RED)))]
            story += [Paragraph(f'<font color="{_RED}">⚠ {escape(element)} · marca {escape(mark)}: {escape(text)}</font>', _BASE)
                      for element, mark, text in result.warnings]
        if result.supply_notes:  # espirales armadas con varias barras: cuántas y cómo se unen
            story += [Paragraph("Suministro con uniones", _SECTION)]
            story += [Paragraph(f"{escape(element)} · marca {escape(mark)}: {escape(text)}", _BASE)
                      for element, mark, text in result.supply_notes]
        story += [PageBreak(), *self._summary(result, usable), PageBreak(), *self._cutting_plan(result, usable)]

        footer = f"{self.project_name}  ·  {issued}"
        canvas_cls = type("FooterCanvas", (_NumberedCanvas,), {"footer_left": footer})
        doc.build(story, canvasmaker=canvas_cls)
        return path

    # ------------------------------------------------------------------ encabezado
    def _title_block(self, result: BBSResult, issued: str, usable: float) -> list:
        extras = [f"{label}: {value}" for label, value in self.info]
        rows = [[_p("Proyecto:", _INFO_LABEL), _p(self.project_name, _INFO_TEXT)]]
        for k in range(0, len(extras), 3):  # los datos de la obra, de tres en tres por fila
            rows.append([_p("Datos:" if k == 0 else "", _INFO_LABEL), _p("      ·      ".join(extras[k:k + 3]), _INFO_TEXT)])
        rows += [
            [_p("Fecha:", _INFO_LABEL), _p(issued + (f"    Responsable: {self.author}" if self.author else ""), _INFO_TEXT)],
            [_p("Criterios:", _INFO_LABEL),
             _p("Cotas exteriores · ganchos y dobleces según ACI 318 / NSR-10 · "
                f"barra comercial {result.stock_length_mm / 1000:.2f} m"
                + coupler_legend(c.kind for c in result.coupler_counts()), _INFO_TEXT)],
        ]
        table = Table(rows, colWidths=[52, usable - 52])
        table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, _GRID), ("TOPPADDING", (0, 0), (-1, -1), 2),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
        title = Paragraph("PLANILLA DE DESPIECE DE ACERO DE REFUERZO (BBS)", _TITLE)
        if not self.logo_png:
            return [title, Spacer(1, 4), table]
        width, height = fitted_size(self.logo_png, 170, 54)  # logo a la izquierda y el título a su lado
        head = Table([[Image(BytesIO(self.logo_png), width=width, height=height), title]], colWidths=[width + 14, usable - width - 14])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        return [head, Spacer(1, 4), table]

    # ------------------------------------------------------------ tabla por elemento
    def _columns(self, usable: float) -> list[tuple[str, float]]:
        columns = [("Marca", 38), ("Barra", 34)]
        if self.include_shape_images:
            columns.append(("Esquema", _IMG_W + 10))
        columns += [("Long. corte (mm)", 50), ("Cant. por elem.", 40), ("Total barras", 42), ("Peso unit. (kg)", 46),
                    ("Long. total (m)", 50), ("Peso total (kg)", 52)]
        picture = _IMG_W + 10 if self.include_shape_images else 0
        rest = sum(width for name, width in columns if name != "Esquema")
        # las demás columnas se ajustan al ancho útil (hasta un 60 % más anchas); la del esquema no cambia, porque debe
        # seguir conteniendo su imagen
        scale = min((usable - picture) / rest, 1.6)
        return [(name, width if name == "Esquema" else width * scale) for name, width in columns]

    def _element_table(self, schedule: ElementSchedule, usable: float) -> Table:
        columns = self._columns(usable)
        names = [name for name, _ in columns]
        n_cols = len(columns)
        element = schedule.element

        band = element.heading
        rows: list[list] = [[_p(band, _BOLD_LEFT)] + [""] * (n_cols - 1),
                            [_p(name, _HEADER) for name in names]]
        for line in schedule.lines:
            rows.append(self._line_row(line, names))

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

    def _line_row(self, line: ScheduleLine, names: list[str]) -> list:
        mark_style = ParagraphStyle("mark_warn", parent=_CELL_CENTER, textColor=colors.HexColor(_RED), fontName="Helvetica-Bold") \
            if line.warnings else _CELL_CENTER
        cells: dict[str, object] = {
            "Marca": _p(line.mark, mark_style),
            "Barra": _p(line.rebar.designation, _CELL_CENTER),
            "Long. corte (mm)": _p(_n(line.cut_length_mm, 0), _CELL_RIGHT),
            "Cant. por elem.": _p(line.group.quantity, _CELL_CENTER),
            "Total barras": _p(line.total_bars, _CELL_CENTER),
            "Peso unit. (kg)": _p(_n(line.unit_weight_kg), _CELL_RIGHT),
            "Long. total (m)": _p(_n(line.total_length_m), _CELL_RIGHT),
            "Peso total (kg)": _p(_n(line.total_weight_kg), _CELL_RIGHT),
        }
        if self.include_shape_images:
            cells["Esquema"] = Image(BytesIO(render_shape_png(line.shape, 3 * _IMG_W, 3 * _IMG_H, line.rebar)),
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

        reusable = summaries[0].reusable_remnant_mm if summaries else 0.0
        story += [Paragraph(
            f"2. Sobrante de corte (plan optimizado con barras comerciales de {result.stock_length_mm / 1000:.2f} m; "
            + (f"retal reutilizable desde {reusable / 1000:.2f} m)" if reusable > 0 else "sin retales reutilizables)"),
            _SECTION), self._data_table(
            ["Barra", "Grado", "Barras comerciales", "Long. comprada (m)", "Long. útil (m)", "Sobrante (m)",
             "Sobrante (kg)", "Sobrante (%)", "Peso a comprar (kg)", "Retal reutilizable (m)", "Desperdicio definitivo (%)"],
            [[s.rebar.designation, s.rebar.grade.name, _n(s.stock_bars, 0), _n(s.purchased_length_m),
              _n(s.total_length_m), _n(s.waste_length_m), _n(s.waste_weight_kg), f"{s.waste_pct:.1%}",
              _n(s.purchase_weight_kg), _n(s.reusable_length_m), f"{s.scrap_pct:.1%}"] for s in summaries],
            ["TOTAL", "", _n(sum(s.stock_bars for s in summaries), 0), _n(sum(s.purchased_length_m for s in summaries)),
             _n(result.total_length_m), _n(sum(s.waste_length_m for s in summaries)), _n(result.total_waste_weight_kg),
             f"{result.total_waste_pct:.1%}", _n(result.total_purchase_weight_kg),
             _n(sum(s.reusable_length_m for s in summaries)), f"{result.total_scrap_pct:.1%}"],
            usable,
        )]

        number = 3
        if result.has_level_groups:  # el consolidado por nivel / estructura solo tiene sentido con dos o más grupos
            by_level = result.weight_by_level_and_diameter()
            multi_grade = len({s.rebar.designation for s in summaries}) != len(summaries)
            story += [Paragraph(f"{number}. Consolidado por {result.group_label.lower()} (peso neto, kg)", _SECTION),
                      self._data_table(
                ["Barra", *[result.level_title(level) for level in result.levels], "Total"],
                [[f"{s.rebar.designation} · {s.rebar.grade.name}" if multi_grade else s.rebar.designation,
                  *[_n(by_level[level].get(s.rebar, 0.0)) for level in result.levels], _n(s.total_weight_kg)]
                 for s in summaries],
                ["TOTAL", *[_n(sum(by_level[level].values())) for level in result.levels], _n(result.total_weight_kg)],
                usable,
            )]
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
            story += [Paragraph(f"{number}. Longitud comercial recomendada (barras · sobrante, con el plan optimizado de cada una)",
                                _SECTION),
                      self._data_table(["Barra", "Grado", *[f"{l / 1000:.2f} m" for l in lengths], "Recomendada"], rows, None, usable)]
            number += 1

        couplers = result.coupler_counts()
        if couplers:
            story += [Paragraph(f"{number}. Couplers por barra y tipo", _SECTION), self._data_table(
                ["Barra", "Grado", "Tipo de coupler", "Cantidad"],
                [[c.rebar.designation, c.rebar.grade.name, coupler_label(c.kind), _n(c.count, 0)] for c in couplers],
                ["TOTAL", "", "", _n(sum(c.count for c in couplers), 0)], usable)]
        return story

    # --------------------------------------------------------------- plan de corte
    def _cutting_plan(self, result: BBSResult, usable: float) -> list:
        story: list = [Paragraph("PLAN Y SECUENCIA DE CORTE", _TITLE), Spacer(1, 3),
                       Paragraph("Cada barra comercial se corta de izquierda a derecha; el tramo rayado final es el retal "
                                 "(verde: reutilizable, gris: desperdicio).", _INFO_TEXT)]
        if not result.diameter_summaries:
            return story + [Paragraph("Sin barras que cortar.", _INFO_TEXT)]
        headers = ["Paso", "Barras N°", "Cant.", "Esquema de corte (m)", "Cortes (mm)", "Marcas", "Retal (mm)", "Uso del retal"]
        widths = [30, 44, 30, _PLAN_W + 10, 120, 112, 46, 52]
        scale = min(1.0, usable / sum(widths))
        widths = [w * scale for w in widths]
        for summary in result.diameter_summaries:
            block: list = [Paragraph(escape(plan_title(summary)), _SECTION)]
            rows = plan_rows(summary)
            if not rows:
                story += [*block, Paragraph("Todas las piezas se suministran en rollo: no hay barras comerciales que cortar.", _INFO_TEXT)]
                continue
            data = [[_p(h, _HEADER) for h in headers]]
            for item in rows:
                image = Image(BytesIO(render_pattern_png(item.pattern, 3 * _PLAN_W, 3 * _PLAN_H, summary.reusable_remnant_mm)),
                              width=_PLAN_W, height=_PLAN_H)
                data.append([_p(item.step, _CELL_CENTER), _p(item.bars_text, _CELL_CENTER), _p(item.count, _CELL_CENTER), image,
                             _p(item.cuts_text), Paragraph(escape(item.marks_text), ParagraphStyle("marks", parent=_BASE, fontSize=6.5, leading=8)),
                             _p(_n(item.remnant_mm, 0), _CELL_RIGHT), _p(item.remnant_use, _CELL_CENTER)])
            data.append([_p("Total", _BOLD_RIGHT), "", _p(summary.plan.stock_bars, _CELL_CENTER), "",
                         _p(f"Sobrante {_n(summary.waste_length_m)} m · reutilizable {_n(summary.reusable_length_m)} m · "
                            f"desperdicio {_n(summary.scrap_length_m)} m", _BOLD_LEFT), "", "", ""])
            last = len(data) - 1
            table = Table(data, colWidths=widths, repeatRows=1)
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, _GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY), ("BACKGROUND", (0, last), (-1, last), _SUBTOTAL),
                ("SPAN", (0, last), (1, last)), ("SPAN", (4, last), (-1, last)),
                ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]))
            if len(rows) <= 12:
                story.append(KeepTogether([*block, table]))
            else:  # una sección larga puede partirse entre páginas (la cabecera de la tabla se repite)
                story += [*block, table]
        return story

    @staticmethod
    def _data_table(headers: list[str], rows: list[list[str]], total: list[str] | None, usable: float) -> Table:
        n_cols = len(headers)
        data = [[_p(h, _HEADER) for h in headers]]
        data += [[_p(v, _CELL_LEFT if i == 0 else _CELL_RIGHT) for i, v in enumerate(row)] for row in rows]
        if total is not None:
            data.append([_p(v, _BOLD_LEFT if i == 0 else _BOLD_RIGHT) for i, v in enumerate(total)])
        width = min(usable, 80 * n_cols)
        table = Table(data, colWidths=[width / n_cols] * n_cols, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, _GRID), ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
            *([("BACKGROUND", (0, -1), (-1, -1), _SUBTOTAL)] if total is not None else []),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return table


def export_bbs_to_pdf(result: BBSResult, path: str | Path, project_name: str = "Proyecto", author: str = "") -> Path:
    """Atajo para exportar ``result`` a ``path`` con un :class:`PdfExporter`."""
    return PdfExporter(project_name=project_name, author=author).export(result, path)
