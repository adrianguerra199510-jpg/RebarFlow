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

        app = create_application([], dark=False)
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
        # Obra sin niveles con encabezado y logo (comprueba Pillow y los exportadores con imagen en el ejecutable).
        from io import BytesIO

        from PIL import Image

        from exporters.logo import normalize_logo

        window.open_bridge()
        logo = BytesIO()
        Image.new("RGB", (320, 100), (31, 56, 100)).save(logo, format="PNG")
        window.project.logo_png = normalize_logo(logo.getvalue())
        window.refresh()
        window.write_excel(folder / "puente.xlsx")
        window.write_pdf(folder / "puente.pdf")
        report.append(f"puente sin niveles: {len(window.result.lines)} marcas, grupos {list(window.result.levels)}")
        # Varios proyectos: la cinta tiene una pestaña por proyecto abierto y un clic en ella cambia de proyecto.
        report.append(f"proyectos abiertos: {window.project_bar.titles()}")
        window.project_bar.tabs.setCurrentIndex(1)
        app.processEvents()
        if window.project.name != "Catálogo de formas" or len(window.sessions) != 3:
            raise RuntimeError("la cinta de proyectos no cambió de proyecto")
        window.duplicate_project()
        if len(window.sessions) != 4 or not window.project.name.endswith("(copia)"):
            raise RuntimeError("no se pudo duplicar el proyecto")
        window.session.modified = False
        window.close_project()
        window.select_project(1)
        app.processEvents()
        split = [line for line in window.result.lines if line.parts]
        report.append("marcas divididas en sub-marcas: " + "; ".join(f"{line.mark}: {line.parts_text}" for line in split))
        if not split or not window.result.thread_rows():
            raise RuntimeError("las uniones por acoplador no generaron sub-marcas")
        # Modo nocturno (sin guardar la preferencia): el botón de la esquina superior derecha cambia toda la interfaz.
        from gui import style

        previous = style.preferred_dark()  # el clic recuerda el tema: se restituye para no tocar la preferencia del usuario
        window.theme_button.click()
        app.processEvents()
        window.grab().save(str(folder / "nocturno.png"))
        if not style.current().dark:
            raise RuntimeError("el botón de tema no activó el modo nocturno")
        report.append(f"modo nocturno: {window.act_theme.text()!r}")
        window.set_dark_mode(False, remember=False)
        style.remember_dark(previous)
        for name in ("ventana.png", "planilla.xlsx", "planilla.pdf", "proyecto.rebarflow",
                     "catalogo.png", "catalogo.xlsx", "catalogo.pdf", "puente.xlsx", "puente.pdf", "nocturno.png"):
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
