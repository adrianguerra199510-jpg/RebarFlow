import math

import pytest

from core.geometry import GeometryError
from core.rebar import BendUse, HookType, get_rebar
from core.serialization import project_from_dict, project_to_dict
from core.project import Project
from core.element import ElementType, StructuralElement
from core.shape_codes import (
    LBar,
    Stirrup90,
    Stirrup135,
    UBar,
    available_shapes,
    create_shape,
)
from core.shape_templates import (
    CrankBar,
    CustomBar,
    HookedBar,
    OmegaBar,
    RingTie,
    Spiral,
    TrapStirrup,
    TriStirrup,
    UStirrup,
    ZBar,
)
from engine.bbs_calculator import BBSCalculator

N3, N4, N5, N6 = (get_rebar(n) for n in ("#3", "#4", "#5", "#6"))


def delta90(rebar, use=BendUse.MAIN):
    r, d = rebar.bend_radius_mm(use), rebar.diameter_mm
    return 2 * (r + d) - math.pi / 2 * (r + d / 2)


def walk(items, heading=0.0):
    """Recorre una barra con rectas y arcos y devuelve (longitud, ancho, alto) del eje."""
    x = y = 0.0
    heading = math.radians(heading)
    length, xs, ys = 0.0, [0.0], [0.0]
    for item in items:
        if item[0] == "s":
            x, y = x + item[1] * math.cos(heading), y + item[1] * math.sin(heading)
            length += item[1]
            xs.append(x), ys.append(y)
        else:  # ("t", grados con signo, radio)
            turn, radius = math.radians(item[1]), item[2]
            sign = 1 if turn > 0 else -1
            steps = 200
            for k in range(steps):
                h0 = heading + turn * k / steps
                h1 = heading + turn * (k + 1) / steps
                x += sign * radius * (math.sin(h1) - math.sin(h0))
                y += -sign * radius * (math.cos(h1) - math.cos(h0))
                xs.append(x), ys.append(y)
            length += abs(turn) * radius
            heading += turn
    return length, max(xs) - min(xs), max(ys) - min(ys)


# ------------------------------------------------------------------ catálogo
def test_catalog_contains_every_requested_typology():
    codes = set(available_shapes())
    assert {"R", "L", "U", "E", "E90", "G", "EU", "Z", "Q", "O", "ET", "ETR", "AR", "ES", "X"} <= codes


@pytest.mark.parametrize("code", ["R", "L", "U", "E", "E90", "G", "EU", "Z", "Q", "O", "ET", "ETR", "AR", "ES", "X"])
def test_every_template_computes_draws_and_describes_itself(code):
    cls = available_shapes()[code]
    assert cls.name and cls.description and cls.parameters()
    shape = cls.template()
    for rebar in (N3, N4, N5):
        cut = shape.cut_length(rebar)
        assert cut.total_mm > 0 and math.isfinite(cut.total_mm)
        sketch = shape.sketch(rebar)
        assert sketch.paths and all(len(path) >= 2 for path in sketch.paths)
    assert shape.sketch(None).paths  # sin barra también dibuja
    assert shape.dimensions()


def test_templates_either_compute_or_raise_geometry_error_for_large_bars():
    for cls in available_shapes().values():
        for designation in ("#6", "#8", "#10"):
            try:
                cls.template().cut_length(get_rebar(designation))
            except GeometryError:
                pass  # una plantilla de 300 mm puede ser imposible con #10: debe avisar, no fallar


# ------------------------------------------------------------------ motor de ganchos
def test_hooked_bar_with_two_90_hooks_equals_u_bar():
    ext = N4.standard_hook(HookType.DEG_90).extension_mm
    hooked = HookedBar(a=1000, hook_start=90, hook_end=90).cut_length(N4)
    u = UBar.with_standard_hooks(N4, a=1000).cut_length(N4)
    assert hooked.total_mm == pytest.approx(u.total_mm)
    assert [h.extension_mm for h in hooked.hooks] == pytest.approx([ext, ext])


@pytest.mark.parametrize(("start", "end"), [(90, 135), (135, 135), (180, 90), (180, 180), (135, 0), (0, 90)])
def test_hooked_bar_length_matches_independent_walk(start, end):
    shape = HookedBar(a=1200, hook_start=start, hook_end=end, style="stirrup" if 135 in (start, end) else "main")
    use = BendUse.STIRRUP if shape.style == "stirrup" else BendUse.MAIN
    rebar = N4
    d, r, R = rebar.diameter_mm, rebar.bend_radius_mm(use), rebar.centerline_radius_mm(use)
    cut = shape.cut_length(rebar)
    ext = {h.angle_deg: h.extension_mm for h in cut.hooks}
    items = []
    extent_start = extent_end = 0.0
    if start:
        items += [("s", ext[start]), ("t", start, R)]
        extent_start = R + d / 2 if start >= 90 else 0
    # tramo recto: cota exterior menos lo que consume cada gancho
    straight = 1200 - (r + d if start else 0) - (r + d if end else 0)
    items.append(("s", straight))
    if end:
        items += [("t", end, R), ("s", ext[end])]
    length, _, _ = walk(items)
    assert cut.total_mm == pytest.approx(length, abs=1e-6)


def test_u_stirrup_geometry_closes_on_its_outer_dimensions():
    """Con ganchos de 135° el eje encierra exactamente a − d de ancho y b − d de alto (+ d/2 de arco)."""
    rebar = N3
    shape = UStirrup(a=300, b=400, hook=135)
    d, r, R = rebar.diameter_mm, rebar.bend_radius_mm(BendUse.STIRRUP), rebar.centerline_radius_mm(BendUse.STIRRUP)
    cut = shape.cut_length(rebar)
    ext = cut.hooks[0].extension_mm
    leg = 400 - (r + d) - (r + d)  # cota exterior menos el extremo del gancho y la tangente del doblez inferior
    base = 300 - 2 * (r + d)
    # Recorrido: cola → gancho (giro a la izquierda) → pata → doblez → base → doblez → pata → gancho → cola
    items = [("s", ext), ("t", 135, R), ("s", leg), ("t", 90, R), ("s", base), ("t", 90, R), ("s", leg), ("t", 135, R), ("s", ext)]
    length, _, _ = walk(items, heading=45.0)
    assert cut.total_mm == pytest.approx(length, abs=1e-6)
    # Caja de la parte en U (sin las colas): ancho exterior = a, alto exterior = b
    u_only = [("s", leg), ("t", 90, R), ("s", base), ("t", 90, R), ("s", leg)]
    _, width, height = walk(u_only, heading=-90.0)
    assert width + d == pytest.approx(300 - 0, abs=1e-6)
    assert height + (r + d) + d / 2 == pytest.approx(400, abs=1e-6)  # + extremo exterior del gancho (r + d)


def test_standard_hook_lengths_are_reported():
    cut = LBar.with_standard_hook(N4, a=1000).cut_length(N4)
    assert len(cut.hooks) == 1 and cut.hooks[0].angle_deg == 90
    assert cut.hooks[0].extension_mm == pytest.approx(152.4)  # 12 d
    assert cut.hooks[0].standard_mm == pytest.approx(152.4)
    assert cut.hook_text == "90° · 152"
    stirrup = Stirrup135(220, 420).cut_length(N4)
    assert stirrup.hook_text == "2 × 135° · 76"
    assert Stirrup90(220, 420).cut_length(N4).hook_text == "2 × 90° · 76"


def test_hook_extension_validation():
    with pytest.raises(GeometryError, match="no hay gancho estándar de 135°"):
        HookedBar(a=1000, hook_start=135, hook_end=0).cut_length(N4)  # estilo barra: ACI no define 135°
    forced = HookedBar(a=1000, hook_start=135, hook_end=0, ext_start=120).cut_length(N4)
    assert forced.hooks[0].extension_mm == 120 and "sin extensión estándar" in forced.warnings[0]
    short = HookedBar(a=1000, hook_start=90, hook_end=0, ext_start=50).cut_length(N4)
    assert "mínimo normativo" in short.warnings[0]
    assert HookedBar(a=1000, hook_start=0, hook_end=0).cut_length(N4).total_mm == 1000


def test_rectangular_stirrup_90_formula():
    d, R = N3.diameter_mm, N3.centerline_radius_mm(BendUse.STIRRUP)
    ext = max(6 * d, 75)
    cut = Stirrup90(220, 420).cut_length(N3)
    expected = 2 * (220 - d) + 2 * (420 - d) - 8 * R + (3 * math.pi / 2 + math.pi) * R + 2 * ext
    assert cut.total_mm == pytest.approx(expected)


# ------------------------------------------------------------------ polilíneas
def test_z_bar_and_omega_are_sum_of_dimensions_minus_bend_deductions():
    assert ZBar(250, 200, 250).cut_length(N4).total_mm == pytest.approx(700 - 2 * delta90(N4))
    omega = OmegaBar(200, 300, 400, 300, 200).cut_length(N4)
    assert omega.total_mm == pytest.approx(1400 - 4 * delta90(N4))
    assert omega.hooks == ()


def test_crank_bar_uses_the_bend_deduction_of_its_angle():
    r, d = N5.bend_radius_mm(), N5.diameter_mm
    angle = 45.0
    deduction = 2 * (r + d) * math.tan(math.radians(angle) / 2) - math.radians(angle) * (r + d / 2)
    cut = CrankBar(600, 300, 600, angle).cut_length(N5)
    assert cut.total_mm == pytest.approx(1500 - 2 * deduction)
    assert any("Desnivel exterior" in note for note in cut.notes)
    with pytest.raises(GeometryError):
        CrankBar(600, 300, 600, angle=95)  # ángulo fuera de rango


def test_geometry_errors_name_the_leg():
    with pytest.raises(GeometryError, match="cota B"):
        OmegaBar(200, 60, 400, 300, 200).cut_length(N6)


# ------------------------------------------------------------------ polígonos
def test_trapezoid_with_equal_bases_is_the_rectangular_stirrup():
    trap = TrapStirrup(bottom=220, top=220, height=420, hook=135).cut_length(N3)
    rect = Stirrup135(220, 420).cut_length(N3)
    assert trap.total_mm == pytest.approx(rect.total_mm)


def test_trapezoid_and_triangle_geometry():
    trap = TrapStirrup(bottom=400, top=250, height=300)
    assert trap.leg() == pytest.approx(math.hypot(300, 75))
    assert trap.base_angle() == pytest.approx(math.degrees(math.atan2(300, 75)))
    tri = TriStirrup(300, 300, 300)
    assert tri.interior_angles() == pytest.approx((60.0, 60.0, 60.0))
    assert sum(180 - a for a in tri.interior_angles()) == pytest.approx(360.0)
    with pytest.raises(GeometryError, match="no forman un triángulo"):
        TriStirrup(100, 100, 250)


def test_equilateral_triangle_stirrup_length():
    rebar, s = N3, 300.0
    r, d, R = rebar.bend_radius_mm(BendUse.STIRRUP), rebar.diameter_mm, rebar.centerline_radius_mm(BendUse.STIRRUP)
    ext = max(6 * d, 75)
    turn = math.radians(120)
    straight = s - (r + d) * 2 * math.tan(turn / 2)
    expected = 3 * straight + 2 * turn * R + 2 * math.radians(135) * R + 2 * ext
    assert TriStirrup(s, s, s, hook=135).cut_length(rebar).total_mm == pytest.approx(expected)
    notes = TriStirrup(s, s, s).cut_length(rebar).notes[0]
    assert "60°" in notes


# ------------------------------------------------------------------ aro y espiral
def test_ring_matches_bs8666_code_75():
    """BS 8666 código 75: L = π·(A − d) + B."""
    cut = RingTie(diameter=400, lap=250).cut_length(N3)
    assert cut.total_mm == pytest.approx(math.pi * (400 - N3.diameter_mm) + 250)
    with pytest.raises(GeometryError, match="mínimo geométrico"):
        RingTie(diameter=40, lap=100).cut_length(N3)


def test_spiral_length_and_spacing_warning():
    d = N4.diameter_mm
    shape = Spiral(diameter=400, pitch=75, height=2000, extra_turns=1.5)
    n = (2000 - d) / 75
    centre = math.pi * (400 - d)
    assert shape.cut_length(N4).total_mm == pytest.approx(n * math.hypot(centre, 75) + 2 * 1.5 * centre)
    assert not shape.cut_length(N4).warnings
    assert "25–75" in Spiral(400, 30, 2000).cut_length(N4).warnings[0]
    assert "25–75" in Spiral(400, 120, 2000).cut_length(N4).warnings[0]
    with pytest.raises(GeometryError):
        Spiral(400, 10, 2000).cut_length(N4)  # paso menor que el diámetro de la barra


# ------------------------------------------------------------------ BS 8666
def test_l_bar_agrees_with_bs8666_code_11():
    """BS 8666 código 11: L = A + B − 0.5r − d. Con r = 3d coincide con la deducción exacta (2.50d)."""
    r, d = N4.bend_radius_mm(), N4.diameter_mm
    bs = 1000 + 300 - 0.5 * r - d
    assert LBar(1000, 300).cut_length(N4).total_mm == pytest.approx(bs, abs=0.01 * d)


# ------------------------------------------------------------------ forma personalizada
def test_custom_bar_matches_equivalent_template():
    custom = CustomBar(legs=(250, 200, 250), angles=(90, -90)).cut_length(N4)
    assert custom.total_mm == pytest.approx(ZBar(250, 200, 250).cut_length(N4).total_mm)
    with_hooks = CustomBar(legs=(1000,), angles=(), hook_start=90, hook_end=90).cut_length(N4)
    assert with_hooks.total_mm == pytest.approx(HookedBar(1000, 90, None, 90, None).cut_length(N4).total_mm)


def test_custom_bar_accepts_lists_and_validates():
    shape = CustomBar(legs=[300, 200, 300], angles=[60, -60])  # listas (p. ej. venidas de JSON) → tuplas
    assert shape.legs == (300.0, 200.0, 300.0) and shape.angles == (60.0, -60.0)
    hash(shape)  # sigue siendo inmutable y hashable
    with pytest.raises(GeometryError, match="ángulos de giro"):
        CustomBar(legs=(300, 200), angles=(90, 90))
    with pytest.raises(GeometryError):
        CustomBar(legs=(300, 200), angles=(0,))
    with pytest.raises(GeometryError):
        CustomBar(legs=(300, 200), angles=(180,))
    with pytest.raises(GeometryError):
        CustomBar(legs=(300, -5), angles=(90,))
    assert list(CustomBar(legs=(1, 2, 3, 4), angles=(90, 90, 90)).dimensions()) == ["A", "B", "C", "D"]


def test_create_shape_and_json_round_trip_of_new_shapes():
    assert create_shape("Q", a=500, b=250, c=500, angle=30).angle == 30
    project = Project(elements=[StructuralElement("X-1", ElementType.OTHER, "Nivel 1", 2)])
    element = project.elements[0]
    element.add_group("1", N4, CustomBar(legs=(400, 300, 200), angles=(90, -45), hook_end=90), 3)
    element.add_group("2", N3, TriStirrup(300, 280, 260, hook=90), 10)
    element.add_group("3", N4, Spiral(350, 70, 1800), 2)
    element.add_group("4", N4, HookedBar(1000, 135, 100, 90, None, 1, "stirrup"), 4)
    loaded = project_from_dict(project_to_dict(project))
    for original, copy in zip(element.groups, loaded.elements[0].groups):
        assert copy.shape == original.shape
        assert copy.cut_length_mm == pytest.approx(original.cut_length_mm)
    assert loaded.elements[0].element_type is ElementType.OTHER
    # y el cálculo del proyecto completo funciona con todas
    assert BBSCalculator().calculate(loaded.elements).total_weight_kg > 0


def test_parameters_are_described_for_forms():
    for cls in available_shapes().values():
        names = [spec.name for spec in cls.parameters()]
        assert len(names) == len(set(names))
        for spec in cls.parameters():
            assert spec.label
            if spec.kind == "choice":
                assert spec.choices
    custom = {spec.name: spec for spec in CustomBar.parameters()}
    assert custom["legs"].kind == "lengths" and custom["angles"].hidden
