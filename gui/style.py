"""Hoja de estilos de la aplicación (azul marino de las planillas exportadas)."""

STYLE = """
QMainWindow, QDialog { background: #F4F6FA; }
QToolBar { background: #E8ECF4; border: 0; border-bottom: 2px solid #1F3864; spacing: 3px; padding: 4px; }
QToolButton { padding: 5px 9px; border-radius: 4px; color: #1F2937; }
QToolButton:hover { background: #CFD9EE; }
QToolButton:disabled { color: #9AA5B8; }
QTreeWidget, QTableWidget { background: white; border: 1px solid #C9D1E0; gridline-color: #DDE3EE;
    selection-background-color: #CFE0FF; selection-color: #111827; }
QTreeWidget::item { padding: 4px 2px; }
QHeaderView::section { background: #1F3864; color: white; padding: 4px 6px; border: 0;
    border-right: 1px solid #3B568F; font-weight: bold; }
QTabWidget::pane { border: 1px solid #C9D1E0; background: white; }
QTabBar::tab { padding: 7px 16px; background: #DDE3EE; border: 1px solid #C9D1E0; border-bottom: 0;
    margin-right: 2px; }
QTabBar::tab:selected { background: white; font-weight: bold; color: #1F3864; }
QDockWidget { font-weight: bold; }
QDockWidget::title { background: #D9E1F2; padding: 6px; }
QStatusBar { background: #E8ECF4; }
QPushButton { padding: 5px 14px; }
QLabel#sectionTitle { font-weight: bold; color: #1F3864; font-size: 11pt; padding-top: 8px; }
QLabel#detailTitle { font-weight: bold; color: #1F3864; font-size: 11pt; }
QLabel#elementTitle { font-size: 11pt; color: #1F3864; }
QLabel#hint { color: #595959; }
QLabel#banner { background: #FDE8E8; color: #9B1C1C; border: 1px solid #F5B5B5; padding: 6px 10px; }
QLabel#shapePreview { background: white; border: 1px solid #C9D1E0; color: #6B7280; }
BarDetailPanel { background: white; }
"""
