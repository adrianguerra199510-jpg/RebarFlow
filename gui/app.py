"""Punto de entrada de la interfaz gráfica: ``python -m gui`` o el script ``rebarflow``."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from gui.style import STYLE


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setApplicationName("RebarFlow")
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
