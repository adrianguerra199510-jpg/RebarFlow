"""Contenido del plan de corte listo para mostrar (filas, títulos y comparativo de longitudes comerciales).

Excel, PDF e interfaz leen de aquí, de modo que los tres muestran exactamente lo mismo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.bbs_calculator import BBSResult, DiameterSummary
from engine.cutting_optimizer import CutPattern

#: Longitudes comerciales habituales que se comparan para recomendar la de menor desperdicio.
CANDIDATE_STOCK_LENGTHS_MM = (6000.0, 9000.0, 12000.0)

STRATEGY_NAMES = {
    "lp": "lineal (Gilmore–Gomory)",
    "shp": "secuencial",
    "bfd": "Best Fit",
    "ffd": "First Fit",
}
_MAX_MARKS = 4


@dataclass(frozen=True)
class PlanRow:
    """Un paso de la secuencia de corte."""

    step: int
    bars_text: str  # "1–24": barras numeradas que se cortan así
    count: int
    pattern: CutPattern
    cuts_text: str  # "3 × 3,900 + 1 × 1,430" (mm)
    marks_text: str  # marcas ("elemento/marca") a las que sirven las piezas
    remnant_mm: float
    remnant_use: str  # "Reutilizable", "Desperdicio" o "—"


def plan_rows(summary: DiameterSummary) -> list[PlanRow]:
    """Secuencia de corte de un diámetro, un paso por patrón."""
    rows = []
    for number, step in enumerate(summary.plan.sequence(), start=1):
        pattern = step.pattern
        grouped = pattern.grouped()
        marks: list[str] = []
        for length, _ in grouped:
            marks += [name for name in summary.marks_for(length) if name not in marks]
        marks_text = ", ".join(marks[:_MAX_MARKS]) + (f" (+{len(marks) - _MAX_MARKS})" if len(marks) > _MAX_MARKS else "")
        remnant = pattern.remnant_mm
        threshold = summary.reusable_remnant_mm
        if remnant < 1e-6:
            use = "—"
        elif threshold > 0 and remnant >= threshold - 1e-6:
            use = "Reutilizable"
        else:
            use = "Desperdicio"
        rows.append(PlanRow(
            step=number,
            bars_text=step.bars_text,
            count=pattern.count,
            pattern=pattern,
            cuts_text=" + ".join(f"{n} × {length:,.0f}" for length, n in grouped),
            marks_text=marks_text,
            remnant_mm=remnant,
            remnant_use=use,
        ))
    return rows


def plan_title(summary: DiameterSummary) -> str:
    """Encabezado de la sección de un diámetro: barras, sobrante y estrategia."""
    plan = summary.plan
    details = []
    if plan.stock_bars:
        quality = "óptimo" if plan.is_optimal else f"mínimo teórico {plan.lower_bound_bars} barras"
        details += [
            f"{plan.stock_bars} barras de {plan.stock_length_mm / 1000:.2f} m",
            f"sobrante {plan.remnant_pct:.1%} ({plan.remnant_length_mm / 1000:,.1f} m)",
            f"plan {STRATEGY_NAMES.get(plan.strategy, plan.strategy)} · {quality}",
        ]
    if summary.coil_length_m:
        details.append(f"{summary.coil_length_m:,.1f} m en rollo (espirales), sin retales")
    head = f"{summary.rebar.designation} · {summary.rebar.grade.name}"
    return f"{head}  —  {' · '.join(details)}" if details else head


@dataclass(frozen=True)
class StockOption:
    stock_length_mm: float
    bars: int
    waste_pct: float
    purchased_m: float


@dataclass(frozen=True)
class StockComparison:
    """Barras y sobrante de un diámetro con cada longitud comercial candidata, y la recomendada."""

    summary: DiameterSummary
    options: tuple[StockOption, ...]
    best_mm: float | None


def stock_comparison(result: BBSResult, lengths: Sequence[float] = CANDIDATE_STOCK_LENGTHS_MM) -> list[StockComparison]:
    """Compara las longitudes comerciales candidatas (más la del proyecto) para cada diámetro.

    La recomendada es la que menos acero compra; a igual compra, la más larga. Solo se consideran las longitudes en las
    que caben todas las piezas.
    """
    candidates = sorted({*lengths, result.stock_length_mm})
    comparisons = []
    for summary in result.diameter_summaries:
        if not summary.pieces:
            continue
        plans = summary.compare_stock_lengths(candidates)
        options = tuple(
            StockOption(length, plan.stock_bars, plan.remnant_pct, plan.purchased_length_mm / 1000.0)
            for length, plan in sorted(plans.items())
        )
        best = min(options, key=lambda o: (round(o.purchased_m, 6), -o.stock_length_mm), default=None)
        comparisons.append(StockComparison(summary, options, best.stock_length_mm if best else None))
    return comparisons
