"""Espiral suministrada en carrete o con barras individuales (traslapes o couplers)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from core.element import ElementType, StructuralElement
from core.geometry import GeometryError
from core.params import ParamSpec, param
from core.project import Project
from core.rebar import get_rebar
from core.serialization import project_from_dict, project_to_dict
from core.shape_templates import Spiral
from core.splice import coupler_pieces, lap_pieces, pieces_text, standard_lap_mm
from engine.bbs_calculator import BBSCalculator

N4 = get_rebar("#4")
STOCK = 12_000.0
BIG = {"diameter": 1100.0, "pitch": 100.0, "height": 5600.0}  # ~ 200 m desarrollados


def bbs(shape, *, quantity=1, elements=1, stock=STOCK):
    element = StructuralElement("C-1", ElementType.COLUMN, quantity=elements)
    element.add_group("F1", N4, shape, quantity)
    return BBSCalculator(stock_length_mm=stock).calculate([element])


# ------------------------------------------------------------------ piezas
def test_lap_pieces_add_one_lap_per_joint_and_never_exceed_the_stock_bar():
    for total in (12_001.0, 23_500.0, 24_000.0, 99_999.0, 201_183.0):
        pieces = lap_pieces(total, STOCK, 610.0)
        joints = len(pieces) - 1
        assert sum(pieces) == pytest.approx(total + joints * 610.0)
        assert all(0 < p <= STOCK + 1e-6 for p in pieces)
        assert pieces[-1] > 610.0 - 1e-6  # el resto siempre cubre al menos el traslape
        assert all(p == STOCK for p in pieces[:-1])  # todo lo posible en barras completas


def test_lap_pieces_minimise_bars():
    # 24 m con traslape de 0.6 m: dos barras no alcanzan (23.4 m útiles), hacen falta tres
    assert len(lap_pieces(24_000.0, STOCK, 600.0)) == 3
    assert len(lap_pieces(23_400.0, STOCK, 600.0)) == 2


def test_coupler_pieces_butt_the_bars_without_changing_the_length():
    pieces = coupler_pieces(30_000.0, STOCK)
    assert pieces == (12_000.0, 12_000.0, 6_000.0) and sum(pieces) == 30_000.0
    assert coupler_pieces(24_000.0, STOCK) == (12_000.0, 12_000.0)


def test_short_pieces_are_a_single_bar_without_joints():
    assert lap_pieces(8_000.0, STOCK, 610.0) == (8_000.0,) == coupler_pieces(8_000.0, STOCK)
    assert pieces_text((8_000.0,)) == ""


def test_a_lap_longer_than_half_the_bar_is_rejected():
    with pytest.raises(GeometryError, match="mitad"):
        lap_pieces(30_000.0, STOCK, 7_000.0)


def test_standard_lap_is_48_diameters_but_not_less_than_300_mm():
    assert standard_lap_mm(N4) == pytest.approx(48 * N4.diameter_mm)  # #4: 609.6 mm
    assert standard_lap_mm(get_rebar("#3")) == pytest.approx(48 * get_rebar("#3").diameter_mm)  # 457 mm
    assert standard_lap_mm(SimpleNamespace(diameter_mm=6.0)) == 300.0  # 48 d = 288 mm < 300 mm: manda el mínimo


def test_pieces_text():
    assert pieces_text((12_000.0, 12_000.0, 12_000.0, 4_320.0)) == "3 × 12.00 m + 4.32 m"
    assert pieces_text((12_000.0, 4_320.0)) == "12.00 m + 4.32 m"


# ------------------------------------------------------------------ forma
def test_the_spiral_comes_from_a_coil_by_default_and_does_not_change_its_length():
    shape = Spiral(**BIG)
    supply = shape.supply(N4, STOCK)
    assert supply.coil and supply.couplers == () and supply.pieces_mm == (pytest.approx(shape.cut_length(N4).total_mm),)


def test_a_spiral_from_bars_that_fits_one_bar_has_no_joints():
    supply = Spiral(300, 75, 300, supply_mode="bars").supply(N4, STOCK)
    assert not supply.coil and len(supply.pieces_mm) == 1 and supply.couplers == ()


def test_a_long_spiral_from_bars_is_lapped_by_default_with_the_standard_lap():
    shape = Spiral(**BIG, supply_mode="bars")
    total = shape.cut_length(N4).total_mm
    supply = shape.supply(N4, STOCK)
    joints = len(supply.pieces_mm) - 1
    assert joints == math.ceil((total - 609.6) / (STOCK - 609.6) - 1e-9) - 1
    assert supply.material_mm == pytest.approx(total + joints * standard_lap_mm(N4))
    assert supply.couplers == () and supply.warnings == () and f"{joints} traslapes de 610 mm" in supply.notes[0]


def test_a_custom_lap_is_used_and_a_short_one_gets_a_warning():
    long_lap = Spiral(**BIG, supply_mode="bars", lap_mm=800.0).supply(N4, STOCK)
    assert long_lap.warnings == () and "traslapes de 800 mm" in long_lap.notes[0]
    short = Spiral(**BIG, supply_mode="bars", lap_mm=200.0).supply(N4, STOCK)
    assert len(short.warnings) == 1 and "200 mm" in short.warnings[0] and "48·d" in short.warnings[0]


def test_a_spiral_from_bars_with_couplers_keeps_the_length_and_counts_a_coupler_per_joint():
    shape = Spiral(**BIG, supply_mode="bars", joint="coupler", joint_coupler="long")
    supply = shape.supply(N4, STOCK)
    assert supply.material_mm == pytest.approx(shape.cut_length(N4).total_mm)
    assert supply.couplers == ("long",) * (len(supply.pieces_mm) - 1) and len(supply.couplers) > 10
    assert supply.warnings == ()


def test_the_unused_options_do_not_change_the_result():
    a = Spiral(**BIG, supply_mode="bars", joint="lap", joint_coupler="long").supply(N4, STOCK)
    b = Spiral(**BIG, supply_mode="bars", joint="lap", joint_coupler="short").supply(N4, STOCK)
    assert a == b
    assert Spiral(**BIG, supply_mode="coil", joint="coupler").supply(N4, STOCK).coil


def test_unknown_supply_options_are_rejected():
    for bad in ({"supply_mode": "rollo"}, {"joint": "soldadura"}, {"joint_coupler": "none"}):
        with pytest.raises(GeometryError):
            Spiral(**BIG, **bad)


def test_param_dependencies():
    specs = {spec.name: spec for spec in Spiral.parameters()}
    assert specs["supply_mode"].depends == () and specs["joint"].active({"supply_mode": "bars"})
    assert not specs["joint"].active({"supply_mode": "coil"})
    assert specs["lap_mm"].active({"supply_mode": "bars", "joint": "lap"})
    assert not specs["lap_mm"].active({"supply_mode": "bars", "joint": "coupler"})
    assert specs["joint_coupler"].active({"supply_mode": "bars", "joint": "coupler"})
    assert not specs["joint_coupler"].active({"supply_mode": "bars", "joint": None})
    assert ParamSpec("x", "x", "length", 1.0).active({})  # sin condiciones, siempre aplica
    assert param("x", depends=(("a", 1),)).metadata["spec"].depends == (("a", 1),)


# ------------------------------------------------------------------ planilla
def test_the_coil_spiral_is_unchanged_in_the_schedule():
    result = bbs(Spiral(**BIG), quantity=2, elements=3)
    line = result.lines[0]
    summary = result.diameter_summaries[0]
    assert line.supply.coil and line.joint_count == 0 and line.pieces_text == "" and line.couplers == ()
    assert summary.pieces == {} and summary.stock_bars == 0
    assert summary.coil_length_m == pytest.approx(line.total_length_m)


def test_a_lapped_spiral_weighs_and_counts_the_laps_and_enters_the_cutting_plan():
    shape = Spiral(**BIG, supply_mode="bars")
    result = bbs(shape, quantity=2, elements=3)  # 6 espirales
    line = result.lines[0]
    summary = result.diameter_summaries[0]
    developed = shape.cut_length(N4).total_mm
    joints = line.joint_count
    assert joints > 10 and not line.supply.coil
    assert line.cut_length_mm == pytest.approx(sum(line.supply.pieces_mm)) and line.cut_length_mm > developed
    assert line.cut_length_mm == pytest.approx(developed + joints * 609.6, abs=40)  # + redondeo de 5 mm por barra
    assert line.total_weight_kg == pytest.approx(6 * N4.mass_for_length(line.cut_length_mm / 1000))
    assert line.total_length_m == pytest.approx(6 * line.cut_length_mm / 1000)
    assert sum(length * count for length, count in summary.pieces.items()) / 1000 == pytest.approx(line.total_length_m)
    assert summary.pieces[STOCK] == 6 * joints  # barras comerciales completas
    assert summary.coil_length_m == 0 and summary.stock_bars >= 6 * joints + 1
    assert "C-1/F1" in summary.marks_for(STOCK)
    assert line.pieces_text.startswith(f"{joints} × 12.00 m + ")


def test_couplers_of_the_joints_are_counted_in_the_summary():
    shape = Spiral(**BIG, supply_mode="bars", joint="coupler", joint_coupler="short")
    result = bbs(shape, quantity=2, elements=3)
    line = result.lines[0]
    assert line.cut_length_mm == pytest.approx(shape.cut_length(N4).total_mm, abs=40)
    assert line.couplers == ("short",) * line.joint_count and line.coupler_text == f"{line.joint_count} × rosca corta"
    (count,) = result.coupler_counts()
    assert (count.rebar, count.kind, count.count) == (N4, "short", 6 * line.joint_count)


def test_the_stock_length_of_the_calculator_decides_the_number_of_bars():
    shape = Spiral(**BIG, supply_mode="bars", joint="coupler")
    short = bbs(shape, stock=6_000.0).lines[0]
    long = bbs(shape, stock=12_000.0).lines[0]
    assert short.joint_count > long.joint_count * 1.9


def test_lap_warnings_reach_the_schedule_and_the_detail():
    result = bbs(Spiral(**BIG, supply_mode="bars", lap_mm=200.0))
    assert any("200 mm" in text for _, _, text in result.warnings)
    assert any("Suministro" in note for note in result.lines[0].notes)


def test_ordinary_bars_still_have_to_fit_in_the_stock_bar():
    from core.shape_codes import StraightBar

    element = StructuralElement("V-1", ElementType.BEAM)
    element.add_group("A", N4, StraightBar(13_000), 1)
    with pytest.raises(ValueError, match="excede la barra comercial"):
        BBSCalculator().calculate([element])


# ------------------------------------------------------------------ archivos
def test_the_supply_options_survive_save_and_load():
    shape = Spiral(**BIG, supply_mode="bars", joint="coupler", joint_coupler="long")
    project = Project(name="P")
    element = StructuralElement("C-1", ElementType.COLUMN)
    element.add_group("F1", N4, shape, 1)
    project.elements.append(element)
    copy = project_from_dict(project_to_dict(project))
    assert copy.elements[0].groups[0].shape == shape
    lapped = Spiral(**BIG, supply_mode="bars", lap_mm=700.0)
    element.groups[0] = type(element.groups[0])("F1", N4, lapped, 1)
    assert project_from_dict(project_to_dict(project)).elements[0].groups[0].shape.lap_mm == 700.0


def test_projects_saved_before_have_a_coil_spiral():
    project = Project(name="P")
    element = StructuralElement("C-1", ElementType.COLUMN)
    element.add_group("F1", N4, Spiral(**BIG), 1)
    project.elements.append(element)
    data = project_to_dict(project)
    params = data["elements"][0]["groups"][0]["shape"]["dimensions"]
    for key in ("supply_mode", "joint", "lap_mm", "joint_coupler"):
        params.pop(key, None)
    shape = project_from_dict(data).elements[0].groups[0].shape
    assert shape.supply_mode == "coil" and shape.supply(N4, STOCK).coil


# ------------------------------------------------------------------ exportación
def test_exports_list_the_marks_built_from_joined_bars(tmp_path):
    from openpyxl import load_workbook

    from exporters.excel_exporter import ExcelExporter
    from exporters.pdf_exporter import PdfExporter

    result = bbs(Spiral(**BIG, supply_mode="bars"))
    assert [(e, m) for e, m, _ in result.supply_notes] == [("C-1", "F1")]
    assert bbs(Spiral(**BIG)).supply_notes == ()  # el carrete no tiene uniones
    sheet = load_workbook(ExcelExporter().export(result, tmp_path / "p.xlsx")).worksheets[0]
    texts = [str(c.value) for row in sheet.iter_rows() for c in row if c.value is not None]
    assert "Suministro con uniones" in texts and any(t.startswith("C-1 · marca F1: ") and "traslapes" in t and "× 12.00 m" in t for t in texts)
    pdf = PdfExporter().export(result, tmp_path / "p.pdf")
    assert pdf.stat().st_size > 5_000
