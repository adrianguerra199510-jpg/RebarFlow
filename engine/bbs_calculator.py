"""Cálculo y agregación de la planilla de despiece (Bar Bending Schedule).

Flujo: ``BBSCalculator.calculate(elementos)`` → :class:`BBSResult` con

* una :class:`ScheduleLine` por marca (cantidades, longitudes y pesos),
* subtotales por elemento (:class:`ElementSchedule`),
* un :class:`DiameterSummary` por barra y grado con peso neto, barras comerciales a comprar
  y desperdicio de corte,
* totales por nivel y diámetro.

Las longitudes de corte se redondean **hacia arriba** al múltiplo de ``length_rounding_mm``
(5 mm por defecto) y los pesos se calculan con la longitud redondeada, que es la que se corta.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import groupby

from core.coupler import COUPLER_ORDER
from core.element import RebarGroup, StructuralElement
from core.rebar import Rebar
from core.shape_codes import ShapeCode
from engine.cutting_optimizer import CuttingPlan, compare_stock_lengths, optimize_cutting

DEFAULT_STOCK_LENGTH_MM = 12_000.0
_EPS = 1e-6


@dataclass(frozen=True)
class ScheduleLine:
    """Fila de la planilla: una marca dentro de un elemento."""

    element: StructuralElement
    group: RebarGroup
    cut_length_mm: float  # longitud de corte redondeada
    total_bars: int  # barras por elemento x cantidad de elementos
    unit_weight_kg: float
    total_length_m: float
    total_weight_kg: float

    @property
    def mark(self) -> str:
        return self.group.mark

    @property
    def rebar(self) -> Rebar:
        return self.group.rebar

    @property
    def shape(self) -> ShapeCode:
        return self.group.shape

    @property
    def level(self) -> str:
        return self.element.level

    @property
    def notes(self) -> tuple[str, ...]:
        return self.group.cut.notes

    @property
    def hook_text(self) -> str:
        """Ganchos de la barra como ``"2 × 135° · 75"`` (ángulo · largo de la extensión en mm)."""
        return self.group.cut.hook_text

    @property
    def warnings(self) -> tuple[str, ...]:
        return self.group.cut.warnings

    @property
    def couplers(self) -> tuple[str, ...]:
        """Tipo de coupler de cada extremo que lo lleva, por barra (``"short"`` o ``"long"``)."""
        return self.group.cut.couplers

    @property
    def coupler_text(self) -> str:
        """Couplers de cada barra como ``"2 × rosca corta"`` (vacío si no lleva)."""
        return self.group.cut.coupler_text


@dataclass(frozen=True)
class CouplerCount:
    """Cantidad de couplers de un tipo en una barra (designación y grado) de todo el proyecto."""

    rebar: Rebar
    kind: str  # "short" o "long"
    count: int


@dataclass(frozen=True)
class ElementSchedule:
    """Filas y subtotales de un elemento estructural."""

    element: StructuralElement
    lines: tuple[ScheduleLine, ...]

    @property
    def total_weight_kg(self) -> float:
        return math.fsum(line.total_weight_kg for line in self.lines)

    @property
    def total_length_m(self) -> float:
        return math.fsum(line.total_length_m for line in self.lines)


@dataclass(frozen=True)
class DiameterSummary:
    """Consolidado de una barra (designación y grado) en todo el proyecto, con su plan de corte.

    Las piezas que salen de barras comerciales siguen ``plan`` (secuencia de corte optimizada); las de rollo
    (espirales) se suministran a su longitud y no generan retales.
    """

    rebar: Rebar
    total_bars: int
    total_length_m: float
    total_weight_kg: float  # peso neto de la planilla
    plan: CuttingPlan  # plan de corte de las piezas que salen de barras comerciales
    pieces: Mapping[float, int] = field(default_factory=dict)  # largo de corte (mm) → cantidad, solo piezas cortadas
    length_marks: Mapping[float, tuple[str, ...]] = field(default_factory=dict)  # largo → "elemento/marca"
    coil_length_m: float = 0.0  # longitud suministrada en rollo
    reusable_remnant_mm: float = 0.0  # un retal de al menos esta longitud se considera reutilizable

    @property
    def stock_bars(self) -> int:
        """Barras comerciales necesarias."""
        return self.plan.stock_bars

    @property
    def purchased_length_m(self) -> float:
        return self.plan.purchased_length_mm / 1000.0 + self.coil_length_m

    @property
    def waste_length_m(self) -> float:
        """Sobrante total de las barras comerciales (retales reutilizables más desperdicio)."""
        return self.plan.remnant_length_mm / 1000.0

    @property
    def reusable_length_m(self) -> float:
        return self.plan.remnants(self.reusable_remnant_mm)[0] / 1000.0

    @property
    def scrap_length_m(self) -> float:
        """Desperdicio definitivo: retales demasiado cortos para reutilizar."""
        return self.plan.remnants(self.reusable_remnant_mm)[1] / 1000.0

    @property
    def waste_weight_kg(self) -> float:
        return self.rebar.mass_for_length(self.waste_length_m)

    @property
    def reusable_weight_kg(self) -> float:
        return self.rebar.mass_for_length(self.reusable_length_m)

    @property
    def scrap_weight_kg(self) -> float:
        return self.rebar.mass_for_length(self.scrap_length_m)

    @property
    def waste_pct(self) -> float:
        """Sobrante como fracción de la longitud comprada (0 a 1)."""
        return self.waste_length_m / self.purchased_length_m if self.purchased_length_m else 0.0

    @property
    def scrap_pct(self) -> float:
        return self.scrap_length_m / self.purchased_length_m if self.purchased_length_m else 0.0

    @property
    def purchase_weight_kg(self) -> float:
        return self.rebar.mass_for_length(self.purchased_length_m)

    def marks_for(self, length_mm: float) -> tuple[str, ...]:
        """Marcas ("elemento/marca") que usan piezas de ese largo de corte (tolerancia de 1 mm)."""
        if length_mm in self.length_marks:
            return self.length_marks[length_mm]
        near = [key for key in self.length_marks if abs(key - length_mm) <= 1.0]
        return self.length_marks[min(near, key=lambda k: abs(k - length_mm))] if near else ()

    def compare_stock_lengths(self, lengths: Sequence[float]) -> dict[float, CuttingPlan]:
        """Plan de corte para cada longitud comercial candidata en la que quepan todas las piezas."""
        return compare_stock_lengths(self.pieces, lengths)


@dataclass(frozen=True)
class BBSResult:
    """Resultado completo del cálculo de la planilla."""

    element_schedules: tuple[ElementSchedule, ...]
    diameter_summaries: tuple[DiameterSummary, ...]
    stock_length_mm: float

    @property
    def lines(self) -> tuple[ScheduleLine, ...]:
        return tuple(line for schedule in self.element_schedules for line in schedule.lines)

    @property
    def total_length_m(self) -> float:
        return math.fsum(s.total_length_m for s in self.diameter_summaries)

    @property
    def total_weight_kg(self) -> float:
        return math.fsum(s.total_weight_kg for s in self.diameter_summaries)

    @property
    def total_waste_weight_kg(self) -> float:
        return math.fsum(s.waste_weight_kg for s in self.diameter_summaries)

    @property
    def total_purchase_weight_kg(self) -> float:
        return math.fsum(s.purchase_weight_kg for s in self.diameter_summaries)

    @property
    def total_waste_pct(self) -> float:
        purchased = self.total_purchase_weight_kg
        return self.total_waste_weight_kg / purchased if purchased else 0.0

    @property
    def total_reusable_weight_kg(self) -> float:
        return math.fsum(s.reusable_weight_kg for s in self.diameter_summaries)

    @property
    def total_scrap_weight_kg(self) -> float:
        return math.fsum(s.scrap_weight_kg for s in self.diameter_summaries)

    @property
    def total_scrap_pct(self) -> float:
        purchased = self.total_purchase_weight_kg
        return self.total_scrap_weight_kg / purchased if purchased else 0.0

    @property
    def dimension_labels(self) -> list[str]:
        """Rótulos de cota presentes en las formas usadas ("A", "B", "C"…), ordenados."""
        return dimension_labels(self.lines)

    @property
    def warnings(self) -> tuple[tuple[str, str, str], ...]:
        """Avisos de norma de la planilla como ``(elemento, marca, texto)``."""
        return tuple((line.element.name, line.mark, text) for line in self.lines for text in line.warnings)

    def coupler_counts(self) -> tuple[CouplerCount, ...]:
        """Couplers del proyecto por barra y tipo (barras por elemento x cantidad de elementos x extremos con coupler)."""
        counts: dict[tuple[Rebar, str], int] = {}
        for line in self.lines:
            for kind in line.couplers:
                counts[(line.rebar, kind)] = counts.get((line.rebar, kind), 0) + line.total_bars
        order = lambda item: (item[0][0].bar_number, item[0][0].grade.fy_mpa, COUPLER_ORDER.index(item[0][1]))  # noqa: E731
        return tuple(CouplerCount(rebar, kind, count) for (rebar, kind), count in sorted(counts.items(), key=order))

    @property
    def levels(self) -> tuple[str, ...]:
        """Niveles en orden de aparición."""
        return tuple(dict.fromkeys(schedule.element.level for schedule in self.element_schedules))

    def weight_by_level_and_diameter(self) -> dict[str, dict[Rebar, float]]:
        """Peso neto (kg) por nivel y barra."""
        table: dict[str, dict[Rebar, float]] = {level: {} for level in self.levels}
        for line in self.lines:
            row = table[line.level]
            row[line.rebar] = row.get(line.rebar, 0.0) + line.total_weight_kg
        return table


def dimension_labels(lines: Iterable[ScheduleLine]) -> list[str]:
    """Rótulos de cota ("A", "B"…) usados por las formas de ``lines``, en orden alfabético."""
    labels = {label for line in lines for label in line.shape.dimensions()}
    return sorted(labels, key=lambda s: (len(s), s)) or ["A"]


def round_up_to_step(value: float, step: float) -> float:
    """Redondea ``value`` hacia arriba al múltiplo de ``step`` (sin redondeo si ``step`` ≤ 0)."""
    if step <= 0:
        return value
    return math.ceil(value / step - 1e-9) * step


def count_stock_bars(pieces: Mapping[float, int], stock_length_mm: float) -> int:
    """Barras comerciales necesarias para cortar ``pieces`` ({longitud mm: cantidad}) con el plan optimizado."""
    return optimize_cutting(pieces, stock_length_mm).stock_bars


@dataclass
class BBSCalculator:
    """Calcula la planilla de despiece de una lista de elementos.

    Attributes:
        stock_length_mm: Longitud de la barra comercial para el plan de corte y los desperdicios.
        length_rounding_mm: Paso de redondeo (hacia arriba) de la longitud de corte.
        reusable_remnant_mm: Un retal de al menos esta longitud se considera reutilizable y no desperdicio
            (0 = ningún retal se reutiliza).
    """

    stock_length_mm: float = DEFAULT_STOCK_LENGTH_MM
    length_rounding_mm: float = 5.0
    reusable_remnant_mm: float = 1000.0

    def __post_init__(self) -> None:
        if self.stock_length_mm <= 0:
            raise ValueError("La longitud de la barra comercial debe ser positiva.")

    def calculate(self, elements: Iterable[StructuralElement]) -> BBSResult:
        elements = list(elements)
        self._check_unique(elements)

        schedules = tuple(
            ElementSchedule(element, tuple(self._build_line(element, g) for g in element.groups))
            for element in elements
        )

        lines = [line for schedule in schedules for line in schedule.lines]
        sort_key = lambda line: (line.rebar.bar_number, line.rebar.grade.fy_mpa)  # noqa: E731
        summaries = []
        for _, group in groupby(sorted(lines, key=sort_key), key=sort_key):
            group_lines = list(group)
            pieces: dict[float, int] = {}
            marks: dict[float, list[str]] = {}
            coil_length_m = 0.0
            for line in group_lines:
                if line.shape.from_coil:
                    coil_length_m += line.total_length_m
                    continue
                pieces[line.cut_length_mm] = pieces.get(line.cut_length_mm, 0) + line.total_bars
                name = f"{line.element.name}/{line.mark}"
                if name not in marks.setdefault(line.cut_length_mm, []):
                    marks[line.cut_length_mm].append(name)
            summaries.append(
                DiameterSummary(
                    rebar=group_lines[0].rebar,
                    total_bars=sum(line.total_bars for line in group_lines),
                    total_length_m=math.fsum(line.total_length_m for line in group_lines),
                    total_weight_kg=math.fsum(line.total_weight_kg for line in group_lines),
                    plan=optimize_cutting(pieces, self.stock_length_mm),
                    pieces=pieces,
                    length_marks={length: tuple(names) for length, names in marks.items()},
                    coil_length_m=coil_length_m,
                    reusable_remnant_mm=self.reusable_remnant_mm,
                )
            )
        return BBSResult(schedules, tuple(summaries), self.stock_length_mm)

    def _build_line(self, element: StructuralElement, group: RebarGroup) -> ScheduleLine:
        cut_mm = round_up_to_step(group.cut_length_mm, self.length_rounding_mm)
        if cut_mm > self.stock_length_mm + _EPS and not group.shape.from_coil:
            raise ValueError(
                f"{element.name} / marca {group.mark}: la barra mide {cut_mm / 1000:.2f} m y excede la barra "
                f"comercial de {self.stock_length_mm / 1000:.2f} m; divídala en barras traslapadas."
            )
        total_bars = group.quantity * element.quantity
        unit_weight = group.rebar.mass_for_length(cut_mm / 1000.0)
        return ScheduleLine(
            element=element,
            group=group,
            cut_length_mm=cut_mm,
            total_bars=total_bars,
            unit_weight_kg=unit_weight,
            total_length_m=total_bars * cut_mm / 1000.0,
            total_weight_kg=total_bars * unit_weight,
        )

    @staticmethod
    def _check_unique(elements: list[StructuralElement]) -> None:
        seen: set[tuple[str, str]] = set()
        for element in elements:
            key = (element.level, element.name)
            if key in seen:
                raise ValueError(f"El elemento {element.name!r} está repetido en {element.level!r}.")
            seen.add(key)

