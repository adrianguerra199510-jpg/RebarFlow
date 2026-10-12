import math

import pytest

from core.geometry import GeometryError
from core.rebar import (
    GRADE_40,
    REBAR_CATALOG,
    BendUse,
    HookType,
    Rebar,
    get_rebar,
    list_rebars,
    register_rebar,
)


def test_catalog_covers_3_to_11_with_consistent_masses():
    assert [r.designation for r in list_rebars()] == [f"#{n}" for n in range(3, 12)]
    for r in list_rebars():
        theoretical = math.pi / 4 * r.diameter_mm**2 * 7850 / 1e6
        assert r.linear_mass_kg_m == pytest.approx(theoretical, rel=0.01), r.designation


def test_metric_range_10_to_32_is_covered():
    assert get_rebar("10M").designation == "#3"
    assert get_rebar("32M").designation == "#10"


@pytest.mark.parametrize("key", ["#4", "4", 4, " #4 ", "13M", "13m"])
def test_get_rebar_accepts_several_formats(key):
    assert get_rebar(key).designation == "#4"


def test_get_rebar_unknown_and_grade():
    with pytest.raises(KeyError, match="#99"):
        get_rebar("#99")
    assert get_rebar(5, grade=GRADE_40).grade is GRADE_40
    assert REBAR_CATALOG["#5"].grade.fy_mpa == 420  # el catálogo no se modifica


def test_rebar_validation():
    with pytest.raises(ValueError, match="Designación"):
        Rebar("4", 12.7, 0.994)
    with pytest.raises(ValueError, match="inconsistente"):
        Rebar("#4", 12.7, 2.0)  # masa errónea para ese diámetro
    with pytest.raises(ValueError):
        Rebar("#4", -1, 0.994)


def test_register_rebar_rejects_duplicates():
    with pytest.raises(ValueError, match="ya existe"):
        register_rebar(get_rebar("#4"))


@pytest.mark.parametrize(
    ("bar", "use", "factor"),
    [("#3", BendUse.MAIN, 6), ("#8", BendUse.MAIN, 6), ("#9", BendUse.MAIN, 8), ("#11", BendUse.MAIN, 8),
     ("#3", BendUse.STIRRUP, 4), ("#5", BendUse.STIRRUP, 4), ("#6", BendUse.STIRRUP, 6), ("#8", BendUse.STIRRUP, 6)],
)
def test_minimum_bend_diameter(bar, use, factor):
    r = get_rebar(bar)
    assert r.bend_diameter_mm(use) == pytest.approx(factor * r.diameter_mm)
    assert r.bend_radius_mm(use) == pytest.approx(factor * r.diameter_mm / 2)
    assert r.centerline_radius_mm(use) == pytest.approx((factor + 1) * r.diameter_mm / 2)


def test_stirrup_bend_not_defined_above_8():
    with pytest.raises(GeometryError):
        get_rebar("#9").bend_diameter_mm(BendUse.STIRRUP)


@pytest.mark.parametrize(("bar", "leg_in"), [("#4", 8.0), ("#6", 12.0), ("#8", 16.0)])
def test_90_degree_hook_matches_aci_sp66_dimension(bar, leg_in):
    """Cota exterior A/G del gancho de 90° (ACI SP-66): #4 = 8", #6 = 12", #8 = 16"."""
    hook = get_rebar(bar).standard_hook(HookType.DEG_90)
    assert hook.outside_leg_mm == pytest.approx(leg_in * 25.4, abs=0.5)


def test_hook_extensions():
    n3, n10 = get_rebar("#3"), get_rebar("#10")
    assert n3.standard_hook(HookType.DEG_135, BendUse.STIRRUP).extension_mm == 75.0  # manda el mínimo de 75 mm
    assert get_rebar("#5").standard_hook(HookType.DEG_135, BendUse.STIRRUP).extension_mm == pytest.approx(95.25)
    assert n3.standard_hook(HookType.DEG_180).extension_mm == 65.0
    assert n10.standard_hook(HookType.DEG_180).extension_mm == pytest.approx(4 * n10.diameter_mm)
    assert get_rebar("#6").standard_hook(HookType.DEG_90, BendUse.STIRRUP).extension_mm == pytest.approx(12 * 19.05)
    with pytest.raises(GeometryError):
        n3.standard_hook(HookType.DEG_135)  # 135° solo para estribos
    with pytest.raises(GeometryError):
        n3.standard_hook(HookType.DEG_180, BendUse.STIRRUP)


def test_hook_developed_length():
    hook = get_rebar("#4").standard_hook(HookType.DEG_90)
    assert hook.developed_length_mm == pytest.approx(math.pi / 2 * 44.45 + 152.4)
    with pytest.raises(GeometryError):
        get_rebar("#4").standard_hook(HookType.DEG_180).outside_leg_mm
