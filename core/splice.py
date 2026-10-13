"""Uniones entre barras comerciales: traslapes y couplers.

Cuando una pieza desarrollada mide más que la barra comercial (típicamente una espiral de columna, de decenas de metros)
hay que armarla con varias barras. Hay dos maneras de unirlas:

* **Traslape** (``lap``): cada unión monta una barra sobre la otra ``lap_mm``; el acero crece en un traslape por unión.
  Para el refuerzo en espiral ACI 318-19 (25.7.3.5) pide ``48·d`` y no menos de 300 mm en barra corrugada sin recubrir
  (valor citado de memoria: verifíquelo contra la norma de su proyecto y use ``lap_mm`` para fijar otro).
* **Coupler** (``coupler``): las barras se topan dentro de un acople mecánico; el largo no cambia y se cuenta un coupler
  por unión.

En ambos casos se corta todo lo posible en barras de largo comercial completo y la última barra lleva el resto.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

from core.geometry import GeometryError
from core.rebar import Rebar

JOINT_LAP = "lap"
JOINT_COUPLER = "coupler"
JOINT_CHOICES = ((JOINT_LAP, "Traslape"), (JOINT_COUPLER, "Coupler (acople mecánico)"))

LAP_DIAMETERS = 48.0  # ACI 318-19 25.7.3.5, barra corrugada sin recubrir (de memoria)
LAP_MINIMUM_MM = 300.0
_EPS = 1e-6
_MAX_PIECES = 100_000


def standard_lap_mm(rebar: Rebar) -> float:
    """Traslape de norma para refuerzo en espiral: ``48·d`` y no menos de 300 mm."""
    return max(LAP_DIAMETERS * rebar.diameter_mm, LAP_MINIMUM_MM)


def lap_pieces(total_mm: float, stock_mm: float, lap_mm: float) -> tuple[float, ...]:
    """Largo de cada barra para armar ``total_mm`` de pieza con traslapes de ``lap_mm`` y barras de ``stock_mm``.

    La suma de las barras es ``total_mm`` más un traslape por cada unión. Si cabe en una barra, es una sola pieza.
    """
    if total_mm <= stock_mm + _EPS:
        return (total_mm,)
    if lap_mm > stock_mm / 2.0 + _EPS:
        raise GeometryError(
            f"El traslape de {lap_mm:g} mm no puede pasar de la mitad de la barra comercial ({stock_mm / 2.0:g} mm)."
        )
    step = stock_mm - lap_mm  # avance útil de cada barra completa
    count = math.ceil((total_mm - lap_mm) / step - 1e-9)
    if count > _MAX_PIECES:
        raise GeometryError(f"La pieza necesitaría {count:,} barras; revise el largo de la barra comercial.")
    return (stock_mm,) * (count - 1) + (total_mm - (count - 1) * step,)


def coupler_pieces(total_mm: float, stock_mm: float) -> tuple[float, ...]:
    """Largo de cada barra para armar ``total_mm`` de pieza con barras de ``stock_mm`` unidas a tope con couplers."""
    if total_mm <= stock_mm + _EPS:
        return (total_mm,)
    count = math.ceil(total_mm / stock_mm - 1e-9)
    if count > _MAX_PIECES:
        raise GeometryError(f"La pieza necesitaría {count:,} barras; revise el largo de la barra comercial.")
    return (stock_mm,) * (count - 1) + (total_mm - (count - 1) * stock_mm,)


def pieces_text(pieces_mm: Iterable[float]) -> str:
    """Barras de una pieza como ``"3 × 12.00 m + 4.32 m"`` (vacío si es una sola barra)."""
    counts = Counter(round(p) for p in pieces_mm)
    if sum(counts.values()) < 2:
        return ""
    parts = [f"{n} × {length / 1000:.2f} m" if n > 1 else f"{length / 1000:.2f} m"
             for length, n in sorted(counts.items(), reverse=True)]
    return " + ".join(parts)
