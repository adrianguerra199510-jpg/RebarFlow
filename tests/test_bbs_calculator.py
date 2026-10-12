import pytest

from core.element import ElementType, StructuralElement
from core.rebar import GRADE_40, get_rebar
from core.shape_codes import StraightBar
from engine.bbs_calculator import BBSCalculator, count_stock_bars, round_up_to_step


def element(name="V-1", level="Nivel 1", qty=1, bars=()):
    el = StructuralElement(name, ElementType.BEAM, level, qty)
    for mark, rebar, length, n in bars:
        el.add_group(mark, rebar, StraightBar(length), n)
    return el


def test_round_up_to_step():
    assert round_up_to_step(1000.0, 5) == 1000.0
    assert round_up_to_step(1000.1, 5) == 1005.0
    assert round_up_to_step(1001.2, 10) == 1010.0
    assert round_up_to_step(1001.2, 0) == 1001.2


def test_line_quantities_and_weights():
    n4 = get_rebar("#4")
    result = BBSCalculator().calculate([element(qty=2, bars=[("A1", n4, 1001, 3)])])
    (line,) = result.lines
    assert line.cut_length_mm == 1005  # redondeo hacia arriba a 5 mm
    assert line.total_bars == 6  # 3 por elemento x 2 elementos
    assert line.unit_weight_kg == pytest.approx(1.005 * 0.994)
    assert line.total_length_m == pytest.approx(6.03)
    assert line.total_weight_kg == pytest.approx(6 * 1.005 * 0.994)
    assert result.total_weight_kg == pytest.approx(line.total_weight_kg)


def test_weight_aggregated_by_diameter():
    n4, n5 = get_rebar("#4"), get_rebar("#5")
    result = BBSCalculator().calculate([
        element("V-1", bars=[("A1", n4, 2000, 2), ("A2", n5, 3000, 1)]),
        element("V-2", bars=[("A1", n4, 1000, 4)]),
    ])
    by_bar = {s.rebar.designation: s for s in result.diameter_summaries}
    assert list(by_bar) == ["#4", "#5"]
    assert by_bar["#4"].total_bars == 6
    assert by_bar["#4"].total_length_m == pytest.approx(8.0)
    assert by_bar["#4"].total_weight_kg == pytest.approx(8.0 * 0.994)
    assert by_bar["#5"].total_weight_kg == pytest.approx(3.0 * 1.552)
    assert result.total_weight_kg == pytest.approx(8.0 * 0.994 + 3.0 * 1.552)


def test_different_grades_are_not_merged():
    n4 = get_rebar("#4")
    result = BBSCalculator().calculate([element(bars=[("A1", n4, 2000, 1), ("A2", n4.with_grade(GRADE_40), 2000, 1)])])
    assert len(result.diameter_summaries) == 2


def test_waste_summary():
    n4 = get_rebar("#4")
    # Piezas de 5 m: caben 2 por barra de 12 m → 5 piezas necesitan 3 barras.
    result = BBSCalculator(stock_length_mm=12000).calculate([element(bars=[("A1", n4, 5000, 5)])])
    (s,) = result.diameter_summaries
    assert s.stock_bars == 3
    assert s.purchased_length_m == pytest.approx(36.0)
    assert s.waste_length_m == pytest.approx(11.0)
    assert s.waste_pct == pytest.approx(11 / 36)
    assert s.waste_weight_kg == pytest.approx(11 * 0.994)
    assert s.purchase_weight_kg == pytest.approx(36 * 0.994)
    assert s.total_weight_kg + s.waste_weight_kg == pytest.approx(s.purchase_weight_kg)
    assert result.total_waste_pct == pytest.approx(11 / 36)


def test_zero_waste_when_pieces_fit_exactly():
    result = BBSCalculator().calculate([element(bars=[("A1", get_rebar("#4"), 6000, 4)])])
    assert result.diameter_summaries[0].stock_bars == 2
    assert result.diameter_summaries[0].waste_length_m == pytest.approx(0.0)


def test_first_fit_decreasing_packing():
    assert count_stock_bars({7000: 2, 5000: 2, 4000: 3}, 12000) == 3
    assert count_stock_bars({8000: 1, 5000: 1, 3000: 2}, 12000) == 2  # los retales se reutilizan
    assert count_stock_bars({}, 12000) == 0


def test_packing_never_loses_material():
    pieces = {2350: 17, 1430: 40, 880: 23, 5600: 3, 11990: 2}
    stock = 12000
    bars = count_stock_bars(pieces, stock)
    used = sum(length * n for length, n in pieces.items())
    assert bars * stock >= used  # cota inferior de barras comerciales
    assert bars >= -(-used // stock)


def test_bar_longer_than_stock_is_rejected():
    with pytest.raises(ValueError, match="excede la barra comercial"):
        BBSCalculator().calculate([element(bars=[("A1", get_rebar("#6"), 12500, 1)])])


def test_duplicate_element_in_same_level_is_rejected():
    with pytest.raises(ValueError, match="repetido"):
        BBSCalculator().calculate([element("V-1"), element("V-1")])
    BBSCalculator().calculate([element("V-1", "Nivel 1"), element("V-1", "Nivel 2")])  # distinto nivel: válido


def test_weight_by_level_and_diameter():
    n4 = get_rebar("#4")
    result = BBSCalculator().calculate([
        element("V-1", "Nivel 1", bars=[("A1", n4, 1000, 1)]),
        element("V-2", "Nivel 2", bars=[("A1", n4, 3000, 1)]),
    ])
    assert result.levels == ("Nivel 1", "Nivel 2")
    table = result.weight_by_level_and_diameter()
    assert table["Nivel 1"][n4] == pytest.approx(0.994)
    assert table["Nivel 2"][n4] == pytest.approx(2.982)


def test_empty_project():
    result = BBSCalculator().calculate([])
    assert result.total_weight_kg == 0 and result.total_waste_pct == 0 and result.lines == ()


def test_invalid_calculator_settings():
    with pytest.raises(ValueError):
        BBSCalculator(stock_length_mm=0)
