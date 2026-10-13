"""Iconos propios de la interfaz: existen para cada botón, siguen el tema y tienen variante deshabilitada."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QAction, QColor, QIcon  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402

from gui import icons, style  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from sample_project import build_project  # noqa: E402
from tests.test_gui import _isolate_theme, qapp  # noqa: E402,F401  (fixtures)


def opaque_pixels(pixmap) -> int:
    image = pixmap.toImage()
    return sum(1 for x in range(image.width()) for y in range(image.height()) if QColor(image.pixel(x, y)).alpha() > 40)


def test_every_icon_draws_something_at_every_size(qapp):
    assert len(icons.NAMES) >= 25
    for name in icons.NAMES:
        for size in (16, 24, 32, 64):
            pixmap = icons.render(name, size, dark=False)
            assert (pixmap.width(), pixmap.height()) == (2 * size, 2 * size)
            assert opaque_pixels(pixmap) > 0.06 * pixmap.width() * pixmap.height(), (name, size)


def test_icons_differ_between_themes_and_when_disabled(qapp):
    for name in icons.NAMES:
        light = icons.render(name, 32, dark=False).toImage()
        dark = icons.render(name, 32, dark=True).toImage()
        off = icons.render(name, 32, dark=False, enabled=False).toImage()
        assert light != dark and light != off, name


def test_icon_returns_a_qicon_for_the_current_theme_with_a_disabled_variant(qapp):
    icon = icons.icon("new_project")
    assert isinstance(icon, QIcon) and not icon.isNull()
    normal = icon.pixmap(32).toImage()
    disabled = icon.pixmap(32, QIcon.Mode.Disabled).toImage()
    assert normal != disabled
    with pytest.raises(KeyError):
        icons.icon("no_existe")


def test_all_icons_have_distinct_drawings(qapp):
    images = {name: icons.render(name, 48, dark=False).toImage().bits().tobytes() for name in icons.NAMES}
    # "project" y "open_project" comparten dibujo a propósito (la raíz del árbol es una carpeta de obra)
    shared = {frozenset({"project", "open_project"})}
    seen: dict[bytes, str] = {}
    for name, data in images.items():
        if data in seen:
            assert frozenset({name, seen[data]}) in shared, (name, seen[data])
        seen[data] = name


def test_every_toolbar_and_menu_action_has_an_own_icon_and_it_follows_the_theme(qapp, monkeypatch):
    window = MainWindow(build_project())
    named = {action.text().replace("&", ""): name for action, name in window._icon_names.items()}
    for action in (window.act_new, window.act_open, window.act_save, window.act_props, window.act_duplicate,
                   window.act_add_element, window.act_add_bar, window.act_edit_bar, window.act_delete_bar,
                   window.act_excel, window.act_pdf, window.act_detail):
        assert action in window._icon_names and not action.icon().isNull(), action.text()
    assert len(set(window._icon_names[a] for a in (window.act_new, window.act_open, window.act_save, window.act_props,
                                                   window.act_duplicate, window.act_add_element, window.act_add_bar,
                                                   window.act_edit_bar, window.act_delete_bar, window.act_excel,
                                                   window.act_pdf, window.act_detail))) == 12  # uno distinto por botón
    assert "Nuevo proyecto" in named
    light = window.act_save.icon().pixmap(32).toImage()
    window.set_dark_mode(True, remember=False)
    assert window.act_save.icon().pixmap(32).toImage() != light  # el icono se repinta con la paleta nocturna
    buttons = {b.text(): b for b in window.findChildren(QPushButton)}
    assert not buttons["Nueva barra"].icon().isNull() and not buttons["Eliminar"].icon().isNull()
    window.set_dark_mode(False, remember=False)
    assert window.act_save.icon().pixmap(32).toImage() == light
    for session in window.sessions:
        session.modified = False
    window.close()


def test_the_tree_uses_the_own_icons(qapp):
    window = MainWindow(build_project())
    root = window.tree.topLevelItem(0)
    assert not root.icon(0).isNull() and not root.child(0).icon(0).isNull()
    leaf = root.child(0)
    while leaf.childCount():
        leaf = leaf.child(0)
    assert leaf.icon(0).pixmap(16).toImage() == icons.icon("element").pixmap(16).toImage()
    window.close()


def test_light_palette_is_the_default_icon_palette(qapp):
    assert style.current().dark is False
    assert isinstance(icons.LIGHT_COLORS.ink, str) and QAction is not None
