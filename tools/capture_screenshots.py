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
from sample_project import build_bridge_project, build_catalog_project, build_project  # noqa: E402


def select_element(window: MainWindow, app, name: str, level: str) -> None:
    root = window.tree.topLevelItem(0)
    for i in range(root.childCount()):
        if root.child(i).text(0) == level:
            for j in range(root.child(i).childCount()):
                if root.child(i).child(j).text(0).startswith(name):
                    window.tree.setCurrentItem(root.child(i).child(j))
                    app.processEvents()


def capture_interface(out: Path) -> None:
    app = create_application([], dark=False)
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

    # Espiral armada con barras individuales: traslape o coupler cuando excede la barra comercial
    lapped = BarDialog(window, suggested_mark="ES3")
    lapped.bar.setCurrentIndex(lapped.bar.findData("#3"))
    lapped.shape.setCurrentIndex(lapped.shape.findText("ES · Espiral"))
    lapped._widgets["supply_mode"].setCurrentIndex(lapped._widgets["supply_mode"].findData("bars"))
    lapped.show()
    app.processEvents()
    lapped.grab().save(str(out / "ui_dialogo_espiral_traslape.png"))
    coupled = BarDialog(window, suggested_mark="ES4")
    coupled.bar.setCurrentIndex(coupled.bar.findData("#3"))
    coupled.shape.setCurrentIndex(coupled.shape.findText("ES · Espiral"))
    coupled._widgets["supply_mode"].setCurrentIndex(coupled._widgets["supply_mode"].findData("bars"))
    coupled._widgets["joint"].setCurrentIndex(coupled._widgets["joint"].findData("coupler"))
    coupled._widgets["joint_threads"].setCurrentIndex(coupled._widgets["joint_threads"].findData("long_short"))
    coupled.show()
    app.processEvents()
    coupled.grab().save(str(out / "ui_dialogo_espiral_coupler.png"))

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

    # Marca dividida en sub-marcas (ES4 → ES4.1, ES4.2, ES4.3), cada una con las roscas de sus extremos
    row = window.bars_table.row_of("ES4")
    window.bars_table.scrollToItem(window.bars_table.item(row, 0), window.bars_table.ScrollHint.PositionAtTop)
    window.bars_table.selectRow(row + 2)
    app.processEvents()
    window.grab().save(str(out / "ui_subbarras.png"))

    # Obra sin niveles: el paso inferior de ejemplo, agrupado por estructura y subestructura
    window.open_bridge()
    window.resize(1700, 1000)
    window.tabs.setCurrentIndex(0)
    app.processEvents()
    window.bars_table.selectRow(2)
    app.processEvents()
    window.grab().save(str(out / "ui_puente.png"))

    # Varios proyectos abiertos: la cinta de proyectos (un clic en una pestaña cambia de proyecto)
    window.duplicate_project()
    window.refresh()
    app.processEvents()
    window.grab().save(str(out / "ui_proyectos.png"))
    window.session.modified = False
    window.close_project()
    window.select_project(1)  # vuelve al catálogo
    app.processEvents()

    # Propiedades del proyecto: datos del encabezado, logo y nombre del primer grupo
    from gui.dialogs import ProjectDialog

    bridge = build_bridge_project()
    bridge.logo_png = demo_logo()
    props = ProjectDialog(window, bridge)
    props.show()
    app.processEvents()
    props.grab().save(str(out / "ui_dialogo_proyecto.png"))

    # Modo nocturno (sin guardar la preferencia): ventana con el catálogo y diálogo de la espiral
    window.set_dark_mode(True, remember=False)
    window.bars_table.selectRow(window.bars_table.row_of("E3"))
    app.processEvents()
    window.grab().save(str(out / "ui_nocturno.png"))
    window.tabs.setCurrentIndex(2)
    app.processEvents()
    window.grab().save(str(out / "ui_nocturno_resumen.png"))
    night = BarDialog(window, suggested_mark="ES2")
    night.bar.setCurrentIndex(night.bar.findData("#3"))
    night.shape.setCurrentIndex(night.shape.findText("ES · Espiral"))
    night._widgets["hook_start"].setCurrentIndex(night._widgets["hook_start"].findData(135))
    night.show()
    app.processEvents()
    night.grab().save(str(out / "ui_dialogo_nocturno.png"))
    window.set_dark_mode(False, remember=False)


_ICON_LABELS = {
    "new_project": "Nuevo proyecto", "open_project": "Abrir proyecto", "save_project": "Guardar proyecto",
    "edit_project": "Modificar proyecto", "duplicate_project": "Duplicar proyecto", "new_element": "Nuevo elemento",
    "new_bar": "Nueva barra", "edit_bar": "Editar barra", "delete_bar": "Eliminar barra",
    "export_excel": "Exportar a Excel", "export_pdf": "Exportar a PDF", "detail": "Detalle de barra",
    "save_as": "Guardar como", "save_all": "Guardar todos", "close_project": "Cerrar proyecto",
    "edit_element": "Editar elemento", "delete_element": "Eliminar elemento", "sample": "Abrir ejemplo",
    "catalog": "Catálogo", "bridge": "Puente", "next_project": "Siguiente", "previous_project": "Anterior",
    "project": "Árbol: proyecto", "group": "Árbol: grupo", "element": "Árbol: elemento",
}


def capture_icons(out: Path) -> None:
    """Hoja con todos los iconos de la interfaz, en el tema claro y en el nocturno (``docs/iconos.png``)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

    from gui import icons

    create_application([], dark=False)
    names = list(_ICON_LABELS)
    columns, cell_w, cell_h, size = 5, 168, 108, 64
    rows = -(-len(names) // columns)
    sheet = QPixmap(columns * cell_w * 2, rows * cell_h)
    painter = QPainter(sheet)
    font = QFont()
    font.setPixelSize(12)
    painter.setFont(font)
    for half, dark in enumerate((False, True)):
        painter.fillRect(half * columns * cell_w, 0, columns * cell_w, rows * cell_h, QColor("#141922" if dark else "#F4F6FA"))
        painter.setPen(QColor("#E4E8F0" if dark else "#1F2937"))
        for index, name in enumerate(names):
            x = half * columns * cell_w + (index % columns) * cell_w
            y = (index // columns) * cell_h
            painter.drawPixmap(x + (cell_w - size) // 2, y + 8, icons.render(name, size, dark=dark))
            painter.drawText(x, y + size + 12, cell_w, 20, Qt.AlignmentFlag.AlignHCenter, _ICON_LABELS[name])
    painter.end()
    sheet.save(str(out / "iconos.png"))


def _pages(pdf: Path) -> int:
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"Pages:\s+(\d+)", info).group(1))


def _png(pdf: Path, page: int, target: Path, resolution: int = 110) -> None:
    # con ``-singlefile`` pdftoppm añade ".png" al prefijo que se le da
    subprocess.run(["pdftoppm", "-r", str(resolution), "-f", str(page), "-l", str(page), "-png", "-singlefile",
                    str(pdf), str(target.with_suffix(""))], check=True)


def demo_logo() -> bytes:
    """Logo de muestra para las capturas: el icono de la aplicación (no se usa ninguna marca ajena)."""
    from io import BytesIO

    from exporters.logo import normalize_logo
    from gui.icon import app_icon_image

    buffer = BytesIO()
    app_icon_image(256).save(buffer, format="PNG")
    return normalize_logo(buffer.getvalue())


def capture_exports(out: Path) -> None:
    from engine.bbs_calculator import BBSCalculator
    from exporters.excel_exporter import ExcelExporter
    from exporters.pdf_exporter import PdfExporter

    bridge = build_bridge_project()
    bridge.logo_png = demo_logo()
    for project, prefix in ((build_project(), "export"), (build_catalog_project(), "export_catalogo"),
                            (bridge, "export_puente")):
        result = BBSCalculator(project.stock_length_mm, project.length_rounding_mm, project.reusable_remnant_mm,
                               project.group_label).calculate(project.elements)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            xlsx = ExcelExporter(project.name, project.author, info=project.header_fields(),
                                 logo_png=project.logo_png).export(result, tmp_dir / "planilla.xlsx")
            pdf = PdfExporter(project.name, project.author, page_size=project.paper, info=project.header_fields(),
                              logo_png=project.logo_png).export(result, tmp_dir / "planilla_pdf.pdf")
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
    capture_icons(target)
    capture_exports(target)
    print(f"Capturas escritas en {target}")
