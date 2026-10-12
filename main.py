"""Ejemplo funcional por línea de comandos: planilla de un edificio sencillo (cimentación + 2 niveles).

Uso::

    python main.py                       # escribe output/planilla_bbs.xlsx y .pdf
    python main.py -o mi_planilla.xlsx   # el PDF se escribe junto al Excel
    python -m gui                        # interfaz gráfica
"""

from __future__ import annotations

import argparse
from pathlib import Path

from engine.bbs_calculator import BBSCalculator, BBSResult
from exporters.excel_exporter import ExcelExporter
from exporters.pdf_exporter import PdfExporter
from sample_project import build_project


def print_summary(result: BBSResult) -> None:
    print(f"{'Barra':<7}{'Barras':>8}{'Long. (m)':>12}{'Peso (kg)':>12}{'Comerciales':>13}{'Desperd. %':>12}")
    for s in result.diameter_summaries:
        print(f"{s.rebar.designation:<7}{s.total_bars:>8}{s.total_length_m:>12.1f}{s.total_weight_kg:>12.1f}"
              f"{s.stock_bars:>13}{s.waste_pct:>11.1%} ")
    print(f"{'TOTAL':<7}{'':>8}{result.total_length_m:>12.1f}{result.total_weight_kg:>12.1f}"
          f"{'':>13}{result.total_waste_pct:>11.1%} ")
    for line in result.lines:
        for warning in line.warnings:
            print(f"AVISO {line.element.name}/{line.mark}: {warning}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera una planilla de despiece de ejemplo en Excel y PDF.")
    parser.add_argument("-o", "--output", type=Path, default=Path("output/planilla_bbs.xlsx"))
    args = parser.parse_args()

    project = build_project()
    result = BBSCalculator(project.stock_length_mm, project.length_rounding_mm, project.reusable_remnant_mm).calculate(project.elements)
    print_summary(result)
    excel = ExcelExporter(project.name, project.author).export(result, args.output)
    pdf = PdfExporter(project.name, project.author, page_size=project.paper).export(result, args.output.with_suffix(".pdf"))
    print(f"\nPlanillas escritas en {excel} y {pdf}")


if __name__ == "__main__":
    main()
