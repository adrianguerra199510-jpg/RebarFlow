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

# Componentes que la aplicación no usa (ahorran ~16 MB comprimidos). La app dibuja con el rasterizador de
# Qt Widgets y solo carga PNG; si algo faltara, ``RebarFlow.exe --self-test`` lo detecta.
_UNUSED_FILES = {
    "opengl32sw.dll",        # OpenGL por software (solo para QOpenGL, que no se usa)
    "Qt6Network.dll", "Qt6Svg.dll", "qsvg.dll", "qsvgicon.dll",
    "qdirect2d.dll",         # plataforma Direct2D alternativa; se usa qwindows
    "qtiff.dll", "qwebp.dll",
}


def _keep(entry):
    dest = entry[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1]
    return not (name in _UNUSED_FILES or name.startswith("_avif") or "/translations/" in dest)


analysis.binaries = [entry for entry in analysis.binaries if _keep(entry)]
analysis.datas = [entry for entry in analysis.datas if _keep(entry)]
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
