"""Genera ``rebarflow.ico`` (16 a 256 px) con el icono de la aplicación.

Uso (desde la raíz del repositorio)::

    python packaging/make_icon.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gui.icon import app_icon_image  # noqa: E402

if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "rebarflow.ico"
    app_icon_image(256).save(target, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print(f"Icono escrito en {target}")
