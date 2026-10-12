# RebarFlow

Planillas de despiece de acero de refuerzo (Bar Bending Schedule, BBS) en Python: interfaz gráfica de escritorio,
cálculo de longitudes de corte, pesos y desperdicios, y exportación a **Excel** y **PDF** con el esquema dibujado de
cada barra.

![Barras de un elemento](docs/ui_barras.png)

## Uso rápido

```bash
pip install -e ".[dev]"      # openpyxl, pillow, reportlab, PySide6 y pytest
python -m gui                # interfaz gráfica (también: rebarflow, o rebarflow ruta/proyecto.rebarflow)
python main.py               # ejemplo por consola: escribe output/planilla_bbs.xlsx y .pdf
pytest
```

En Linux, PySide6 necesita las librerías del sistema de Qt (`libegl1`, `libxkbcommon0`, `libdbus-1-3`, `libfontconfig1`).
Para usar solo el motor y los exportadores (sin interfaz) basta `pip install -e .`.

```python
from core.element import ElementType, StructuralElement
from core.rebar import get_rebar
from core.shape_codes import Stirrup135, UBar
from engine.bbs_calculator import BBSCalculator
from exporters.excel_exporter import ExcelExporter
from exporters.pdf_exporter import PdfExporter

viga = StructuralElement("V-101", ElementType.BEAM, "Nivel 1", quantity=4)
n3, n6 = get_rebar("#3"), get_rebar("#6")
viga.add_group("A2", n6, UBar.with_standard_hooks(n6, a=5500), 2, "Refuerzo superior")
viga.add_group("E1", n3, Stirrup135(220, 420), 38, "Estribos")

resultado = BBSCalculator(stock_length_mm=12_000).calculate([viga])
ExcelExporter(project_name="Mi proyecto").export(resultado, "planilla.xlsx")
PdfExporter(project_name="Mi proyecto", page_size="a4").export(resultado, "planilla.pdf")
```

## Interfaz gráfica

* **Árbol del proyecto** (nivel → elemento) a la izquierda; al elegir un elemento se listan sus barras.
* **Barras del elemento**: tabla con el dibujo de cada forma y sus cotas; doble clic o *Editar* abre el diálogo de barra.
* **Diálogo de barra** con vista previa en vivo: al elegir barra, grado, forma y cotas muestra el esquema, la longitud de
  corte (Σ cotas, ajuste por dobleces, extensiones), el peso y los errores geométricos; no permite aceptar una barra
  imposible, con marca repetida o más larga que la barra comercial. Los campos de cotas se generan solos para
  cualquier forma registrada.
* **Planilla del proyecto**: la planilla completa agrupada por elemento, tal como se exporta.
* **Resumen**: peso por diámetro, desperdicio de corte y consolidado por nivel.
* **Panel de detalle** a la derecha: dibujo grande y desglose del cálculo de la barra seleccionada.
* Guardar/abrir proyectos (`.rebarflow`, JSON legible), propiedades del proyecto (barra comercial, redondeo, papel) y
  exportación a Excel y PDF desde la barra de herramientas. Atajos: Ctrl+N/O/S, Ctrl+Shift+N (elemento), Ctrl+B (barra),
  Ctrl+E (Excel), Ctrl+P (PDF).

| Planilla del proyecto | Resumen |
|---|---|
| ![Planilla](docs/ui_planilla.png) | ![Resumen](docs/ui_resumen.png) |

| Diálogo de barra | Validación geométrica |
|---|---|
| ![Diálogo](docs/ui_dialogo_barra.png) | ![Error](docs/ui_dialogo_error.png) |

## Exportación con esquemas

Cada fila lleva el dibujo de su forma con las cotas, igual que las tablas de armaduras de Revit o de los programas de
despiece. El mismo renderizador (`exporters/shape_images.py`) alimenta Excel, PDF y la interfaz.

| Excel (`.xlsx`) | PDF |
|---|---|
| ![Excel](docs/export_excel.png) | ![PDF](docs/export_pdf.png) |

* **Excel**: hoja *Planilla BBS* (barras agrupadas por elemento con filas colapsables, subtotales, total general) y hoja
  *Resumen*. Las celdas contienen valores calculados, no fórmulas, para que coincidan siempre con el motor.
* **PDF** apaisado (carta o A4): una tabla por elemento con encabezado repetido entre páginas, pie *Página X de Y* y
  hoja de resumen.

## Arquitectura

```
core/
  geometry.py       GeometryError y fórmulas de doblez (tangente, arco, deducción)
  rebar.py          Rebar, SteelGrade, ganchos estándar, radios de doblez y catálogo #3–#11
  sketch.py         esquemas de forma independientes del medio de dibujo
  shape_codes.py    ShapeCode + registro extensible; formas R, L, U y E (estribo 135°)
  element.py        RebarGroup (marca), StructuralElement (nivel, tipo, cantidad)
  project.py        Project: elementos + parámetros de cálculo e impresión
  serialization.py  guardado y carga de proyectos en JSON
engine/
  bbs_calculator.py líneas de planilla, pesos por diámetro, desperdicio y consolidado por nivel
exporters/
  shape_images.py   PNG de cada forma con sus cotas (Pillow)
  excel_exporter.py libro Excel con esquemas (openpyxl)
  pdf_exporter.py   planilla en PDF con esquemas (reportlab)
gui/                interfaz PySide6: ventana principal, diálogos, tablas, estilo
sample_project.py   proyecto de ejemplo (cimentación + 2 niveles)
main.py             ejemplo por consola
tools/              capture_screenshots.py regenera las imágenes de docs/
tests/              pytest (la interfaz se prueba sin pantalla)
```

Los modelos son `dataclass` (sin dependencias extra); las validaciones viven en `__post_init__`. Las capas respetan el
sentido `core ← engine ← exporters ← gui`.

## Convenciones de cálculo

* Unidades: mm, kg y kg/m.
* **Cotas exteriores** (de fuera a fuera de la barra, como en ACI SP-66 / CRSI). La longitud de corte es

  `L = Σ cotas − Σ deducciones por doblez (+ extensiones)`, con deducción por doblez de ángulo θ,
  radio interior `r` y diámetro `d`: `2(r + d)·tan(θ/2) − θ·(r + d/2)`.
  Para 90° con `D = 6d` equivale a ≈ 2.5d.
* **Estribo 135°**: cotas `a × b` exteriores (sección − 2·recubrimiento). Longitud al eje con 4 lados rectos,
  3 dobleces de 90°, 2 de 135° y 2 extensiones: `2(a+b) + [(3π − 8)·R − 4d] + 2·ext`.
  Se verifica en los tests con un recorrido paso a paso de la barra.
* **Diámetros de doblez** (ACI 318-19 Tablas 25.3.1/25.3.2): barras principales #3–#8 → 6d, #9–#11 → 8d;
  estribos #3–#5 → 4d, #6–#8 → 6d.
* **Ganchos estándar**: 90° → 12d (principales); 135° de estribo → mayor de 6d y 75 mm; 180° → mayor de 4d y 65 mm.
  `LBar.with_standard_hook` y `UBar.with_standard_hooks` reproducen las cotas A/G de ACI SP-66 (#4 = 8", #6 = 12").
* **Redondeo**: la longitud de corte sube al múltiplo de 5 mm (configurable) y los pesos usan esa longitud.
* **Desperdicio**: por cada barra y grado se empaquetan las piezas en barras comerciales (12 m por defecto) con
  *First Fit Decreasing*; desperdicio = longitud comprada − longitud útil. Una barra mayor que la comercial
  lanza `ValueError` (la interfaz lo muestra como aviso; debe dividirse con traslapes).
* El catálogo ASTM A615 cubre #3 (10M) a #11 (36M): el rango de 10 a 32 mm son #3 a #10. Se amplía con `register_rebar`.

> **Verifique la norma vigente.** Los valores de ganchos y diámetros de doblez están codificados de
> ACI 318-19 / NSR-10 y no se pudieron contrastar en línea al desarrollar este prototipo. Confírmelos
> contra la edición aplicable a su proyecto antes de emitir planos o pedidos.

## Agregar una forma nueva

Basta una subclase registrada. La validación de cotas positivas es automática y la forma aparece sola en la interfaz
(campos del diálogo), en el Excel y en el PDF (columnas de cotas derivadas de `dimensions()`):

```python
@register_shape
@dataclass(frozen=True)
class ZBar(ShapeCode):
    code: ClassVar[str] = "Z"
    name: ClassVar[str] = "Barra en Z"
    field_labels: ClassVar[dict[str, str]] = {"a": "A · tramo 1", "b": "B · tramo 2", "c": "C · tramo 3"}
    a: float
    b: float
    c: float

    def dimensions(self): return {"A": self.a, "B": self.b, "C": self.c}

    def sketch(self) -> Sketch: ...   # opcional: sin él se dibuja una línea con las cotas

    def cut_length(self, rebar: Rebar) -> CutLength:
        ...  # validar con _require_min y devolver CutLength(...)
```

## Alcance y limitaciones

* Los estribos se modelan con ambos ganchos en una misma esquina y tangentes a ella; la diferencia con un
  detalle real (ganchos anidados) es de pocos milímetros.
* Los esquemas son proporcionales a las cotas con un tramo mínimo, para que un gancho corto siga siendo legible.
* Formas incluidas: recta, L, U y estribo rectangular de 135°. Quedan fuera dobleces a ángulos distintos de 90°
  (la fórmula de deducción ya los admite), barras curvas y traslapes automáticos.
