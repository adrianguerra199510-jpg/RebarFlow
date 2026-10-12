"""Proyecto de ejemplo: edificio sencillo (cimentación + 2 niveles) usado por ``main.py`` y la interfaz."""

from __future__ import annotations

from core.element import ElementType, StructuralElement
from core.project import Project
from core.rebar import get_rebar
from core.shape_codes import LBar, Stirrup90, Stirrup135, StraightBar, UBar
from core.shape_templates import (
    CrankBar, CustomBar, HookedBar, OmegaBar, RingTie, Spiral, TrapStirrup, TriStirrup, UStirrup, ZBar,
)

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


def build_elements() -> list[StructuralElement]:
    return [
        build_footing("Z-1", "Cimentación", 6),
        build_column("C-1", "Nivel 1", 6, section_mm=400, height_mm=3000),
        build_beam("V-101", "Nivel 1", 4),
        build_column("C-1", "Nivel 2", 6, section_mm=400, height_mm=3000),
        build_beam("V-201", "Nivel 2", 4),
    ]


def build_project() -> Project:
    return Project(name="Edificio de ejemplo", author="RebarFlow", elements=build_elements())


def build_catalog_project() -> Project:
    """Una barra de cada plantilla del catálogo de formas (en un elemento de tipo «Otros»), para ver y probar todas."""
    n3, n4, n5 = get_rebar("#3"), get_rebar("#4"), get_rebar("#5")
    element = StructuralElement("Catálogo", ElementType.OTHER, "Ejemplos", 1)
    rows = [
        ("R1", n5, StraightBar(3000), 4, "Recta"),
        ("L1", n5, LBar.with_standard_hook(n5, a=1200), 4, "Bastón L con gancho estándar de 90°"),
        ("U1", n5, UBar.with_standard_hooks(n5, a=1650), 4, "Gancho U con patas de 90°"),
        ("G1", n4, HookedBar(a=1800, hook_start=90, hook_end=180), 6, "Ganchos de 90° y 180°"),
        ("G2", n3, HookedBar(a=320, hook_start=135, hook_end=90, style="stirrup"), 20, "Traba: gancho de 135° y de 90°"),
        ("E1", n3, Stirrup135(320, 320), 24, "Estribo rectangular, ganchos a 135°"),
        ("E2", n3, Stirrup90(220, 420), 24, "Estribo rectangular, ganchos a 90°"),
        ("EU1", n3, UStirrup(a=300, b=400, hook=135), 12, "Estribo abierto en U, ganchos a 135°"),
        ("Z1", n5, ZBar(a=250, b=200, c=250), 8, "Barra en Z"),
        ("Q1", n4, CrankBar(a=900, b=350, c=900, angle=45), 10, "Quiebre a 45°"),
        ("O1", n3, OmegaBar(a=200, b=300, c=400, d=300, e=200), 10, "Omega"),
        ("ET1", n3, TriStirrup(a=300, b=300, c=300, hook=135), 10, "Estribo triangular"),
        ("ETR1", n3, TrapStirrup(bottom=400, top=250, height=300, hook=135), 10, "Estribo trapezoidal"),
        ("AR1", n3, RingTie(diameter=400, lap=250), 20, "Aro circular con traslape"),
        ("ES1", n3, Spiral(diameter=400, pitch=75, height=2400), 2, "Espiral (se suministra en rollo)"),
        ("X1", n4, CustomBar(legs=(300.0, 200.0, 300.0, 250.0), angles=(90.0, -90.0, 60.0), hook_end=90), 6,
         "Forma dibujada a mano: 4 tramos, giros de 90°, −90° y 60° y gancho final de 90°"),
    ]
    for mark, rebar, shape, quantity, description in rows:
        element.add_group(mark, rebar, shape, quantity, description)
    return Project(name="Catálogo de formas", author="RebarFlow", elements=[element])
