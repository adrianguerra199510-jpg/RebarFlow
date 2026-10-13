import re
import shutil
import subprocess

import pytest

from core.element import ElementType, StructuralElement
from core.rebar import get_rebar
from core.shape_codes import LBar, Stirrup, StraightBar, UBar
from engine.bbs_calculator import BBSCalculator
from exporters.pdf_exporter import PdfExporter


def pages(path) -> int:
    return len(re.findall(rb"/Type /Page\b(?!s)", path.read_bytes()))


@pytest.fixture
def result():
    n3, n5 = get_rebar("#3"), get_rebar("#5")
    beam = StructuralElement("V-101", ElementType.BEAM, "Nivel 1", 4)
    beam.add_group("A1", n5, StraightBar(5600), 3)
    beam.add_group("A2", n5, UBar.with_standard_hooks(n5, 5500), 2)
    beam.add_group("A3", n5, LBar(1500, 350), 4)
    beam.add_group("E1", n3, Stirrup(220, 420), 38)
    beam.add_group("E2", n3, Stirrup(220, 420, ext_start=50, ext_end=50), 2)  # aviso de gancho corto
    return BBSCalculator().calculate([beam])


def test_pdf_is_written(result, tmp_path):
    path = PdfExporter(project_name="Proyecto X").export(result, tmp_path / "sub" / "bbs.pdf")
    data = path.read_bytes()
    assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF")
    assert pages(path) >= 2  # planilla + resumen


@pytest.mark.parametrize("page_size", ["letter", "a4"])
def test_page_sizes_and_no_images(result, tmp_path, page_size):
    with_images = PdfExporter(page_size=page_size).export(result, tmp_path / "a.pdf")
    plain = PdfExporter(page_size=page_size, include_shape_images=False).export(result, tmp_path / "b.pdf")
    assert plain.stat().st_size < with_images.stat().st_size


def test_invalid_page_size(result, tmp_path):
    with pytest.raises(ValueError, match="papel"):
        PdfExporter(page_size="legal").export(result, tmp_path / "x.pdf")


def test_many_elements_paginate_and_empty_result_exports(tmp_path):
    n3 = get_rebar("#3")
    elements = []
    for i in range(40):
        el = StructuralElement(f"C-{i}", ElementType.COLUMN, "Nivel 1", 2)
        el.add_group("E1", n3, Stirrup(320, 320), 20)
        elements.append(el)
    big = PdfExporter().export(BBSCalculator().calculate(elements), tmp_path / "big.pdf")
    assert pages(big) > 3
    empty = PdfExporter().export(BBSCalculator().calculate([]), tmp_path / "empty.pdf")
    assert empty.read_bytes().startswith(b"%PDF")


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="requiere pdftotext (poppler)")
def test_pdf_text_has_no_removed_columns_and_lists_warnings_and_couplers(result, tmp_path):
    from core.shape_codes import StraightBar

    element = StructuralElement("C-1", ElementType.COLUMN, "Nivel 2", 2)
    element.add_group("C1", get_rebar("#5"), StraightBar(3000, coupler_start="short", coupler_end="long"), 4)
    elements = [result.element_schedules[0].element, element]
    path = PdfExporter().export(BBSCalculator().calculate(elements), tmp_path / "t.pdf")
    text = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout
    header = next(line for line in text.splitlines() if "Marca" in line and "Barra" in line)
    for removed in ("Forma", "Ganchos", "Observaciones", "Ø"):
        assert removed not in header
    assert "Avisos" in text and "V-101 · marca E2" in text and "mínimo normativo" in text
    assert "RC = rosca corta, RL = rosca larga" in text
    assert "Acopladores y roscas por barra" in text and "Roscas largas" in text and "Roscas cortas" in text
