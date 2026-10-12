import json

import pytest

from core.project import Project
from core.rebar import GRADE_40, get_rebar
from core.serialization import load_project, project_from_dict, project_to_dict, save_project
from core.shape_codes import Stirrup
from engine.bbs_calculator import BBSCalculator
from sample_project import build_project


def totals(project):
    result = BBSCalculator(project.stock_length_mm, project.length_rounding_mm).calculate(project.elements)
    return result.total_weight_kg, [line.cut_length_mm for line in result.lines]


def test_round_trip_preserves_everything(tmp_path):
    project = build_project()
    project.paper = "a4"
    path = save_project(project, tmp_path / "obra.rebarflow")
    loaded = load_project(path)
    assert loaded.name == project.name and loaded.paper == "a4"
    assert [e.name for e in loaded.elements] == [e.name for e in project.elements]
    assert totals(loaded) == totals(project)
    assert loaded.elements[2].groups[3].shape == project.elements[2].groups[3].shape  # estribo


def test_optional_dimension_and_grade_survive(tmp_path):
    project = build_project()
    project.elements[2].groups.append(
        type(project.elements[2].groups[0])("E9", get_rebar("#3", GRADE_40), Stirrup(220, 420, ext_start=90, ext_end=90), 3)
    )
    loaded = load_project(save_project(project, tmp_path / "p.rebarflow"))
    group = loaded.elements[2].groups[-1]
    assert group.shape.ext_start == 90 and group.shape.ext_end == 90 and group.rebar.grade == GRADE_40


def test_file_is_plain_json_with_inputs_only(tmp_path):
    data = json.loads(save_project(build_project(), tmp_path / "p.rebarflow").read_text(encoding="utf-8"))
    assert data["format"] == "rebarflow-project" and data["version"] == 1
    group = data["elements"][0]["groups"][0]
    assert group["bar"] == "#5" and group["shape"]["code"] == "U"
    assert "cut_length" not in json.dumps(data)  # lo calculado no se guarda


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("elements"),
    lambda d: d.update(format="otra-cosa"),
    lambda d: d.update(version=99),
    lambda d: d["elements"][0]["groups"][0]["shape"].update(code="NO-EXISTE"),
    lambda d: d["elements"][0]["groups"][0].update(bar="#99"),
    lambda d: d["elements"][0]["groups"][0]["shape"]["dimensions"].update(a=-5),
])
def test_invalid_files_raise_value_error(mutate):
    data = project_to_dict(build_project())
    mutate(data)
    with pytest.raises((ValueError, KeyError)):
        project_from_dict(data)


def test_not_json(tmp_path):
    bad = tmp_path / "bad.rebarflow"
    bad.write_text("{ no es json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_project(bad)


def test_project_validation_and_levels():
    with pytest.raises(ValueError):
        Project(stock_length_mm=0)
    with pytest.raises(ValueError):
        Project(paper="legal")
    assert build_project().levels == ["Cimentación", "Nivel 1", "Nivel 2"]


def test_project_saved_with_the_old_stirrup_codes_still_opens():
    """Archivos de versiones anteriores: el estribo E90 y los parámetros de un solo gancho."""
    data = project_to_dict(build_project())
    groups = data["elements"][2]["groups"]
    stirrup = next(g for g in groups if g["shape"]["code"] == "E")
    stirrup["shape"] = {"code": "E90", "dimensions": {"a": 220.0, "b": 420.0, "hook_extension_mm": 90.0}}
    loaded = project_from_dict(data)
    shape = next(g for g in loaded.elements[2].groups if g.mark == stirrup["mark"]).shape
    assert (shape.code, shape.hook_start, shape.hook_end, shape.ext_start, shape.ext_end) == ("E", 90, 90, 90, 90)


def test_stirrup_with_different_legs_and_ring_and_spiral_hooks_round_trip(tmp_path):
    from core.element import ElementType, StructuralElement
    from core.project import Project
    from core.shape_codes import Stirrup
    from core.shape_templates import RingTie, Spiral

    element = StructuralElement("X-1", ElementType.OTHER, "Nivel 1", 1)
    n3 = get_rebar("#3")
    element.add_group("E1", n3, Stirrup(220, 420, hook_start=135, hook_end=90, ext_end=120), 5)
    element.add_group("AR", n3, RingTie(400, lap=0, hook_start=135, hook_end=135), 5)
    element.add_group("ES", n3, Spiral(400, 75, 2000, turns_start=2.0, turns_end=1.0, hook_start=90, ext_start=100), 1)
    loaded = load_project(save_project(Project(elements=[element]), tmp_path / "p.rebarflow"))
    for original, copy in zip(element.groups, loaded.elements[0].groups):
        assert copy.shape == original.shape
        assert copy.cut_length_mm == original.cut_length_mm


def test_couplers_round_trip_and_old_files_without_them_open(tmp_path):
    from core.element import ElementType, StructuralElement
    from core.shape_codes import StraightBar
    from core.shape_templates import ZBar

    element = StructuralElement("C-1", ElementType.COLUMN, "Nivel 1", 2)
    n5 = get_rebar("#5")
    element.add_group("A", n5, StraightBar(3000, coupler_start="short", coupler_end="long"), 4)
    element.add_group("B", n5, ZBar(coupler_end="short"), 2)
    loaded = load_project(save_project(Project(elements=[element]), tmp_path / "p.rebarflow"))
    for original, copy in zip(element.groups, loaded.elements[0].groups):
        assert copy.shape == original.shape and copy.cut.couplers == original.cut.couplers
    data = project_to_dict(Project(elements=[element]))
    for group in data["elements"][0]["groups"]:  # un archivo anterior a los couplers no tiene esos campos
        for key in ("coupler_start", "coupler_end"):
            group["shape"]["dimensions"].pop(key, None)
    old = project_from_dict(data)
    assert all(g.cut.couplers == () for g in old.elements[0].groups)
