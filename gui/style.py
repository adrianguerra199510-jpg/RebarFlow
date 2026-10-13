"""Temas de la aplicación: claro (azul marino de las planillas exportadas) y nocturno.

Un :class:`Theme` reúne todos los colores. :func:`apply_theme` lo aplica a la aplicación (paleta de Qt más hoja de
estilos) y lo deja como tema actual (:func:`current`), que el resto de la interfaz consulta para los colores que no se
resuelven con la hoja de estilos: celdas de las tablas, textos HTML de los diálogos y esquemas de las barras.

La preferencia (claro / nocturno) se guarda con ``QSettings`` y se recupera al abrir la aplicación. **Sin preferencia
guardada se abre siempre en claro**, aunque Windows use su tema oscuro: el tema claro fija su propia paleta y el esquema
de colores de Qt en vez de heredarlos del sistema.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    """Colores de un tema (cadenas ``#RRGGBB``)."""

    name: str
    dark: bool
    window: str  # fondo de ventanas y diálogos
    panel: str  # fondo de tablas, árbol, pestañas y paneles
    toolbar: str
    toolbar_border: str
    hover: str  # botón de la barra bajo el puntero
    tab: str  # pestaña no seleccionada
    text: str
    muted: str  # textos secundarios
    disabled: str
    border: str
    grid: str
    header: str  # cabecera de las tablas y fila TOTAL
    header_text: str
    header_border: str
    accent: str  # títulos y pestaña activa
    band: str  # fila de título de elemento
    subtotal: str
    selection: str
    selection_text: str
    red: str  # avisos
    hook: str  # largo de ganchos
    coupler: str
    green: str  # retal reutilizable
    banner_bg: str
    banner_text: str
    banner_border: str
    dock_title: str
    input_bg: str
    input_border: str


LIGHT = Theme(
    name="claro", dark=False, window="#F4F6FA", panel="#FFFFFF", toolbar="#E8ECF4", toolbar_border="#1F3864",
    hover="#CFD9EE", tab="#DDE3EE", text="#1F2937", muted="#595959", disabled="#9AA5B8", border="#C9D1E0",
    grid="#DDE3EE", header="#1F3864", header_text="#FFFFFF", header_border="#3B568F", accent="#1F3864",
    band="#D9E1F2", subtotal="#F2F2F2", selection="#CFE0FF", selection_text="#111827", red="#C00000",
    hook="#B05504", coupler="#00695C", green="#2F6B2F", banner_bg="#FDE8E8", banner_text="#9B1C1C",
    banner_border="#F5B5B5", dock_title="#D9E1F2", input_bg="#FFFFFF", input_border="#B8C2D6",
)

DARK = Theme(
    name="nocturno", dark=True, window="#141922", panel="#1C2330", toolbar="#18202D", toolbar_border="#4C7BD6",
    hover="#2B3A55", tab="#222B3A", text="#E4E8F0", muted="#9AA7BD", disabled="#5F6B80", border="#323D52",
    grid="#2A3446", header="#22345A", header_text="#F1F5FD", header_border="#3A5288", accent="#8FB4FF",
    band="#27334D", subtotal="#232B3A", selection="#2E4B80", selection_text="#FFFFFF", red="#FF7B7B",
    hook="#F4A95A", coupler="#5FD3C0", green="#86C98A", banner_bg="#3A1F24", banner_text="#FF9C9C",
    banner_border="#7A3640", dock_title="#222E47", input_bg="#1A212D", input_border="#3A4660",
)

_current = LIGHT


def current() -> Theme:
    """Tema aplicado en este momento."""
    return _current


def stylesheet(t: Theme) -> str:
    return f"""
QMainWindow, QDialog {{ background: {t.window}; color: {t.text}; }}
QMenuBar {{ background: {t.toolbar}; color: {t.text}; }}
QMenuBar::item:selected {{ background: {t.hover}; }}
QMenu {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border}; }}
QMenu::item:selected {{ background: {t.selection}; color: {t.selection_text}; }}
QMenu::item:disabled {{ color: {t.disabled}; }}
QToolBar {{ background: {t.toolbar}; border: 0; border-bottom: 2px solid {t.toolbar_border}; spacing: 3px; padding: 4px; }}
QToolButton {{ padding: 5px 9px; border-radius: 4px; color: {t.text}; }}
QToolButton:hover {{ background: {t.hover}; }}
QToolButton:checked {{ background: {t.hover}; }}
QToolButton:disabled {{ color: {t.disabled}; }}
QMenuBar QToolButton#themeButton {{ padding: 3px 10px; margin: 2px 6px; border: 1px solid {t.border};
    border-radius: 12px; background: {t.panel}; }}
QMenuBar QToolButton#themeButton:hover {{ background: {t.hover}; }}
QTreeWidget, QTableWidget {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border};
    gridline-color: {t.grid}; selection-background-color: {t.selection}; selection-color: {t.selection_text}; }}
QTreeWidget::item {{ padding: 4px 2px; }}
QHeaderView::section {{ background: {t.header}; color: {t.header_text}; padding: 4px 6px; border: 0;
    border-right: 1px solid {t.header_border}; font-weight: bold; }}
QTableCornerButton::section {{ background: {t.header}; border: 0; }}
QTabWidget::pane {{ border: 1px solid {t.border}; background: {t.panel}; }}
QTabBar::tab {{ padding: 7px 16px; background: {t.tab}; color: {t.text}; border: 1px solid {t.border};
    border-bottom: 0; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {t.panel}; font-weight: bold; color: {t.accent}; }}
QDockWidget {{ font-weight: bold; color: {t.text}; }}
QDockWidget::title {{ background: {t.dock_title}; padding: 6px; }}
QStatusBar {{ background: {t.toolbar}; color: {t.text}; }}
QPushButton {{ padding: 5px 14px; }}
QScrollArea {{ background: {t.panel}; }}
QScrollArea > QWidget > QWidget {{ background: {t.panel}; }}
QToolTip {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border}; }}
QLineEdit, QComboBox {{ background: {t.input_bg}; color: {t.text}; border: 1px solid {t.input_border};
    border-radius: 3px; padding: 2px 4px; selection-background-color: {t.selection}; selection-color: {t.selection_text}; }}
QComboBox QAbstractItemView {{ background: {t.panel}; color: {t.text}; selection-background-color: {t.selection};
    selection-color: {t.selection_text}; }}
QLabel {{ color: {t.text}; }}
QLabel#sectionTitle {{ font-weight: bold; color: {t.accent}; font-size: 11pt; padding-top: 8px; }}
QLabel#detailTitle {{ font-weight: bold; color: {t.accent}; font-size: 11pt; }}
QLabel#elementTitle {{ font-size: 11pt; color: {t.accent}; }}
QLabel#hint {{ color: {t.muted}; }}
QLabel#banner {{ background: {t.banner_bg}; color: {t.banner_text}; border: 1px solid {t.banner_border}; padding: 6px 10px; }}
QLabel#shapePreview {{ background: {t.panel}; border: 1px solid {t.border}; color: {t.muted}; }}
BarDetailPanel {{ background: {t.panel}; }}
"""


def _palette(t: Theme) -> QPalette:
    """Paleta de Qt del tema: los widgets sin estilo propio (diálogos de archivo, calendarios…) la siguen.

    Se define completa también para el tema claro: si se dejara la del estilo, Qt (6.5 o más) la tomaría del
    esquema de colores de Windows y la interfaz saldría oscura en un equipo con el tema oscuro.
    """
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.window, QPalette.ColorRole.WindowText: t.text, QPalette.ColorRole.Base: t.panel,
        QPalette.ColorRole.AlternateBase: t.subtotal, QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.toolbar, QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.ToolTipBase: t.panel, QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.Highlight: t.selection, QPalette.ColorRole.HighlightedText: t.selection_text,
        QPalette.ColorRole.PlaceholderText: t.disabled, QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.BrightText: "#FFFFFF",
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorRole.Light, QColor("#FFFFFF" if not t.dark else "#3A465E"))
    palette.setColor(QPalette.ColorRole.Mid, QColor(t.border))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#9AA5B8" if not t.dark else "#0E1219"))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#000000"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.disabled))
    return palette


def apply_theme(app: QApplication, dark: bool) -> Theme:
    """Aplica el tema claro u oscuro a toda la aplicación y lo deja como tema actual."""
    global _current
    _current = DARK if dark else LIGHT
    app.setStyle("Fusion")
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):  # Qt 6.8+: que el esquema del sistema (Windows oscuro) no mande sobre el elegido
        hints.setColorScheme(Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)
    app.setPalette(_palette(_current))
    app.setStyleSheet(stylesheet(_current))
    return _current


# ------------------------------------------------------------------ preferencia guardada
_KEY = "tema"


def _settings() -> QSettings:
    return QSettings("RebarFlow", "RebarFlow")


def preferred_dark() -> bool:
    """Si la última vez se dejó el modo nocturno (claro por omisión)."""
    try:
        return str(_settings().value(_KEY, "claro")) == "nocturno"
    except Exception:  # noqa: BLE001 - una preferencia ilegible no debe impedir abrir la aplicación
        return False


def remember_dark(dark: bool) -> None:
    try:
        _settings().setValue(_KEY, "nocturno" if dark else "claro")
    except Exception:  # noqa: BLE001
        pass
