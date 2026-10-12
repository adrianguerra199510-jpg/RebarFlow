"""Ejemplo funcional: planilla de despiece de un edificio sencillo (cimentación + 2 niveles).

Uso::

    python main.py                       # escribe output/planilla_bbs.xlsx
    python main.py -o mi_planilla.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

from core.element import ElementType, StructuralElement
from core.rebar import get_rebar
from core.shape_codes import LBar, Stirrup135, StraightBar, UBar
from engine.bbs_calculator import BBSCalculator, BBSResult
from exporters.excel_exporter import ExcelExporter

COVER_MM = 40.0  # recubrimiento libre al estribo


def build_beam(name: str, level: str, quantity: int) -> StructuralElement:
    """Viga de 300 x 500 mm y 5.30 m entre caras de columna, con estribos #3."""
    beam = StructuralElement(name, ElementType.BEAM, level, quantity)
    n6, n5, n3 = get_rebar("#6"), get_rebar("#5"), get_rebar("#3")

    # Refuerzo inferior: 3 barras rectas ancladas en las columnas.
    beam.add_group("A1", n6, StraightBar(5600), 3, "Refuerzo inferior")
    # Refuerzo superior: 2 barras en U con ganchos estándar de 90° en ambos extremos.
    beam.add_group("A2", n6, UBar.with_standard_hooks(n6, a=5500), 2, "Refuerzo superior con ganchos")
    # Bastones en los apoyos: L con tramo vertical de 350 mm.
    beam.add_group("A3", n5, LBar(a=1500, b=350), 4, "Bastón en apoyo")
    # Estribos cerrados: cotas exteriores = sección − 2 x recubrimiento.
    beam.add_group("E1", n3, Stirrup135(300 - 2 * COVER_MM, 500 - 2 * COVER_MM), 38, "Estribos @100/@200")
    return beam


def build_column(name: str, level: str, quantity: int, section_mm: float, height_mm: float) -> StructuralElement:
    """Columna cuadrada con 8 barras longitudinales #7 y estribos #3 de confinamiento."""
    column = StructuralElement(name, ElementType.COLUMN, level, quantity)
    column.add_group("C1", get_rebar("#7"), StraightBar(height_mm + 900), 8, "Barras longitudinales")
    side = section_mm - 2 * COVER_MM
    column.add_group("E1", get_rebar("#3"), Stirrup135(side, side), 26, "Estribos @100/@150")
    return column


def build_footing(name: str, level: str, quantity: int) -> StructuralElement:
    """Zapata aislada de 1.80 x 1.80 m con parrilla inferior de barras #5 con ganchos de 90°."""
    footing = StructuralElement(name, ElementType.FOOTING, level, quantity)
    n5 = get_rebar("#5")
    mesh_width = 1800 - 2 * 75  # recubrimiento de 75 mm contra el terreno
    footing.add_group("Z1", n5, UBar.with_standard_hooks(n5, a=mesh_width), 10, "Parrilla inferior X")
    footing.add_group("Z2", n5, UBar.with_standard_hooks(n5, a=mesh_width), 10, "Parrilla inferior Y")
    return footing


def build_project() -> list[StructuralElement]:
    return [
        build_footing("Z-1", "Cimentación", 6),
        build_column("C-1", "Nivel 1", 6, section_mm=400, height_mm=3000),
        build_beam("V-101", "Nivel 1", 4),
        build_column("C-1", "Nivel 2", 6, section_mm=400, height_mm=3000),
        build_beam("V-201", "Nivel 2", 4),
    ]


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
    parser = argparse.ArgumentParser(description="Genera una planilla de despiece de ejemplo en Excel.")
    parser.add_argument("-o", "--output", type=Path, default=Path("output/planilla_bbs.xlsx"))
    args = parser.parse_args()

    result = BBSCalculator(stock_length_mm=12_000, length_rounding_mm=5).calculate(build_project())
    print_summary(result)
    path = ExcelExporter(project_name="Edificio de ejemplo", author="RebarFlow").export(result, args.output)
    print(f"\nPlanilla escrita en {path}")


if __name__ == "__main__":
    main()
