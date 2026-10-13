"""Varios proyectos abiertos a la vez: cinta de proyectos (seleccionar, modificar, duplicar, cerrar a un clic)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QTimer, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.project import Project  # noqa: E402
from core.serialization import load_project, save_project  # noqa: E402
from gui import style  # noqa: E402
from gui.dialogs import ProjectDialog  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from sample_project import build_bridge_project, build_project  # noqa: E402
from tests.test_gui import _isolate_theme, click_button, qapp  # noqa: E402,F401  (fixtures)


@pytest.fixture
def window(qapp):
    win = MainWindow(build_project())
    win.show()
    yield win
    for session in win.sessions:
        session.modified = False
    win.close()


def titles(window) -> list[str]:
    return window.project_bar.titles()


def tab_center(window, index: int) -> QPoint:
    tabs = window.project_bar.tabs
    rect = tabs.tabRect(index)
    return QPoint(rect.left() + 20, rect.center().y())  # a la izquierda de la «×»


# ------------------------------------------------------------------ abrir y seleccionar
def test_the_window_starts_with_one_project_in_the_ribbon(window):
    assert len(window.sessions) == 1 and titles(window) == [window.project.name]
    assert window.ribbon.objectName() == "projectRibbon" and window.project_bar.tabs.objectName() == "projectTabs"


def test_new_projects_open_in_new_tabs_with_unique_names(window):
    window.new_project()
    window.new_project()
    assert len(window.sessions) == 3 and window._index == 2
    assert [s.project.name for s in window.sessions][1:] == ["Proyecto sin título", "Proyecto sin título 2"]
    assert titles(window) == [s.project.name for s in window.sessions]
    assert window.project_bar.current_index() == 2 and window.project is window.sessions[2].project


def test_examples_open_in_their_own_tabs_and_keep_the_others(window):
    first = window.project
    window.open_catalog()
    window.open_bridge()
    assert [s.project.name for s in window.sessions] == [first.name, "Catálogo de formas", "Paso inferior de ejemplo"]
    assert window.sessions[0].project is first and not any(s.modified for s in window.sessions)


def test_a_blank_project_is_replaced_instead_of_leaving_an_empty_tab(qapp):
    win = MainWindow()  # arranca con un proyecto vacío sin tocar
    win.open_bridge()
    assert len(win.sessions) == 1 and win.project.name == "Paso inferior de ejemplo"
    win.new_project()  # «Nuevo» sí abre una pestaña vacía aunque el activo sea el único
    win.open_catalog()  # y el vacío activo se reemplaza al abrir otro
    assert [s.project.name for s in win.sessions] == ["Paso inferior de ejemplo", "Catálogo de formas"]
    win.close()


def test_clicking_a_tab_switches_the_project(window):
    window.open_bridge()
    window.open_catalog()
    for index in (0, 2, 1):
        QTest.mouseClick(window.project_bar.tabs, Qt.MouseButton.LeftButton, pos=tab_center(window, index))
        assert window._index == index and window.project is window.sessions[index].project
        assert window.tree.topLevelItem(0).text(0) == window.project.name
        assert window.windowTitle() == f"{window.project.name} — RebarFlow"


def test_each_project_remembers_its_selection_and_tab(window):
    window.open_bridge()
    bridge_element = window.sessions[1].project.elements[2]
    window.refresh(select=bridge_element)
    window.tabs.setCurrentIndex(2)  # Resumen
    window.select_project(0)
    building_element = window.sessions[0].project.elements[0]
    assert window.current_element() is building_element and window.tabs.currentIndex() == 0
    window.tabs.setCurrentIndex(1)
    window.select_project(1)
    assert window.current_element() is bridge_element and window.tabs.currentIndex() == 2
    window.select_project(0)
    assert window.tabs.currentIndex() == 1 and window.current_element() is building_element


def test_edits_go_to_the_active_project_only(window):
    window.open_bridge()
    bridge, building = window.sessions[1].project, window.sessions[0].project
    before = len(building.elements)
    window.add_element_values("NUEVO-1", window.current_element().element_type)
    assert [e.name for e in bridge.elements].count("NUEVO-1") == 1
    assert len(building.elements) == before and not window.sessions[0].modified and window.sessions[1].modified
    assert titles(window)[1].startswith("•") and not titles(window)[0].startswith("•")


def test_tabs_of_projects_with_the_same_name_are_told_apart(window):
    window.open_sample()
    window.open_sample()
    base = window.sessions[0].project.name
    assert titles(window) == [base, f"{base} (2)", f"{base} (3)"]
    assert [s.project.name for s in window.sessions] == [base] * 3  # solo la pestaña se distingue


# ------------------------------------------------------------------ modificar
def test_the_modify_project_button_edits_the_active_project(window, monkeypatch):
    window.open_bridge()
    opened: list[str] = []

    def fake_exec(self):
        opened.append(self.name.text())
        self.name.setText("Puente renombrado")
        return True

    monkeypatch.setattr(ProjectDialog, "exec", fake_exec)
    window.act_props.trigger()
    assert opened == ["Paso inferior de ejemplo"] and window.sessions[1].project.name == "Puente renombrado"
    assert window.sessions[0].project.name != "Puente renombrado"
    assert window.sessions[1].modified and titles(window)[1] == "•  Puente renombrado"


def test_double_clicking_a_tab_edits_that_project_even_if_it_is_not_active(window, monkeypatch):
    window.open_bridge()
    window.select_project(0)
    seen: list[str] = []
    monkeypatch.setattr(ProjectDialog, "exec", lambda self: seen.append(self.name.text()) and False)
    QTest.mouseDClick(window.project_bar.tabs, Qt.MouseButton.LeftButton, pos=tab_center(window, 1))
    assert window._index == 1 and seen == ["Paso inferior de ejemplo"]
    assert not window.modified  # canceló


# ------------------------------------------------------------------ duplicar
def test_duplicate_makes_an_independent_unsaved_copy(window):
    original = window.project
    n = len(original.elements)
    window.duplicate_project()
    copy = window.project
    assert copy is not original and copy.name == f"{original.name} (copia)" and window._index == 1
    assert window.session.modified and window.path is None and len(copy.elements) == n
    window.add_element_values("SOLO-COPIA", copy.elements[0].element_type)
    assert len(original.elements) == n and not window.sessions[0].modified
    window.act_duplicate.trigger()
    assert window.project.name == f"{original.name} (copia) (copia)" and len(window.sessions) == 3


def test_duplicate_keeps_the_header_and_the_logo():
    from tests.test_gui import _png_bytes  # noqa: PLC0415
    from exporters.logo import normalize_logo  # noqa: PLC0415

    win = MainWindow(build_bridge_project())
    win.project.logo_png = normalize_logo(_png_bytes())
    win.duplicate_project(0)
    assert win.project.logo_png == win.sessions[0].project.logo_png and win.project.client == "Consorcio de ejemplo"
    assert win.project.group_label == "Estructura"
    for session in win.sessions:
        session.modified = False
    win.close()


# ------------------------------------------------------------------ cerrar
def test_closing_a_project_selects_a_neighbour(window):
    building_name = window.project.name
    window.open_catalog()
    window.open_bridge()  # [edificio, catálogo, puente], activo: puente
    assert window.close_project(1) is True  # una pestaña a la izquierda: sigue activo el puente
    assert [s.project.name for s in window.sessions] == [building_name, "Paso inferior de ejemplo"]
    assert window.project.name == "Paso inferior de ejemplo"
    assert window.close_project() is True  # cierra el activo: queda el anterior
    assert len(window.sessions) == 1 and window.project is window.sessions[0].project


def test_closing_the_last_project_leaves_a_blank_one(window):
    assert window.close_project() is True
    assert len(window.sessions) == 1 and window.session.blank and window.project.name == "Proyecto sin título"
    assert window.tree.topLevelItem(0).text(0) == "Proyecto sin título"


def test_the_close_button_of_a_tab_closes_that_project(window):
    window.open_bridge()
    button = window.project_bar.tabs.tabButton(0, window.project_bar.tabs.ButtonPosition.RightSide)
    button.click()
    assert [s.project.name for s in window.sessions] == ["Paso inferior de ejemplo"]


def test_closing_a_modified_project_asks_and_can_be_cancelled(window):
    window.open_bridge()
    window.add_element_values("X-1", window.current_element().element_type)  # cambia el puente
    texts: list[str] = []
    click_button("Cancelar", texts)
    assert window.close_project() is False and len(window.sessions) == 2
    assert sorted(texts) == ["Cancelar", "Descartar", "Guardar"]
    click_button("Descartar", [])
    assert window.close_project() is True and len(window.sessions) == 1 and window.project.name == "Edificio de ejemplo"


def test_closing_asks_about_a_background_project_and_shows_it(window):
    window.open_bridge()
    window.add_element_values("X-1", window.current_element().element_type)
    window.select_project(0)
    shown: list[str] = []
    QTimer.singleShot(100, lambda: (shown.append(window.project.name), next(
        b for b in QApplication.activeModalWidget().buttons() if b.text() == "Cancelar").click()))
    assert window.close_project(1) is False
    assert shown == ["Paso inferior de ejemplo"]  # el proyecto del que se pregunta pasó a ser el activo


def test_closing_the_window_asks_for_each_modified_project(window):
    window.open_bridge()
    window.open_catalog()
    for index in (0, 2):
        window.select_project(index)
        window.add_element_values("Y-1", window.current_element().element_type)
    asked: list[str] = []

    def answer(button):
        def click():
            box = QApplication.activeModalWidget()
            asked.append(window.project.name)
            next(b for b in box.buttons() if b.text() == button).click()
        QTimer.singleShot(100, click)

    answer("Cancelar")
    assert window.close() is False  # cancelar en el primero detiene el cierre
    assert asked == ["Edificio de ejemplo"]
    answer("Descartar")
    QTimer.singleShot(400, lambda: next(b for b in QApplication.activeModalWidget().buttons() if b.text() == "Descartar").click())
    assert window.close() is True and asked[1:] == ["Edificio de ejemplo"]


def test_close_other_projects(window):
    window.open_catalog()
    window.open_bridge()
    window.close_other_projects(1)
    assert [s.project.name for s in window.sessions] == ["Catálogo de formas"] and window.project.name == "Catálogo de formas"


# ------------------------------------------------------------------ archivos
def test_open_path_opens_in_a_new_tab_and_does_not_repeat_an_open_file(window, tmp_path):
    path = tmp_path / "puente.rebarflow.json"
    save_project(build_bridge_project(), path)
    from core.serialization import FILE_SUFFIX  # noqa: PLC0415

    path = tmp_path / f"puente{FILE_SUFFIX}"
    save_project(build_bridge_project(), path)
    assert window.open_path(path) and len(window.sessions) == 2 and window.path == path
    window.select_project(0)
    assert window.open_path(path) and len(window.sessions) == 2 and window._index == 1  # solo lo selecciona
    assert "puente" in window._tab_tip(1)


def test_save_all_saves_every_modified_project(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415
    from core.serialization import FILE_SUFFIX  # noqa: PLC0415

    window.open_bridge()
    for index in (0, 1):
        window.select_project(index)
        window.add_element_values(f"S-{index}", window.current_element().element_type)
    assert window.act_save_all.isEnabled()
    names = iter([tmp_path / f"a{FILE_SUFFIX}", tmp_path / f"b{FILE_SUFFIX}"])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(next(names)), ""))
    assert window.save_all() is True
    assert not any(s.modified for s in window.sessions) and not window.act_save_all.isEnabled()
    assert {p.name for p in tmp_path.iterdir()} == {f"a{FILE_SUFFIX}", f"b{FILE_SUFFIX}"}
    assert any(e.name == "S-0" for e in load_project(tmp_path / f"a{FILE_SUFFIX}").elements)


# ------------------------------------------------------------------ reordenar, menús y estilo
def test_dragging_tabs_reorders_the_projects_and_keeps_the_active_one(window):
    window.open_catalog()
    window.open_bridge()  # activo: puente (índice 2)
    active = window.project
    window.project_bar.tabs.moveTab(2, 0)
    assert window.project is active and window._index == 0
    assert [s.project.name for s in window.sessions] == titles(window)
    window.select_project(2)
    assert window.project.name == "Catálogo de formas"


def test_context_menu_actions(window):
    window.open_bridge()

    def choose(index: int, text: str) -> None:
        menu = window._build_project_menu(index)
        assert [a.text() for a in menu.actions() if a.text()] == [
            "Modificar proyecto…", "Duplicar proyecto", "Guardar proyecto", "Cerrar proyecto", "Cerrar los demás"]
        next(a for a in menu.actions() if a.text() == text).trigger()

    choose(0, "Duplicar proyecto")
    assert len(window.sessions) == 3 and window.project.name == "Edificio de ejemplo (copia)"
    window.session.modified = False
    choose(2, "Cerrar los demás")
    assert len(window.sessions) == 1 and window.project.name == "Edificio de ejemplo (copia)"
    assert not next(a for a in window._build_project_menu(0).actions() if a.text() == "Cerrar los demás").isEnabled()


def test_project_menu_and_shortcuts(window):
    menus = {a.text().replace("&", ""): a.menu() for a in window.menuBar().actions() if a.menu()}
    assert "Proyecto" in menus
    for action in (window.act_new, window.act_props, window.act_duplicate, window.act_close_project,
                   window.act_next_project, window.act_prev_project):
        assert action in menus["Proyecto"].actions()
    assert window.act_save_all in menus["Archivo"].actions()
    assert not window.act_next_project.isEnabled()
    window.open_bridge()
    assert window.act_next_project.isEnabled()
    window.act_prev_project.trigger()
    assert window._index == 0
    window.act_next_project.trigger()
    assert window._index == 1
    window.act_next_project.trigger()  # da la vuelta
    assert window._index == 0
    window.act_duplicate.trigger()
    assert len(window.sessions) == 3
    window.session.modified = False
    window.act_close_project.trigger()
    assert len(window.sessions) == 2


def test_ribbon_is_styled_in_both_themes_and_marks_the_active_close_button(window, qapp):
    window.open_bridge()
    tabs = window.project_bar.tabs
    side = tabs.ButtonPosition.RightSide
    assert [tabs.tabButton(i, side).property("current") for i in range(2)] == [False, True]
    sheet = qapp.styleSheet()
    assert "QTabBar#projectTabs::tab:selected" in sheet and "QToolBar#projectRibbon" in sheet
    window.set_dark_mode(True, remember=False)
    assert style.current().dark and style.current().header in qapp.styleSheet()
    window.select_project(0)
    assert [tabs.tabButton(i, side).property("current") for i in range(2)] == [True, False]
    window.set_dark_mode(False, remember=False)


# ------------------------------------------------------------------ botones de proyecto en la barra de herramientas
def toolbar_actions(window):
    toolbar = next(t for t in window.findChildren(type(window.ribbon)) if t.windowTitle() == "Principal")
    return toolbar, [a for a in toolbar.actions() if not a.isSeparator()]


def test_project_buttons_live_in_the_main_toolbar_with_project_names(window):
    toolbar, actions = toolbar_actions(window)
    assert [a.iconText() for a in actions][:5] == [
        "Nuevo proyecto", "Abrir proyecto", "Guardar proyecto", "Modificar proyecto", "Duplicar proyecto"]
    assert actions[:5] == [window.act_new, window.act_open, window.act_save, window.act_props, window.act_duplicate]
    assert toolbar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon and toolbar.iconSize().width() == 32
    assert all(not a.icon().isNull() for a in actions)


def test_the_ribbon_has_only_the_project_tabs(window):
    from PySide6.QtWidgets import QToolButton  # noqa: PLC0415

    # solo quedan las «×» de las pestañas y los botones de desplazamiento propios de la barra de pestañas
    buttons = [b for b in window.project_bar.findChildren(QToolButton) if b.objectName() not in ("tabClose", "ScrollLeftButton", "ScrollRightButton")]
    assert buttons == [] and not hasattr(window.project_bar, "btn_edit")
    assert window.project_bar.label.text() == "Proyectos"


def test_project_toolbar_buttons_act_on_the_active_project(window, monkeypatch):
    window.open_bridge()
    toolbar, _ = toolbar_actions(window)
    from PySide6.QtWidgets import QToolButton  # noqa: PLC0415

    def button(action):
        return next(b for b in toolbar.findChildren(QToolButton) if b.defaultAction() is action)

    button(window.act_duplicate).click()
    assert len(window.sessions) == 3 and window.project.name == "Paso inferior de ejemplo (copia)"
    button(window.act_new).click()
    assert len(window.sessions) == 4 and window.project.name == "Proyecto sin título"
    seen: list[str] = []
    monkeypatch.setattr(ProjectDialog, "exec", lambda self: seen.append(self.name.text()) and False)
    window.select_project(1)
    button(window.act_props).click()
    assert seen == ["Paso inferior de ejemplo"]


def test_menus_use_the_project_names_too(window):
    assert [window.act_new.text(), window.act_open.text(), window.act_save.text(), window.act_save_as.text(),
            window.act_props.text(), window.act_duplicate.text(), window.act_close_project.text()] == [
        "Nuevo proyecto", "Abrir proyecto…", "Guardar proyecto", "Guardar proyecto como…", "Modificar proyecto…",
        "Duplicar proyecto", "Cerrar proyecto"]
