"""Lanzador del ejecutable de Windows (PyInstaller): abre la interfaz gráfica de RebarFlow.

``RebarFlow.exe``                      abre la aplicación (opcionalmente con un ``.rebarflow`` como argumento)
``RebarFlow.exe --self-test CARPETA``  comprobación sin intervención del ejecutable ya compilado: abre la
                                       ventana con el proyecto de ejemplo, exporta Excel, PDF y proyecto,
                                       guarda una captura y escribe ``self-test.txt`` con el resultado.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def self_test(folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    report: list[str] = []
    try:
        from gui.app import create_application
        from gui.main_window import MainWindow
        from sample_project import build_project

        app = create_application([])
        window = MainWindow(build_project())
        window.show()
        app.processEvents()
        window.grab().save(str(folder / "ventana.png"))
        window.write_excel(folder / "planilla.xlsx")
        window.write_pdf(folder / "planilla.pdf")
        window.write_project(folder / "proyecto.rebarflow")
        report.append(f"peso neto: {window.result.total_weight_kg:.2f} kg")
        report.append(f"plan de corte: {sum(s.stock_bars for s in window.result.diameter_summaries)} barras comerciales")
        # Catálogo de formas: una barra de cada plantilla (comprueba que todas se empaquetaron y se dibujan).
        window.open_catalog()
        app.processEvents()
        window.grab().save(str(folder / "catalogo.png"))
        window.write_excel(folder / "catalogo.xlsx")
        window.write_pdf(folder / "catalogo.pdf")
        report.append(f"catálogo: {len(window.result.lines)} marcas, {window.result.total_weight_kg:.2f} kg")
        for name in ("ventana.png", "planilla.xlsx", "planilla.pdf", "proyecto.rebarflow",
                     "catalogo.png", "catalogo.xlsx", "catalogo.pdf"):
            size = (folder / name).stat().st_size
            report.append(f"{name}: {size} bytes")
            if size == 0:
                raise RuntimeError(f"{name} está vacío")
        report.append("SELF-TEST OK")
        code = 0
    except Exception:  # noqa: BLE001 - se informa cualquier fallo del empaquetado
        report.append("SELF-TEST FALLÓ")
        report.append(traceback.format_exc())
        code = 1
    (folder / "self-test.txt").write_text("\n".join(report), encoding="utf-8")
    if sys.stdout is not None:  # el ejecutable sin consola no tiene stdout
        print("\n".join(report))
    return code


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        return self_test(Path(sys.argv[2] if len(sys.argv) > 2 else "self-test"))
    from gui.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
