from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

from core.element import ElementType  # noqa: E402
from core.rebar import get_rebar  # noqa: E402
from core.shape_codes import Stirrup135  # noqa: E402
from gui.app import create_application  # noqa: E402
from gui.dialogs import BarDialog, ElementDialog, ProjectDialog  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from sample_project import build_project  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return create_application([])


@pytest.fixture
def window(qapp):
    win = MainWindow(build_project())
    yield win
    win.modified = False  # evita el diálogo de cambios sin guardar al cerrar
    win.close()


def ok_enabled(dialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def select_element(window, name, level):
    root = window.tree.topLevelItem(0)
    for i in range(root.childCount()):
        if root.child(i).text(0) != level:
            continue
        for j in range(root.child(i).childCount()):
            item = root.child(i).child(j)
            if item.text(0).startswith(name):
                window.tree.setCurrentItem(item)
                return window.current_element()
    raise AssertionError(f"{name} / {level} no está en el árbol")


# ------------------------------------------------------------------ ventana principal
def test_window_loads_project_tree_and_tables(window):
    root = window.tree.topLevelItem(0)
    assert root.text(0) == "Edificio de ejemplo"
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["Cimentación", "Nivel 1", "Nivel 2"]
    assert window.current_element().name == "Z-1"
    assert window.bars_table.rowCount() == 3  # 2 marcas + subtotal
    assert window.project_table.rowCount() == 25  # 5 elementos (título + marcas + subtotal) + total general
    assert "Edificio de ejemplo" in window.windowTitle() and not window.windowTitle().startswith("*")
    assert "2,625.2 kg" in window.totals_label.text()
    assert window.act_excel.isEnabled() and window.act_pdf.isEnabled()


def test_every_bar_row_has_a_shape_image(window):
    for row in range(window.project_table.rowCount()):
        if window.project_table.line_for_row(row) is not None:
            icon = window.project_table.item(row, 3).icon()  # columna "Esquema"
            assert not icon.isNull() and not icon.pixmap(160, 60).isNull()


def test_selecting_a_bar_fills_the_detail_panel(window):
    select_element(window, "V-101", "Nivel 1")
    window.bars_table.selectRow(1)
    assert window.current_line().mark == "A2"
    assert "A2" in window.detail.title.text()
    assert "Gancho U" in window.detail.details.text()
    assert not window.detail.preview.pixmap().isNull()
    assert window.act_edit_bar.isEnabled() and window.act_delete_bar.isEnabled()


def test_add_element_and_bars_updates_totals_and_marks_modified(window):
    before = window.result.total_weight_kg
    element = window.add_element_values("C-9", ElementType.COLUMN, "Nivel 3", 2)
    assert window.current_element() is element and window.modified
    assert window.windowTitle().startswith("*")
    assert window.bars_table.rowCount() == 1  # solo el subtotal

    dialog = BarDialog(window, suggested_mark="E1", used_marks=[])
    dialog.shape.setCurrentIndex(dialog.shape.findText("E · Estribo 135°"))
    dialog._spins["a"].setValue(320)
    dialog._spins["b"].setValue(320)
    dialog.quantity.setValue(10)
    dialog.bar.setCurrentIndex(dialog.bar.findData("#3"))
    assert ok_enabled(dialog)
    window.add_group(element, dialog.result_group())
    assert window.result.total_weight_kg == pytest.approx(before + 2 * 10 * 1.43 * 0.560)
    assert window.current_line().mark == "E1"  # la barra nueva queda seleccionada


def test_duplicate_element_is_rejected(window):
    with pytest.raises(ValueError, match="Ya existe"):
        window.add_element_values("V-101", ElementType.BEAM, "Nivel 1", 1)
    window.add_element_values("V-101", ElementType.BEAM, "Nivel 3", 1)  # otro nivel: válido


def test_edit_and_delete_bar_and_element(window):
    element = select_element(window, "V-101", "Nivel 1")
    old = element.groups[0]
    dialog = BarDialog(window, group=old, used_marks=[g.mark for g in element.groups if g is not old])
    dialog.quantity.setValue(5)
    window.replace_group(element, old, dialog.result_group())
    assert element.groups[0].quantity == 5 and window.current_line().mark == "A1"

    window.delete_group(element, element.groups[0])
    assert [g.mark for g in element.groups] == ["A2", "A3", "E1"]

    n = len(window.project.elements)
    window.delete_element_object(element)
    assert len(window.project.elements) == n - 1
    assert window.current_element() is not None  # se selecciona otro elemento


def test_update_element_values(window):
    element = select_element(window, "V-101", "Nivel 1")
    window.update_element_values(element, "V-102", ElementType.BEAM, "Nivel 1", 6)
    assert element.name == "V-102" and element.quantity == 6
    with pytest.raises(ValueError):
        window.update_element_values(element, "C-1", ElementType.BEAM, "Nivel 1", 1)


def test_calculation_error_is_shown_not_raised(window):
    window.project.stock_length_mm = 3000  # las barras de 5.6 m ya no caben
    window.refresh()
    assert window.result is None and "excede la barra comercial" in window.error
    assert not window.banner.isHidden() and "No se puede calcular" in window.banner.text()
    assert not window.act_excel.isEnabled() and not window.act_pdf.isEnabled()
    with pytest.raises(ValueError):
        window.write_pdf(Path("x.pdf"))
    window.project.stock_length_mm = 12000
    window.refresh()
    assert window.result is not None and window.banner.isHidden()


def test_save_open_and_export(window, tmp_path, qapp):
    window.add_element_values("C-9", ElementType.COLUMN, "Nivel 3", 2)
    assert window.modified
    path = tmp_path / "obra.rebarflow"
    window.write_project(path)
    assert not window.modified and window.path == path

    other = MainWindow()
    assert other.open_path(path)
    assert [e.name for e in other.project.elements] == [e.name for e in window.project.elements]
    assert other.result.total_weight_kg == pytest.approx(window.result.total_weight_kg)
    other.close()

    assert window.write_excel(tmp_path / "planilla.xlsx").stat().st_size > 5000
    assert window.write_pdf(tmp_path / "planilla.pdf").read_bytes().startswith(b"%PDF")


def test_open_invalid_file_reports_failure(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))
    bad = tmp_path / "mal.rebarflow"
    bad.write_text("{}", encoding="utf-8")
    assert window.open_path(bad) is False
    assert shown and "mal.rebarflow" in shown[0]


def test_empty_project_window(qapp):
    win = MainWindow()
    assert win.current_element() is None
    assert not win.act_excel.isEnabled() and not win.act_add_bar.isEnabled()
    assert win.totals_label.text() == "Sin barras"
    win.close()


# ------------------------------------------------------------------ diálogos
def test_bar_dialog_rejects_impossible_geometry_and_recovers(qapp):
    dialog = BarDialog(None, suggested_mark="B1")
    dialog.shape.setCurrentIndex(dialog.shape.findText("L · Bastón L"))
    dialog.bar.setCurrentIndex(dialog.bar.findData("#8"))
    dialog._spins["a"].setValue(60)
    assert not ok_enabled(dialog) and "mínimo geométrico" in dialog.info.text()
    with pytest.raises(ValueError):
        dialog.result_group()
    dialog._spins["a"].setValue(1000)
    assert ok_enabled(dialog) and "Longitud de corte" in dialog.info.text()
    assert dialog.result_group().shape.a == 1000


def test_bar_dialog_mark_and_stock_validation(qapp):
    dialog = BarDialog(None, suggested_mark="A1", used_marks=["A1"])
    assert not ok_enabled(dialog) and "ya existe" in dialog.info.text()
    dialog.mark.setText("A2")
    assert ok_enabled(dialog)
    dialog.mark.setText("  ")
    assert not ok_enabled(dialog)
    dialog.mark.setText("A2")
    dialog.shape.setCurrentIndex(dialog.shape.findText("R · Recta"))
    dialog._spins["length"].setValue(13000)
    assert not ok_enabled(dialog) and "excede la barra comercial" in dialog.info.text()


def test_bar_dialog_builds_fields_from_shape_and_keeps_values(qapp):
    dialog = BarDialog(None)
    dialog.shape.setCurrentIndex(dialog.shape.findText("U · Gancho U"))
    assert list(dialog._spins) == ["a", "b", "c"]
    dialog._spins["a"].setValue(1234)
    dialog.shape.setCurrentIndex(dialog.shape.findText("E · Estribo 135°"))
    assert list(dialog._spins) == ["a", "b", "hook_extension_mm"]
    assert dialog._spins["a"].value() == 1234  # se conserva el valor del campo de igual nombre
    assert dialog._spins["hook_extension_mm"].value() == 0  # "estándar"
    assert dialog.result_group().shape.hook_extension_mm is None
    dialog._spins["hook_extension_mm"].setValue(50)
    assert "75" in dialog.info.text() and "Aviso" in dialog.info.text()  # gancho por debajo del mínimo
    assert dialog.result_group().shape == Stirrup135(1234, 500, 50)


def test_bar_dialog_prefills_existing_group(qapp):
    group = build_project().elements[2].groups[3]  # estribo E1 de V-101
    dialog = BarDialog(None, group=group, used_marks=["A1", "A2", "A3"])
    assert dialog.mark.text() == "E1" and dialog.bar.currentData() == "#3"
    assert dialog.shape.currentData() is Stirrup135
    assert dialog._spins["a"].value() == 220 and dialog._spins["b"].value() == 420
    assert dialog.quantity.value() == 38 and ok_enabled(dialog)
    assert dialog.result_group().shape == group.shape


def test_element_dialog(qapp):
    dialog = ElementDialog(None, levels=["Nivel 1", "Nivel 2"])
    assert not ok_enabled(dialog)  # falta el nombre
    dialog.name.setText("V-1")
    assert ok_enabled(dialog)
    dialog.type.setCurrentIndex(dialog.type.findData(ElementType.FOOTING))
    dialog.quantity.setValue(3)
    assert dialog.values() == ("V-1", ElementType.FOOTING, "Nivel 2", 3)  # propone el último nivel


def test_project_dialog_applies_values(qapp):
    project = build_project()
    dialog = ProjectDialog(None, project)
    dialog.name.setText("Torre Norte")
    dialog.stock.setValue(9000)
    dialog.rounding.setValue(10)
    dialog.paper.setCurrentIndex(dialog.paper.findData("a4"))
    dialog.apply_to(project)
    assert (project.name, project.stock_length_mm, project.length_rounding_mm, project.paper) == ("Torre Norte", 9000, 10, "a4")


# ------------------------------------------------------------------ confirmaciones en español
def click_button(label: str, texts: list[str]) -> None:
    """Programa el clic en el botón ``label`` del diálogo modal que esté abierto."""
    def click():
        box = QApplication.activeModalWidget()
        texts.extend(b.text() for b in box.buttons())
        next(b for b in box.buttons() if b.text() == label).click()
    QTimer.singleShot(100, click)


def test_yes_no_dialog_uses_spanish_buttons(window):
    texts: list[str] = []
    click_button("Sí", texts)
    assert window._ask("Título", "¿Seguro?") is True
    assert texts == ["Sí", "No"]
    click_button("No", [])
    assert window._ask("Título", "¿Seguro?") is False


def test_discard_changes_dialog(window):
    assert window._confirm_discard() is True  # sin cambios no pregunta
    window.modified = True
    texts: list[str] = []
    click_button("Descartar", texts)
    assert window._confirm_discard() is True
    assert sorted(texts) == ["Cancelar", "Descartar", "Guardar"]  # Qt los ordena por rol
    click_button("Cancelar", [])
    assert window._confirm_discard() is False
    window.modified = False


def test_delete_slots_ask_for_confirmation(window, monkeypatch):
    element = select_element(window, "V-101", "Nivel 1")
    window.bars_table.selectRow(0)
    monkeypatch.setattr(MainWindow, "_ask", lambda self, title, text: False)
    window.delete_bar()
    assert len(element.groups) == 4  # respondió "No": no se borra
    monkeypatch.setattr(MainWindow, "_ask", lambda self, title, text: True)
    window.delete_bar()
    assert len(element.groups) == 3
    window.delete_element()
    assert all(e.name != "V-101" or e.level != "Nivel 1" for e in window.project.elements)
