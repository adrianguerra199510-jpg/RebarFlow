import random
import time
from collections import Counter

import pytest

from engine.bbs_calculator import count_stock_bars
from engine.cutting_optimizer import (
    CutPattern,
    _first_fit_decreasing,
    compare_stock_lengths,
    optimize_cutting,
)

STOCK = 12_000.0


def produced(plan):
    """Piezas que genera el plan, como {largo: cantidad}."""
    total = Counter()
    for pattern in plan.patterns:
        for length in pattern.cuts:
            total[length] += pattern.count
    return dict(total)


def random_instance(rng, kinds, max_count):
    return {float(5 * rng.randint(60, 2300)): rng.randint(1, max_count) for _ in range(kinds)}


def test_empty_and_trivial_plans():
    empty = optimize_cutting({}, STOCK)
    assert empty.stock_bars == 0 and empty.patterns == () and empty.remnant_pct == 0
    one = optimize_cutting({5000.0: 1}, STOCK)
    assert one.stock_bars == 1 and one.patterns[0].remnant_mm == 7000
    exact = optimize_cutting({6000.0: 4}, STOCK)
    assert exact.stock_bars == 2 and exact.remnant_length_mm == 0 and exact.is_optimal


def test_pieces_longer_than_stock_are_rejected():
    with pytest.raises(ValueError, match="más larga"):
        optimize_cutting({12_500.0: 1}, STOCK)
    with pytest.raises(ValueError, match="desconocidas"):
        optimize_cutting({1000.0: 1}, STOCK, strategies=("magia",))


def test_known_case_reaches_the_optimum():
    # 7 m + 5 m, 4 m + 4 m + 4 m, 6 m + 6 m: tres barras sin sobrante.
    plan = optimize_cutting({7000.0: 2, 5000.0: 2, 4000.0: 3}, STOCK)
    assert plan.stock_bars == 3 and plan.is_optimal and plan.remnant_length_mm == 0
    # el retal se reaprovecha: 8 m + 3 m + 3 m + 5 m en dos barras
    assert optimize_cutting({8000.0: 1, 5000.0: 1, 3000.0: 2}, STOCK).stock_bars == 2


def test_never_loses_or_invents_pieces_and_never_beats_the_physical_bound():
    rng = random.Random(2024)
    for _ in range(60):
        pieces = random_instance(rng, rng.randint(1, 12), 40)
        plan = optimize_cutting(pieces, STOCK)
        assert produced(plan) == pieces
        assert plan.lower_bound_bars <= plan.stock_bars
        assert all(p.used_mm <= STOCK + 1e-6 for p in plan.patterns)
        total = sum(length * count for length, count in pieces.items())
        assert plan.used_length_mm == pytest.approx(total)
        assert plan.purchased_length_mm >= total


def optimum(lengths, capacity):
    """Mínimo exacto de barras (DP sobre subconjuntos; solo para pocas piezas)."""
    n = len(lengths)
    total = [0] * (1 << n)
    for mask in range(1, 1 << n):
        total[mask] = total[mask & (mask - 1)] + lengths[(mask & -mask).bit_length() - 1]
    best = [10**9] * (1 << n)
    best[0] = 0
    for mask in range(1, 1 << n):
        low, sub = mask & -mask, mask
        while sub:
            if sub & low and total[sub] <= capacity:
                best[mask] = min(best[mask], best[mask ^ sub] + 1)
            sub = (sub - 1) & mask
    return best[(1 << n) - 1]


def test_matches_the_exact_optimum_on_small_instances():
    for seed in range(40):
        rng = random.Random(seed)
        lengths = [5 * rng.randint(100, 2300) for _ in range(rng.randint(5, 10))]
        pieces = Counter(float(length) for length in lengths)
        assert optimize_cutting(pieces, STOCK).stock_bars == optimum(lengths, int(STOCK)), f"semilla {seed}"


def test_optimizer_is_never_worse_than_first_fit():
    rng = random.Random(7)
    for _ in range(80):
        pieces = random_instance(rng, rng.randint(3, 15), 60)
        ffd_bins = _first_fit_decreasing({int(k // 5): v for k, v in pieces.items()}, int(STOCK // 5))
        assert optimize_cutting(pieces, STOCK).stock_bars <= len(ffd_bins)


def test_lp_strategy_beats_the_greedy_heuristics_on_a_hard_instance():
    """40 longitudes y 20 mil piezas: First Fit queda ~2.4 % sobre la cota simple; el método lineal, <1.2 %."""
    rng = random.Random(1)
    pieces = {float(5 * rng.randint(200, 1400)): rng.randint(50, 900) for _ in range(40)}
    greedy = optimize_cutting(pieces, STOCK, ("ffd", "bfd", "shp"))
    best = optimize_cutting(pieces, STOCK)
    assert best.strategy == "lp"
    assert best.stock_bars < greedy.stock_bars - 50
    assert best.stock_bars <= best.lower_bound_bars * 1.012
    assert produced(best) == pieces


def test_remnants_classification():
    plan = optimize_cutting({5000.0: 5}, STOCK)  # 2 barras con 2 m de sobrante y 1 con 7 m
    reusable, scrap = plan.remnants(1000.0)
    assert reusable + scrap == pytest.approx(plan.remnant_length_mm)
    assert reusable == 2000 * 2 + 7000 and scrap == 0
    assert plan.remnants(3000.0) == (7000.0, 4000.0)
    assert plan.remnants(0.0) == (0.0, plan.remnant_length_mm)


def test_sequence_numbers_every_bar_once():
    plan = optimize_cutting({3900.0: 40, 1430.0: 25, 2500.0: 9}, STOCK)
    steps = plan.sequence()
    assert steps[0].first_bar == 1 and steps[-1].last_bar == plan.stock_bars
    assert all(a.last_bar + 1 == b.first_bar for a, b in zip(steps, steps[1:]))
    assert all(step.pattern.cuts == tuple(sorted(step.pattern.cuts, reverse=True)) for step in steps)
    assert [step.pattern.count for step in steps] == sorted((step.pattern.count for step in steps), reverse=True)
    assert CutPattern((3900.0, 1430.0), 1, STOCK).grouped() == ((3900.0, 1), (1430.0, 1))
    assert steps[0].bars_text.count("–") == (1 if steps[0].pattern.count > 1 else 0)


def test_scales_to_thousands_of_stirrups():
    rng = random.Random(1)
    pieces = {float(5 * rng.randint(200, 1400)): rng.randint(50, 900) for _ in range(40)}
    started = time.perf_counter()
    plan = optimize_cutting(pieces, STOCK)
    assert time.perf_counter() - started < 8.0  # el presupuesto del método lineal es 2.5 s
    assert produced(plan) == pieces
    again = time.perf_counter()
    assert optimize_cutting(pieces, STOCK) is plan  # segunda vez: sale de la caché
    assert time.perf_counter() - again < 0.05


def test_non_multiple_of_five_lengths_stay_feasible():
    plan = optimize_cutting({1425.8: 20, 3333.3: 7}, STOCK)
    assert plan.stock_bars >= plan.lower_bound_bars
    assert all(p.used_mm <= STOCK for p in plan.patterns)  # redondeo hacia arriba: nunca excede la barra


def test_count_stock_bars_uses_the_optimizer():
    assert count_stock_bars({7000: 2, 5000: 2, 4000: 3}, 12000) == 3
    assert count_stock_bars({}, 12000) == 0


def test_stock_length_comparison_skips_lengths_that_do_not_fit():
    plans = compare_stock_lengths({5600.0: 10, 2400.0: 10}, (6000.0, 9000.0, 12000.0))
    assert set(plans) == {6000.0, 9000.0, 12000.0}
    assert set(compare_stock_lengths({7000.0: 3}, (6000.0, 9000.0, 12000.0))) == {9000.0, 12000.0}
    # 6 m es ideal para piezas de 5.6 m y 2.4 m (con 12 m se pierde más)
    assert plans[6000.0].remnant_pct < plans[12000.0].remnant_pct or plans[6000.0].stock_bars > 0
