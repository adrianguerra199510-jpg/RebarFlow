# RebarFlow

Generación automática de planillas de despiece de acero de refuerzo (Bar Bending Schedule, BBS) en Python.
Modela barras, formas de doblado y elementos estructurales; calcula longitudes de corte, pesos y desperdicios;
y exporta una planilla en Excel.

## Uso rápido

```bash
pip install -e ".[dev]"      # openpyxl (+ pytest)
python main.py               # escribe output/planilla_bbs.xlsx
python main.py -o mi.xlsx
pytest
```

```python
from core.element import ElementType, StructuralElement
from core.rebar import get_rebar
from core.shape_codes import Stirrup135, UBar
from engine.bbs_calculator import BBSCalculator
from exporters.excel_exporter import ExcelExporter

viga = StructuralElement("V-101", ElementType.BEAM, "Nivel 1", quantity=4)
n3, n6 = get_rebar("#3"), get_rebar("#6")
viga.add_group("A2", n6, UBar.with_standard_hooks(n6, a=5500), 2, "Refuerzo superior")
viga.add_group("E1", n3, Stirrup135(220, 420), 38, "Estribos")

resultado = BBSCalculator(stock_length_mm=12_000).calculate([viga])
ExcelExporter(project_name="Mi proyecto").export(resultado, "planilla.xlsx")
```

## Arquitectura

```
core/
  geometry.py      GeometryError y fórmulas de doblez (tangente, arco, deducción)
  rebar.py         Rebar, SteelGrade, ganchos estándar, radios de doblez y catálogo #3–#11
  shape_codes.py   ShapeCode + registro extensible; formas R, L, U y E (estribo 135°)
  element.py       RebarGroup (marca), StructuralElement (nivel, tipo, cantidad)
engine/
  bbs_calculator.py  líneas de planilla, pesos por diámetro, desperdicio y consolidado por nivel
exporters/
  excel_exporter.py  libro Excel (planilla agrupada por elemento + resumen)
main.py            ejemplo ejecutable
tests/             pytest
```

Los modelos son `dataclass` (sin dependencias extra); las validaciones viven en `__post_init__`.
La única dependencia de ejecución es `openpyxl`.

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
  lanza `ValueError` (debe dividirse con traslapes).
* El catálogo ASTM A615 cubre #3 (10M) a #11 (36M): el rango de 10 a 32 mm son #3 a #10. Se amplía con `register_rebar`.

> **Verifique la norma vigente.** Los valores de ganchos y diámetros de doblez están codificados de
> ACI 318-19 / NSR-10 y no se pudieron contrastar en línea al desarrollar este prototipo. Confírmelos
> contra la edición aplicable a su proyecto antes de emitir planos o pedidos.

## Agregar una forma nueva

Basta una subclase registrada; la validación de cotas positivas es automática y la forma aparece sola en el Excel
(las columnas de cotas se derivan de `dimensions()`):

```python
@register_shape
@dataclass(frozen=True)
class ZBar(ShapeCode):
    code: ClassVar[str] = "Z"
    name: ClassVar[str] = "Barra en Z"
    a: float
    b: float
    c: float

    def dimensions(self): return {"A": self.a, "B": self.b, "C": self.c}

    def cut_length(self, rebar: Rebar) -> CutLength:
        ...  # validar con _require_min y devolver CutLength(...)
```

## Alcance y limitaciones

* El Excel contiene valores calculados, no fórmulas, para que coincida siempre con el motor.
* Los estribos se modelan con ambos ganchos en una misma esquina y tangentes a ella; la diferencia con un
  detalle real (ganchos anidados) es de pocos milímetros.
* Formas incluidas: recta, L, U y estribo rectangular de 135°. Quedan fuera dobleces a ángulos distintos de 90°
  (la fórmula de deducción ya los admite), barras curvas y traslapes automáticos.
