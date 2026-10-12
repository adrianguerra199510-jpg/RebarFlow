import math
from dataclasses import dataclass
from typing import ClassVar

import pytest

from core.geometry import GeometryError, bend_deduction
from core.rebar import BendUse, HookType, get_rebar
from core.shape_codes import (
    CutLength,
    LBar,
    ShapeCode,
    Stirrup135,
    StraightBar,
    UBar,
    available_shapes,
    create_shape,
    register_shape,
)


def test_bend_deduction_90_degrees():
    # r = 3d  →  2(4d) − (π/2)(3.5d) = 2.502d
    assert bend_deduction(90, 3.0, 1.0) == pytest.approx(2.0 * 4 - math.pi / 2 * 3.5)
    with pytest.raises(GeometryError):
        bend_deduction(0, 3.0, 1.0)


def test_straight_bar():
    cut = StraightBar(5600).cut_length(get_rebar("#6"))
    assert cut.total_mm == 5600


def test_l_bar_matches_hand_calculation():
    # #4: d = 12.7, D = 6d = 76.2, r = 38.1. Tramos rectos al eje + arco de 90°.
    rebar = get_rebar("#4")
    expected = (1000 - 50.8) + (300 - 50.8) + math.pi / 2 * (38.1 + 6.35)
    assert LBar(1000, 300).cut_length(rebar).total_mm == pytest.approx(expected)


def test_u_bar_is_two_bends():
    rebar = get_rebar("#5")
    r, d = rebar.bend_radius_mm(), rebar.diameter_mm
    expected = (1650 + 254 + 254) - 2 * bend_deduction(90, r, d)
    assert UBar(1650, 254, 254).cut_length(rebar).total_mm == pytest.approx(expected)


def test_standard_hook_constructors():
    rebar = get_rebar("#4")
    assert LBar.with_standard_hook(rebar, 1000).b == pytest.approx(203.2)
    u = UBar.with_standard_hooks(rebar, 800)
    assert u.b == u.c == pytest.approx(203.2)


def _turtle_stirrup(a: float, b: float, rebar, ext: float):
    """Recorre el estribo con rectas y arcos y devuelve (longitud, ancho, alto) del eje."""
    R = rebar.centerline_radius_mm(BendUse.STIRRUP)
    W, H = a - rebar.diameter_mm, b - rebar.diameter_mm
    # (tipo, valor): recta en mm o giro antihorario en grados con radio R.
    path = [("s", ext), ("t", 135), ("s", H - 2 * R), ("t", 90), ("s", W - 2 * R), ("t", 90),
            ("s", H - 2 * R), ("t", 90), ("s", W - 2 * R), ("t", 135), ("s", ext)]
    x = y = 0.0
    heading = 135.0  # la cola del primer gancho entra al núcleo a 45°
    length, xs, ys = 0.0, [0.0], [0.0]
    for kind, value in path:
        if kind == "s":
            x += value * math.cos(math.radians(heading))
            y += value * math.sin(math.radians(heading))
            length += value
            xs.append(x), ys.append(y)
        else:
            for k in range(1, 91):  # muestreo del arco
                step = math.radians(value) / 90
                h0 = math.radians(heading) + (k - 1) * step
                x += R * (math.sin(h0 + step) - math.sin(h0))
                y += R * (-math.cos(h0 + step) + math.cos(h0))
                xs.append(x), ys.append(y)
            length += math.radians(value) * R
            heading += value
    return length, max(xs) - min(xs), max(ys) - min(ys)


@pytest.mark.parametrize(("bar", "a", "b"), [("#3", 220, 420), ("#3", 320, 320), ("#4", 300, 600), ("#5", 250, 350)])
def test_stirrup_length_matches_independent_path_walk(bar, a, b):
    rebar = get_rebar(bar)
    cut = Stirrup135(a, b).cut_length(rebar)
    ext = rebar.standard_hook(HookType.DEG_135, BendUse.STIRRUP).extension_mm
    length, width, height = _turtle_stirrup(a, b, rebar, ext)
    assert cut.total_mm == pytest.approx(length, abs=1e-6)
    # El eje encierra exactamente (a − d) x (b − d): la cota exterior es a x b.
    assert width == pytest.approx(a - rebar.diameter_mm, abs=0.05)
    assert height == pytest.approx(b - rebar.diameter_mm, abs=0.05)


def test_stirrup_default_extension_and_warning_for_short_hook():
    rebar = get_rebar("#3")
    ok = Stirrup135(220, 420).cut_length(rebar)
    assert ok.extension_mm == 150.0 and not ok.warnings
    short = Stirrup135(220, 420, hook_extension_mm=50).cut_length(rebar)
    assert short.extension_mm == 100.0
    assert short.warnings and "75" in short.warnings[0]


@pytest.mark.parametrize(
    ("shape", "bar"),
    [(LBar(30, 300), "#4"), (LBar(1000, 40), "#4"), (UBar(100, 300, 300), "#5"),
     (Stirrup135(50, 400), "#3"), (Stirrup135(400, 50), "#3")],
)
def test_impossible_geometry_is_rejected(shape, bar):
    with pytest.raises(GeometryError, match="mínimo geométrico"):
        shape.cut_length(get_rebar(bar))


def test_stirrup_minimum_side_is_bend_diameter_plus_two_bars():
    # #3: D = 4d = 38.1 mm → lado mínimo exterior D + 2d = 57.15 mm
    Stirrup135(57.2, 57.2).cut_length(get_rebar("#3"))
    with pytest.raises(GeometryError):
        Stirrup135(57.0, 57.2).cut_length(get_rebar("#3"))


def test_stirrup_with_large_bar_is_rejected():
    with pytest.raises(GeometryError):
        Stirrup135(400, 400).cut_length(get_rebar("#9"))


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf"), "300", True])
def test_dimensions_must_be_positive_numbers(bad):
    with pytest.raises(GeometryError):
        StraightBar(bad)
    with pytest.raises(GeometryError):
        LBar(1000, bad)


def test_registry_and_extensibility():
    assert {"R", "L", "U", "E"} <= set(available_shapes())
    assert create_shape("L", a=1000, b=300) == LBar(1000, 300)
    with pytest.raises(KeyError):
        create_shape("??", a=1)

    @register_shape
    @dataclass(frozen=True)
    class Hairpin(ShapeCode):
        code: ClassVar[str] = "TEST-H"
        name: ClassVar[str] = "Horquilla de prueba"
        a: float

        def dimensions(self):
            return {"A": self.a}

        def cut_length(self, rebar):
            return CutLength(self.a, -10.0)

    assert create_shape("TEST-H", a=500).cut_length(get_rebar("#3")).total_mm == 490.0
    with pytest.raises(GeometryError):
        create_shape("TEST-H", a=-1)

    with pytest.raises(ValueError, match="ya está registrado"):
        @register_shape
        @dataclass(frozen=True)
        class Clash(ShapeCode):
            code: ClassVar[str] = "TEST-H"
            name: ClassVar[str] = "Choque"
            a: float

            def dimensions(self):
                return {}

            def cut_length(self, rebar):
                return CutLength(self.a)
