import json

import pytest

from core.project import Project
from core.rebar import GRADE_40, get_rebar
from core.serialization import load_project, project_from_dict, project_to_dict, save_project
from core.shape_codes import Stirrup135
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
        type(project.elements[2].groups[0])("E9", get_rebar("#3", GRADE_40), Stirrup135(220, 420, 90), 3)
    )
    loaded = load_project(save_project(project, tmp_path / "p.rebarflow"))
    group = loaded.elements[2].groups[-1]
    assert group.shape.hook_extension_mm == 90 and group.rebar.grade == GRADE_40


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
