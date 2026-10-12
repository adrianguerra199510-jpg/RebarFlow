"""Genera las capturas de la interfaz y de las planillas exportadas que ilustran el README.

Uso::

    python tools/capture_screenshots.py [carpeta_de_salida]     # por defecto: docs/

Requiere PySide6 y, para las imágenes de Excel/PDF, LibreOffice (``soffice``) y ``pdftoppm``/``pdfinfo``.
La interfaz se dibuja sin pantalla (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gui.app import create_application  # noqa: E402
from gui.dialogs import BarDialog  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from sample_project import build_catalog_project, build_project  # noqa: E402


def select_element(window: MainWindow, app, name: str, level: str) -> None:
    root = window.tree.topLevelItem(0)
    for i in range(root.childCount()):
        if root.child(i).text(0) == level:
            for j in range(root.child(i).childCount()):
                if root.child(i).child(j).text(0).startswith(name):
                    window.tree.setCurrentItem(root.child(i).child(j))
                    app.processEvents()


def capture_interface(out: Path) -> None:
    app = create_application([])
    window = MainWindow(build_project())
    window.resize(1560, 920)
    window.show()
    app.processEvents()

    select_element(window, app, "V-101", "Nivel 1")
    window.bars_table.selectRow(1)
    app.processEvents()
    window.grab().save(str(out / "ui_barras.png"))

    window.tabs.setCurrentIndex(1)
    window.project_table.selectRow(11)
    app.processEvents()
    window.grab().save(str(out / "ui_planilla.png"))

    window.tabs.setCurrentIndex(2)
    app.processEvents()
    window.grab().save(str(out / "ui_resumen.png"))

    window.tabs.setCurrentIndex(3)
    app.processEvents()
    window.grab().save(str(out / "ui_plan_corte.png"))

    element = window.current_element()
    dialog = BarDialog(window, group=element.groups[3], used_marks=["A1", "A2", "A3"])
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(out / "ui_dialogo_barra.png"))

    error = BarDialog(window, suggested_mark="B1")
    error.shape.setCurrentIndex(error.shape.findText("L · Bastón L"))
    error.bar.setCurrentIndex(error.bar.findData("#8"))
    error._widgets["a"].setValue(60)
    error.show()
    app.processEvents()
    error.grab().save(str(out / "ui_dialogo_error.png"))

    custom = BarDialog(window, suggested_mark="X1")
    custom.bar.setCurrentIndex(custom.bar.findData("#4"))
    custom.shape.setCurrentIndex(custom.shape.findText("X · Personalizada"))
    custom._editor.set_values((300.0, 200.0, 300.0, 250.0), (90.0, -90.0, 60.0))
    custom._widgets["hook_end"].setCurrentIndex(custom._widgets["hook_end"].findData(90))
    custom.show()
    app.processEvents()
    custom.grab().save(str(out / "ui_dialogo_personalizada.png"))

    stirrup = BarDialog(window, suggested_mark="E3")
    stirrup.bar.setCurrentIndex(stirrup.bar.findData("#3"))
    stirrup.shape.setCurrentIndex(stirrup.shape.findText("E · Estribo rectangular"))
    stirrup._widgets["hook_end"].setCurrentIndex(stirrup._widgets["hook_end"].findData(90))
    stirrup._widgets["ext_end"].setValue(120)
    stirrup.show()
    app.processEvents()
    stirrup.grab().save(str(out / "ui_dialogo_estribo.png"))

    ring = BarDialog(window, suggested_mark="AR2")
    ring.bar.setCurrentIndex(ring.bar.findData("#3"))
    ring.shape.setCurrentIndex(ring.shape.findText("AR · Aro circular"))
    ring._widgets["lap"].setValue(0)
    for name in ("hook_start", "hook_end"):
        ring._widgets[name].setCurrentIndex(ring._widgets[name].findData(135))
    ring.show()
    app.processEvents()
    ring.grab().save(str(out / "ui_dialogo_aro.png"))

    spiral = BarDialog(window, suggested_mark="ES2")
    spiral.bar.setCurrentIndex(spiral.bar.findData("#3"))
    spiral.shape.setCurrentIndex(spiral.shape.findText("ES · Espiral"))
    spiral._widgets["turns_start"].setValue(2.0)
    spiral._widgets["turns_end"].setValue(1.0)
    for name, angle in (("hook_start", 135), ("hook_end", 90)):
        spiral._widgets[name].setCurrentIndex(spiral._widgets[name].findData(angle))
    spiral.show()
    app.processEvents()
    spiral.grab().save(str(out / "ui_dialogo_espiral.png"))

    coupler = BarDialog(window, suggested_mark="R3")
    coupler.bar.setCurrentIndex(coupler.bar.findData("#8"))
    coupler.shape.setCurrentIndex(coupler.shape.findText("R · Recta"))
    coupler._widgets["length"].setValue(3000)
    coupler._widgets["coupler_start"].setCurrentIndex(coupler._widgets["coupler_start"].findData("short"))
    coupler._widgets["coupler_end"].setCurrentIndex(coupler._widgets["coupler_end"].findData("long"))
    coupler.show()
    app.processEvents()
    coupler.grab().save(str(out / "ui_dialogo_coupler.png"))

    templates = BarDialog(window, suggested_mark="G1")
    templates.show()
    templates.shape.showPopup()
    app.processEvents()
    popup = templates.shape.view().window()
    popup.grab().save(str(out / "ui_plantillas.png"))
    templates.shape.hidePopup()

    window.open_catalog()
    window.tabs.setCurrentIndex(0)
    window.resize(1700, 1240)
    app.processEvents()
    window.bars_table.selectRow(window.bars_table.row_of("ET1"))  # un estribo triangular
    app.processEvents()
    window.grab().save(str(out / "ui_catalogo.png"))


def _pages(pdf: Path) -> int:
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"Pages:\s+(\d+)", info).group(1))


def _png(pdf: Path, page: int, target: Path, resolution: int = 110) -> None:
    # con ``-singlefile`` pdftoppm añade ".png" al prefijo que se le da
    subprocess.run(["pdftoppm", "-r", str(resolution), "-f", str(page), "-l", str(page), "-png", "-singlefile",
                    str(pdf), str(target.with_suffix(""))], check=True)


def capture_exports(out: Path) -> None:
    from engine.bbs_calculator import BBSCalculator
    from exporters.excel_exporter import ExcelExporter
    from exporters.pdf_exporter import PdfExporter

    for project, prefix in ((build_project(), "export"), (build_catalog_project(), "export_catalogo")):
        result = BBSCalculator(project.stock_length_mm, project.length_rounding_mm, project.reusable_remnant_mm).calculate(project.elements)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            xlsx = ExcelExporter(project.name, project.author).export(result, tmp_dir / "planilla.xlsx")
            pdf = PdfExporter(project.name, project.author, page_size=project.paper).export(result, tmp_dir / "planilla_pdf.pdf")
            if shutil.which("soffice") and shutil.which("pdftoppm") and prefix == "export":
                subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp_dir), str(xlsx)],
                               check=True, capture_output=True, timeout=180)
                excel_pdf = tmp_dir / "planilla.pdf"
                _png(excel_pdf, 1, out / "export_excel.png")
                _png(excel_pdf, _pages(excel_pdf), out / "export_excel_plan.png")
            if shutil.which("pdftoppm"):
                _png(pdf, 1, out / f"{prefix}_pdf.png")
                if prefix == "export":
                    _png(pdf, _pages(pdf), out / "export_pdf_plan.png")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "docs"
    target.mkdir(parents=True, exist_ok=True)
    capture_interface(target)
    capture_exports(target)
    print(f"Capturas escritas en {target}")
