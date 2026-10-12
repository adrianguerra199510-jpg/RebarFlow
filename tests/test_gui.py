from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

from core.element import ElementType  # noqa: E402
from core.rebar import get_rebar  # noqa: E402
from core.shape_codes import Stirrup  # noqa: E402
from gui.app import create_application  # noqa: E402
from engine.cutting_report import plan_rows  # noqa: E402
from gui.dialogs import BarDialog, ElementDialog, LegsEditor, ProjectDialog  # noqa: E402
from core.shape_templates import CustomBar, HookedBar  # noqa: E402
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
    dialog.shape.setCurrentIndex(dialog.shape.findText("E · Estribo rectangular"))
    dialog._widgets["a"].setValue(320)
    dialog._widgets["b"].setValue(320)
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
    dialog._widgets["a"].setValue(60)
    assert not ok_enabled(dialog) and "mínimo geométrico" in dialog.info.text()
    with pytest.raises(ValueError):
        dialog.result_group()
    dialog._widgets["a"].setValue(1000)
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
    dialog._widgets["length"].setValue(13000)
    assert not ok_enabled(dialog) and "excede la barra comercial" in dialog.info.text()


def test_bar_dialog_builds_fields_from_shape_and_keeps_values(qapp):
    dialog = BarDialog(None)
    dialog.shape.setCurrentIndex(dialog.shape.findText("U · Gancho U"))
    assert list(dialog._widgets) == ["a", "b", "c"]
    dialog._widgets["a"].setValue(1234)
    dialog.shape.setCurrentIndex(dialog.shape.findText("E · Estribo rectangular"))
    assert list(dialog._widgets) == ["a", "b", "hook_start", "ext_start", "hook_end", "ext_end"]
    assert dialog._widgets["a"].value() == 1234  # se conserva el valor del campo de igual nombre
    assert dialog._widgets["ext_start"].value() == 0 and dialog._widgets["ext_end"].value() == 0  # "estándar"
    assert dialog.result_group().shape.ext_start is None
    dialog._widgets["ext_start"].setValue(50)
    assert "75" in dialog.info.text() and "Aviso" in dialog.info.text()  # gancho por debajo del mínimo
    assert dialog.result_group().shape == Stirrup(1234, 400, ext_start=50)


def _choose(dialog, name, value):
    combo = dialog._widgets[name]
    combo.setCurrentIndex(combo.findData(value))


def test_bar_dialog_offers_bar_14(qapp):
    dialog = BarDialog(None)
    designations = [dialog.bar.itemData(i) for i in range(dialog.bar.count())]
    assert designations[-1] == "#14" and designations[:-1] == [f"#{n}" for n in range(3, 12)]
    dialog.bar.setCurrentIndex(dialog.bar.findData("#14"))
    dialog.shape.setCurrentIndex(dialog.shape.findText("L · Bastón L"))
    assert ok_enabled(dialog) and "Longitud de corte" in dialog.info.text()
    dialog.shape.setCurrentIndex(dialog.shape.findText("E · Estribo rectangular"))
    assert not ok_enabled(dialog) and "mayores a #8" in dialog.info.text()  # la norma no define estribos de #14


def test_bar_dialog_stirrup_has_a_hook_per_leg(qapp):
    dialog = BarDialog(None)
    dialog.shape.setCurrentIndex(dialog.shape.findText("E · Estribo rectangular"))
    assert not any(dialog.shape.itemText(i).startswith("E90") for i in range(dialog.shape.count()))
    _choose(dialog, "hook_end", 90)
    shape = dialog.result_group().shape
    assert (shape.hook_start, shape.hook_end) == (135, 90)
    assert "135° · 75  /  90° · 75" in dialog.info.text()


def test_bar_dialog_ring_with_hooks_and_no_lap(qapp):
    dialog = BarDialog(None)
    dialog.shape.setCurrentIndex(dialog.shape.findText("AR · Aro circular"))
    assert list(dialog._widgets) == ["diameter", "lap", "hook_start", "ext_start", "hook_end", "ext_end"]
    dialog._widgets["lap"].setValue(0)  # los ganchos cierran el aro: sin traslape
    _choose(dialog, "hook_start", 135)
    _choose(dialog, "hook_end", 135)
    shape = dialog.result_group().shape
    assert shape.lap == 0 and shape.hook_start == shape.hook_end == 135
    assert "2 × 135° · 75" in dialog.info.text()


def test_bar_dialog_spiral_extra_turns_and_hooks(qapp):
    dialog = BarDialog(None)
    dialog.shape.setCurrentIndex(dialog.shape.findText("ES · Espiral"))
    assert list(dialog._widgets) == ["diameter", "pitch", "height", "turns_start", "turns_end", "hook_start", "ext_start",
                                     "hook_end", "ext_end"]
    dialog._widgets["turns_start"].setValue(2.0)
    dialog._widgets["turns_end"].setValue(0.5)
    _choose(dialog, "hook_end", 90)
    shape = dialog.result_group().shape
    assert (shape.turns_start, shape.turns_end, shape.hook_start, shape.hook_end) == (2.0, 0.5, 0, 90)
    assert "2 al inicio y 0.5 al final" in dialog.info.text() and "90° · 75" in dialog.info.text()


def test_bar_dialog_prefills_existing_group(qapp):
    group = build_project().elements[2].groups[3]  # estribo E1 de V-101
    dialog = BarDialog(None, group=group, used_marks=["A1", "A2", "A3"])
    assert dialog.mark.text() == "E1" and dialog.bar.currentData() == "#3"
    assert dialog.shape.currentData() is Stirrup
    assert dialog._widgets["a"].value() == 220 and dialog._widgets["b"].value() == 420
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


# ------------------------------------------------------------------ plan de corte, ganchos, plantillas
def test_plan_tab_lists_the_cutting_sequence(window):
    assert window.tabs.tabText(3) == "Plan de corte"
    table = window.plan_table
    picture_rows = [r for r in range(table.rowCount()) if table.item(r, 3) is not None and not table.item(r, 3).icon().isNull()]
    assert len(picture_rows) == sum(len(plan_rows(s)) for s in window.result.diameter_summaries)
    assert any("plan lineal" in (table.item(r, 0).text() if table.item(r, 0) else "") for r in range(table.rowCount()))
    window.project.stock_length_mm = 3000
    window.refresh()
    assert table.rowCount() == 1 and "Aún no hay barras" in table.item(0, 0).text()  # sin resultado, mensaje vacío


def test_hook_column_is_in_the_tables(window):
    select_element(window, "C-1", "Nivel 1")
    headers = [window.bars_table.horizontalHeaderItem(c).text() for c in range(window.bars_table.columnCount())]
    column = headers.index("Ganchos\n(° · mm)")
    stirrup_row = next(r for r in range(window.bars_table.rowCount())
                       if window.bars_table.line_for_row(r) and window.bars_table.line_for_row(r).mark == "E1")
    assert window.bars_table.item(stirrup_row, column).text().startswith("2 × 135°")
    select_element(window, "V-101", "Nivel 1")
    window.bars_table.selectRow(1)  # A2: U con ganchos de 90°
    assert "Ganchos (° · mm)" in window.detail.details.text() and "90°" in window.detail.details.text()


def test_bar_dialog_offers_every_template_with_a_thumbnail(qapp):
    dialog = BarDialog(None, suggested_mark="T")
    classes = [dialog.shape.itemData(i) for i in range(dialog.shape.count())]
    assert {"R", "L", "U", "E", "G", "EU", "Z", "Q", "O", "ET", "ETR", "AR", "ES", "X"} <= {c.code for c in classes}
    for index, cls in enumerate(classes):
        assert not dialog.shape.itemIcon(index).isNull(), cls.code
        dialog.shape.setCurrentIndex(index)
        assert dialog.shape_hint.text() == cls.description
        assert ok_enabled(dialog), f"la plantilla {cls.code} debe ser válida con sus valores por defecto"
        assert dialog.result_group().shape == cls.template()


def test_hooked_bar_dialog_validates_hooks_and_style(qapp):
    dialog = BarDialog(None, suggested_mark="G1")
    dialog.shape.setCurrentIndex(dialog.shape.findText("G · Barra con ganchos"))
    start = dialog._widgets["hook_start"]
    start.setCurrentIndex(start.findData(135))
    assert not ok_enabled(dialog) and "no hay gancho estándar de 135°" in dialog.info.text()
    style = dialog._widgets["style"]
    style.setCurrentIndex(style.findData("stirrup"))
    assert ok_enabled(dialog) and "Ganchos (° · mm)" in dialog.info.text()
    assert dialog.result_group().shape.hook_start == 135 and dialog.result_group().cut.hooks[0].extension_mm == 75.0
    dialog._widgets["ext_start"].setValue(50)  # bajo el mínimo de la norma: aviso, no error
    assert ok_enabled(dialog) and "Aviso" in dialog.info.text()


def test_legs_editor_operations(qapp):
    editor = LegsEditor((300.0, 200.0, 300.0), (90.0, -90.0))
    assert editor.values() == ((300.0, 200.0, 300.0), (90.0, -90.0))
    editor.add_leg()
    assert editor.values() == ((300.0, 200.0, 300.0, 300.0), (90.0, -90.0, 90.0))
    editor.reverse()
    assert editor.values() == ((300.0, 300.0, 200.0, 300.0), (-90.0, 90.0, -90.0))
    editor.mirror()
    assert editor.values()[1] == (90.0, -90.0, 90.0)
    editor.table.selectRow(1)
    editor.remove_leg()  # desaparece el tramo 2 y el giro con que salía de él
    assert editor.values() == ((300.0, 200.0, 300.0), (90.0, 90.0))
    editor.table.setCurrentCell(-1, -1)
    editor.remove_leg()  # sin selección quita el último tramo
    assert editor.values() == ((300.0, 200.0), (90.0,))
    editor.remove_leg()
    editor.remove_leg()
    assert len(editor.values()[0]) == 1 and editor.values()[1] == ()  # siempre queda al menos un tramo


def test_custom_shape_through_the_dialog(qapp):
    dialog = BarDialog(None, suggested_mark="X1")
    dialog.shape.setCurrentIndex(dialog.shape.findText("X · Personalizada"))
    assert dialog._editor is not None
    dialog._editor.set_values((400.0, 300.0, 200.0), (90.0, -45.0))
    hook = dialog._widgets["hook_end"]
    hook.setCurrentIndex(hook.findData(90))
    assert ok_enabled(dialog)
    shape = dialog.result_group().shape
    assert shape == CustomBar(legs=(400.0, 300.0, 200.0), angles=(90.0, -45.0), hook_end=90)
    dialog._editor.set_values((400.0, 300.0), (200.0,))  # un giro de 200° es imposible
    assert not ok_enabled(dialog)


def test_dialog_prefills_existing_hooked_and_custom_shapes(qapp):
    for original in (HookedBar(1200, 135, 100, 90, None, 1, "stirrup"),
                     CustomBar(legs=(300.0, 200.0, 300.0), angles=(90.0, -90.0), hook_start=90)):
        group = build_project().elements[2].groups[0].__class__("P1", get_rebar("#4"), original, 2)
        dialog = BarDialog(None, group=group)
        assert dialog.shape.currentData() is type(original)
        assert ok_enabled(dialog) and dialog.result_group().shape == original


def test_other_element_type_and_project_remnant_setting(qapp, window):
    dialog = ElementDialog(None, levels=["Nivel 1"])
    dialog.name.setText("MURETE-1")
    dialog.type.setCurrentIndex(dialog.type.findData(ElementType.OTHER))
    assert dialog.type.currentText() == "Otros" and dialog.values()[1] is ElementType.OTHER
    element = window.add_element_values(*dialog.values())
    assert element.element_type is ElementType.OTHER and window.current_element() is element
    assert "Otros" in window.tree.currentItem().text(0)  # el árbol muestra «MURETE-1 · Otros ×1»
    assert window.result is not None  # el cálculo y las tablas funcionan con el tipo nuevo

    project = build_project()
    pdialog = ProjectDialog(None, project)
    assert pdialog.reusable.value() == 1000
    pdialog.reusable.setValue(2500)
    pdialog.apply_to(project)
    assert project.reusable_remnant_mm == 2500


def test_open_catalog_example_from_the_menu(window):
    window.open_catalog()
    assert window.project.name == "Catálogo de formas" and not window.modified
    assert window.bars_table.rowCount() == 22  # 21 marcas + subtotal
    pictures = [r for r in range(window.bars_table.rowCount()) if window.bars_table.line_for_row(r)]
    assert all(not window.bars_table.item(r, 3).icon().isNull() for r in pictures)
    assert window.plan_table.rowCount() > 1 and window.act_catalog.text().startswith("Abrir ejemplo")
