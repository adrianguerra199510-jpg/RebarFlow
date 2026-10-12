# -*- mode: python ; coding: utf-8 -*-
"""Especificación de PyInstaller: carpeta ``dist/RebarFlow`` con ``RebarFlow.exe`` (sin consola).

    pyinstaller --noconfirm --clean packaging/rebarflow.spec
"""
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH lo define PyInstaller)

analysis = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "rebarflow_gui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=["tkinter", "unittest", "pydoc", "pytest", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="RebarFlow",
    console=False,
    icon=str(ROOT / "packaging" / "rebarflow.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="RebarFlow",
)
