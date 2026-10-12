import pytest

from core.element import ElementType, RebarGroup, StructuralElement
from core.geometry import GeometryError
from core.rebar import get_rebar
from core.shape_codes import LBar, StraightBar


def test_group_computes_cut_length_on_creation():
    group = RebarGroup("A1", get_rebar("#4"), LBar(1000, 300), 4)
    assert group.cut_length_mm == pytest.approx(1268.22, abs=0.01)


def test_group_validates_geometry_against_rebar():
    with pytest.raises(GeometryError):
        RebarGroup("A1", get_rebar("#8"), LBar(50, 300), 1)


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True])
def test_group_quantity_must_be_positive_int(quantity):
    with pytest.raises(ValueError, match="cantidad"):
        RebarGroup("A1", get_rebar("#4"), StraightBar(1000), quantity)


def test_group_requires_mark():
    with pytest.raises(ValueError, match="marca"):
        RebarGroup(" ", get_rebar("#4"), StraightBar(1000), 1)


def test_element_add_group_and_unique_marks():
    beam = StructuralElement("V-101", ElementType.BEAM, "Nivel 1", quantity=2)
    beam.add_group("A1", get_rebar("#4"), StraightBar(1000), 3)
    assert len(beam.groups) == 1
    with pytest.raises(ValueError, match="ya existe"):
        beam.add_group("A1", get_rebar("#5"), StraightBar(2000), 1)


@pytest.mark.parametrize("quantity", [0, -3])
def test_element_quantity_validation(quantity):
    with pytest.raises(ValueError, match="cantidad"):
        StructuralElement("C-1", ElementType.COLUMN, "Nivel 1", quantity)


def test_element_type_labels():
    assert ElementType.BEAM.value == "Viga"
    assert ElementType.COLUMN.value == "Columna"
    assert ElementType.FOOTING.value == "Zapata"
