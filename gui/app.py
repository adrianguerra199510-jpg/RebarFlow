"""Punto de entrada de la interfaz gráfica: ``python -m gui`` o el script ``rebarflow``."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from gui.icon import app_icon
from gui.main_window import MainWindow
from gui import style


def create_application(argv: list[str] | None = None, dark: bool | None = None) -> QApplication:
    """Crea la aplicación con el tema ``dark`` (claro o nocturno); por omisión, el que se dejó la última vez."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setOrganizationName("RebarFlow")
    app.setApplicationName("RebarFlow")
    style.apply_theme(app, style.preferred_dark() if dark is None else dark)
    app.setWindowIcon(app_icon())
    return app


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = create_application(argv)
    window = MainWindow()
    if len(argv) > 1 and Path(argv[1]).is_file():
        window.open_path(Path(argv[1]))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
