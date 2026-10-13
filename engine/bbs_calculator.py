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
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import groupby

from core.coupler import COUPLER_LONG, COUPLER_ORDER, COUPLER_SHORT, coupler_count, coupler_text
from core.cutlength import BarPart, Supply
from core.element import RebarGroup, StructuralElement
from core.rebar import Rebar
from core.shape_codes import ShapeCode
from core.splice import parts_text, pieces_text
from engine.cutting_optimizer import CuttingPlan, compare_stock_lengths, optimize_cutting

DEFAULT_STOCK_LENGTH_MM = 12_000.0
_EPS = 1e-6


@dataclass(frozen=True)
class LinePart:
    """Sub-marca de una marca dividida en barras (``A1.1``, ``A1.2``…): barras idénticas que se cortan para ella.

    Lleva sus propias cantidades y pesos: los totales de la planilla salen de las sub-marcas, no de la marca que las reúne.
    ``shape`` es la barra recta que se dibuja, con la rosca de cada extremo.
    """

    mark: str
    part: BarPart
    shape: ShapeCode
    total_bars: int  # barras de esta sub-marca en todo el proyecto: por unidad x unidades x cantidad de elementos
    unit_weight_kg: float  # una barra
    total_length_m: float
    total_weight_kg: float

    @property
    def length_mm(self) -> float:
        return self.part.length_mm

    @property
    def count(self) -> int:
        """Barras de esta sub-marca por unidad de la marca."""
        return self.part.count

    @property
    def threads(self) -> tuple[str, ...]:
        return self.part.threads

    @property
    def thread_text(self) -> str:
        return self.part.thread_text


@dataclass(frozen=True)
class ScheduleLine:
    """Fila de la planilla: una marca dentro de un elemento.

    ``cut_length_mm`` es el acero que consume cada unidad (suma de las barras que la arman, con los traslapes si los
    hay), ``supply`` las barras que se cortan para cada una, con sus largos redondeados, y ``parts`` las sub-marcas en
    las que se divide si es más larga que la barra comercial (vacío si no se divide).
    """

    element: StructuralElement
    group: RebarGroup
    cut_length_mm: float  # longitud de corte redondeada
    total_bars: int  # barras por elemento x cantidad de elementos
    unit_weight_kg: float
    total_length_m: float
    total_weight_kg: float
    supply: Supply
    parts: tuple[LinePart, ...] = ()

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
        return self.group.cut.notes + self.supply.notes

    @property
    def hook_text(self) -> str:
        """Ganchos de la barra como ``"2 × 135° · 75"`` (ángulo · largo de la extensión en mm)."""
        return self.group.cut.hook_text

    @property
    def warnings(self) -> tuple[str, ...]:
        return self.group.cut.warnings + self.supply.warnings

    @property
    def couplers(self) -> tuple[str, ...]:
        """Rosca para acoplador de cada extremo de barra que la lleva, por unidad (``"short"`` / ``"long"``).

        Con la marca dividida en sub-marcas son las de todas sus barras, incluidas las de las uniones por acoplador.
        """
        return self.supply.threads if self.supply.parts else self.group.cut.couplers

    @property
    def coupler_text(self) -> str:
        """Roscas de cada unidad como ``"2 × rosca corta"`` (vacío si no lleva)."""
        return coupler_text(self.couplers)

    @property
    def parts_text(self) -> str:
        """Sub-marcas de la marca como ``"A1.1 ×1 · 12.00 m, A1.2 ×15 · 12.00 m"`` (vacío si no se divide)."""
        return parts_text(self.mark, (p.part for p in self.parts)) if self.parts else ""

    @property
    def pieces_text(self) -> str:
        """Barras que arman cada unidad, p. ej. ``"3 × 12.00 m + 4.32 m"`` (vacío si es una sola barra o un rollo)."""
        return "" if self.supply.coil else pieces_text(self.supply.pieces_mm)

    @property
    def joint_count(self) -> int:
        """Uniones entre barras de cada unidad (traslapes o couplers de unión)."""
        return 0 if self.supply.coil else len(self.supply.pieces_mm) - 1


@dataclass(frozen=True)
class CouplerCount:
    """Cantidad de extremos con rosca de un tipo en una barra (designación y grado) de todo el proyecto."""

    rebar: Rebar
    kind: str  # "short" o "long"
    count: int


@dataclass(frozen=True)
class ThreadRow:
    """Roscas y acopladores de una barra (designación y grado) en todo el proyecto.

    El acoplador es una sola pieza y junta dos extremos roscados: ``couplers`` sale de la cantidad de extremos.
    """

    rebar: Rebar
    long: int  # extremos con rosca larga
    short: int  # extremos con rosca corta

    @property
    def couplers(self) -> int:
        return coupler_count(self.long + self.short)


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
    group_label: str = "Nivel"  # cómo se llama el primer nivel de agrupación de los elementos

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
        """Extremos con rosca del proyecto por barra y tipo (barras x elementos x extremos roscados de cada barra)."""
        counts: dict[tuple[Rebar, str], int] = {}
        for line in self.lines:
            for kind in line.couplers:
                counts[(line.rebar, kind)] = counts.get((line.rebar, kind), 0) + line.total_bars
        order = lambda item: (item[0][0].bar_number, item[0][0].grade.fy_mpa, COUPLER_ORDER.index(item[0][1]))  # noqa: E731
        return tuple(CouplerCount(rebar, kind, count) for (rebar, kind), count in sorted(counts.items(), key=order))

    def thread_rows(self) -> tuple[ThreadRow, ...]:
        """Roscas largas y cortas y acopladores por barra (vacío si ninguna barra lleva rosca)."""
        counts = {(c.rebar, c.kind): c.count for c in self.coupler_counts()}
        rebars = sorted({c.rebar for c in self.coupler_counts()}, key=lambda r: (r.bar_number, r.grade.fy_mpa))
        return tuple(ThreadRow(r, counts.get((r, COUPLER_LONG), 0), counts.get((r, COUPLER_SHORT), 0)) for r in rebars)

    @property
    def levels(self) -> tuple[str, ...]:
        """Valores del primer nivel de agrupación en orden de aparición (``""`` para los elementos que no lo tienen)."""
        return tuple(dict.fromkeys(schedule.element.level for schedule in self.element_schedules))

    def level_title(self, level: str) -> str:
        """Rótulo de un grupo para las tablas: su nombre, o «Sin nivel» (según ``group_label``) si no tiene."""
        return level or f"Sin {self.group_label.lower()}"

    @property
    def has_level_groups(self) -> bool:
        """Verdadero si hay al menos dos grupos: solo entonces tiene sentido el consolidado por nivel."""
        return len(self.levels) >= 2

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


def round_supply(supply: Supply, stock_length_mm: float, step_mm: float) -> Supply:
    """``supply`` con el largo de cada barra redondeado hacia arriba al múltiplo de ``step_mm``.

    Las barras de una pieza armada con varias nunca pasan de la barra comercial. Una sola barra más larga que la
    comercial se deja tal cual para que el cálculo avise del error.
    """
    if supply.parts:
        return supply.with_part_lengths(tuple(min(round_up_to_step(p.length_mm, step_mm), stock_length_mm)
                                              for p in supply.parts))
    return replace(supply, pieces_mm=tuple(round_up_to_step(p, step_mm) for p in supply.pieces_mm))


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
        group_label: Nombre del primer nivel de agrupación de los elementos (``"Nivel"``, ``"Estructura"``…), para los
            rótulos del consolidado.
    """

    stock_length_mm: float = DEFAULT_STOCK_LENGTH_MM
    length_rounding_mm: float = 5.0
    reusable_remnant_mm: float = 1000.0
    group_label: str = "Nivel"

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
        for schedule in schedules:  # una sub-marca (A1.1) no puede llamarse como otra marca del mismo elemento
            marks = {line.mark for line in schedule.lines}
            for line in schedule.lines:
                clash = next((p.mark for p in line.parts if p.mark in marks), None)
                if clash:
                    raise ValueError(f"{schedule.element.name}: la sub-marca {clash} de la marca {line.mark} coincide con "
                                     f"otra marca del elemento; cambie el nombre de una de las dos.")

        lines = [line for schedule in schedules for line in schedule.lines]
        sort_key = lambda line: (line.rebar.bar_number, line.rebar.grade.fy_mpa)  # noqa: E731
        summaries = []
        for _, group in groupby(sorted(lines, key=sort_key), key=sort_key):
            group_lines = list(group)
            pieces: dict[float, int] = {}
            marks: dict[float, list[str]] = {}
            coil_length_m = 0.0
            for line in group_lines:
                if line.supply.coil:
                    coil_length_m += line.total_length_m
                    continue
                # una marca dividida aporta las barras de cada sub-marca; una sola barra, la suya
                cuts = ([(f"{line.element.name}/{part.mark}", part.length_mm, part.total_bars) for part in line.parts]
                        or [(f"{line.element.name}/{line.mark}", length, per_unit * line.total_bars)
                            for length, per_unit in Counter(line.supply.pieces_mm).items()])
                for name, length, bars in cuts:
                    pieces[length] = pieces.get(length, 0) + bars
                    if name not in marks.setdefault(length, []):
                        marks[length].append(name)
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
        return BBSResult(schedules, tuple(summaries), self.stock_length_mm, self.group_label)

    def _build_line(self, element: StructuralElement, group: RebarGroup) -> ScheduleLine:
        supply = round_supply(group.shape.supply(group.rebar, self.stock_length_mm), self.stock_length_mm,
                              self.length_rounding_mm)
        cut_mm = supply.material_mm
        longest = max(supply.pieces_mm)
        if not supply.coil and longest > self.stock_length_mm + _EPS:
            raise ValueError(
                f"{element.name} / marca {group.mark}: la barra mide {longest / 1000:.2f} m y excede la barra "
                f"comercial de {self.stock_length_mm / 1000:.2f} m; divídala en barras traslapadas."
            )
        total_bars = group.quantity * element.quantity
        unit_weight = group.rebar.mass_for_length(cut_mm / 1000.0)
        parts = tuple(
            LinePart(
                mark=sub_mark,
                part=part,
                shape=group.shape.part_shape(group.rebar, part),
                total_bars=part.count * total_bars,
                unit_weight_kg=group.rebar.mass_for_length(part.length_mm / 1000.0),
                total_length_m=part.count * total_bars * part.length_mm / 1000.0,
                total_weight_kg=part.count * total_bars * group.rebar.mass_for_length(part.length_mm / 1000.0),
            )
            for sub_mark, part in supply.sub_marks(group.mark)
        )
        return ScheduleLine(
            element=element,
            group=group,
            cut_length_mm=cut_mm,
            total_bars=total_bars,
            unit_weight_kg=unit_weight,
            total_length_m=total_bars * cut_mm / 1000.0,
            total_weight_kg=total_bars * unit_weight,
            supply=supply,
            parts=parts,
        )

    @staticmethod
    def _check_unique(elements: list[StructuralElement]) -> None:
        seen: set[tuple[str, str]] = set()
        for element in elements:
            key = (element.level, element.substructure, element.name)
            if key in seen:
                where = f" en {element.location!r}" if element.location else ""
                raise ValueError(f"El elemento {element.name!r} está repetido{where}.")
            seen.add(key)

