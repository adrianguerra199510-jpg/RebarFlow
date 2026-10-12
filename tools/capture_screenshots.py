"""Genera las capturas de la interfaz y de las planillas exportadas que ilustran el README.

Uso::

    python tools/capture_screenshots.py [carpeta_de_salida]     # por defecto: docs/

Requiere PySide6 y, para las imágenes de Excel/PDF, LibreOffice (``soffice``) y ``pdftoppm``.
La interfaz se dibuja sin pantalla (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
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
from sample_project import build_project  # noqa: E402


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

    element = window.current_element()
    dialog = BarDialog(window, group=element.groups[3], used_marks=["A1", "A2", "A3"])
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(out / "ui_dialogo_barra.png"))

    error = BarDialog(window, suggested_mark="B1")
    error.shape.setCurrentIndex(error.shape.findText("L · Bastón L"))
    error.bar.setCurrentIndex(error.bar.findData("#8"))
    error._spins["a"].setValue(60)
    error.show()
    app.processEvents()
    error.grab().save(str(out / "ui_dialogo_error.png"))


def capture_exports(out: Path) -> None:
    from engine.bbs_calculator import BBSCalculator
    from exporters.excel_exporter import ExcelExporter
    from exporters.pdf_exporter import PdfExporter

    project = build_project()
    result = BBSCalculator(project.stock_length_mm, project.length_rounding_mm).calculate(project.elements)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        xlsx = ExcelExporter(project.name, project.author).export(result, tmp_dir / "planilla.xlsx")
        pdf = PdfExporter(project.name, project.author, page_size=project.paper).export(result, tmp_dir / "planilla_pdf.pdf")
        if shutil.which("soffice"):
            subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp_dir), str(xlsx)],
                           check=True, capture_output=True, timeout=180)
        if shutil.which("pdftoppm"):
            for source, name in ((tmp_dir / "planilla.pdf", "export_excel"), (pdf, "export_pdf")):
                if source.exists():
                    subprocess.run(["pdftoppm", "-r", "110", "-f", "1", "-l", "1", "-png", "-singlefile",
                                    str(source), str(out / name)], check=True)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "docs"
    target.mkdir(parents=True, exist_ok=True)
    capture_interface(target)
    capture_exports(target)
    print(f"Capturas escritas en {target}")
