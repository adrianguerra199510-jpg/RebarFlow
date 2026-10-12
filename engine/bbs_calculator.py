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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import groupby

from core.element import RebarGroup, StructuralElement
from core.rebar import Rebar
from core.shape_codes import ShapeCode

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
    def warnings(self) -> tuple[str, ...]:
        return self.group.cut.warnings


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
    """Consolidado de una barra (designación y grado) en todo el proyecto."""

    rebar: Rebar
    total_bars: int
    total_length_m: float
    total_weight_kg: float  # peso neto de la planilla
    stock_bars: int  # barras comerciales necesarias
    purchased_length_m: float  # stock_bars x longitud comercial

    @property
    def waste_length_m(self) -> float:
        return self.purchased_length_m - self.total_length_m

    @property
    def waste_weight_kg(self) -> float:
        return self.rebar.mass_for_length(self.waste_length_m)

    @property
    def waste_pct(self) -> float:
        """Desperdicio como fracción de la longitud comprada (0 a 1)."""
        return self.waste_length_m / self.purchased_length_m if self.purchased_length_m else 0.0

    @property
    def purchase_weight_kg(self) -> float:
        return self.rebar.mass_for_length(self.purchased_length_m)


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
    def dimension_labels(self) -> list[str]:
        """Rótulos de cota presentes en las formas usadas ("A", "B", "C"…), ordenados."""
        return dimension_labels(self.lines)

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
    """Barras comerciales necesarias para cortar ``pieces`` ({longitud mm: cantidad}).

    Empaquetado 1D por *First Fit Decreasing*: las piezas se ordenan de mayor a menor y cada
    una se coloca en la primera barra con espacio. Las piezas iguales se colocan en bloque,
    lo que equivale al algoritmo pieza a pieza pero escala a miles de estribos.
    """
    free: list[float] = []  # espacio libre de cada barra comercial abierta
    for length in sorted(pieces, reverse=True):
        remaining = pieces[length]
        for i, room in enumerate(free):
            if remaining == 0:
                break
            fit = min(remaining, int((room + _EPS) // length))
            if fit:
                free[i] = room - fit * length
                remaining -= fit
        per_bar = int((stock_length_mm + _EPS) // length)
        while remaining:
            fit = min(remaining, per_bar)
            free.append(stock_length_mm - fit * length)
            remaining -= fit
    return len(free)


@dataclass
class BBSCalculator:
    """Calcula la planilla de despiece de una lista de elementos.

    Attributes:
        stock_length_mm: Longitud de la barra comercial para el cálculo de desperdicios.
        length_rounding_mm: Paso de redondeo (hacia arriba) de la longitud de corte.
    """

    stock_length_mm: float = DEFAULT_STOCK_LENGTH_MM
    length_rounding_mm: float = 5.0

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
            for line in group_lines:
                pieces[line.cut_length_mm] = pieces.get(line.cut_length_mm, 0) + line.total_bars
            stock_bars = count_stock_bars(pieces, self.stock_length_mm)
            summaries.append(
                DiameterSummary(
                    rebar=group_lines[0].rebar,
                    total_bars=sum(line.total_bars for line in group_lines),
                    total_length_m=math.fsum(line.total_length_m for line in group_lines),
                    total_weight_kg=math.fsum(line.total_weight_kg for line in group_lines),
                    stock_bars=stock_bars,
                    purchased_length_m=stock_bars * self.stock_length_mm / 1000.0,
                )
            )
        return BBSResult(schedules, tuple(summaries), self.stock_length_mm)

    def _build_line(self, element: StructuralElement, group: RebarGroup) -> ScheduleLine:
        cut_mm = round_up_to_step(group.cut_length_mm, self.length_rounding_mm)
        if cut_mm > self.stock_length_mm + _EPS:
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

