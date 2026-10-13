"""Uniones entre barras comerciales: traslapes y acopladores.

Cuando una pieza desarrollada mide más que la barra comercial (una espiral de columna de decenas de metros, una barra
recta larga) hay que armarla con varias barras. Hay dos maneras de unirlas:

* **Traslape** (``lap``): cada unión monta una barra sobre la otra ``lap_mm``; el acero crece en un traslape por unión.
  Para el refuerzo en espiral ACI 318-19 (25.7.3.5) pide ``48·d`` y no menos de 300 mm en barra corrugada sin recubrir
  (valor citado de memoria: verifíquelo contra la norma de su proyecto y use ``lap_mm`` para fijar otro).
* **Acoplador** (``coupler``): las barras se topan dentro de un acople mecánico; el largo no cambia. El acoplador es una
  sola pieza; lo que cambia es la **rosca de cada extremo de barra**: lo normal es larga en un lado y corta en el otro
  (``long_short``: la barra que termina lleva la larga y la que sigue la corta), aunque también hay corta + corta y
  larga + larga.

En ambos casos se corta todo lo posible en barras de largo comercial completo y la última barra lleva el resto. Las
barras se agrupan en **sub-marcas** (``A1.1``, ``A1.2``…): las que son idénticas —mismo largo y mismas roscas— forman una
sola, con su cantidad por unidad.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

from core.coupler import COUPLER_LONG, COUPLER_SHORT, coupler_text
from core.cutlength import BarPart, Supply
from core.geometry import GeometryError
from core.rebar import Rebar

JOINT_LAP = "lap"
JOINT_COUPLER = "coupler"
JOINT_CHOICES = ((JOINT_LAP, "Traslape"), (JOINT_COUPLER, "Acoplador"))

#: Roscas de una unión por acoplador: (barra que termina, barra que sigue).
THREADS_LONG_SHORT = "long_short"
THREADS_SHORT_SHORT = "short_short"
THREADS_LONG_LONG = "long_long"
JOINT_THREAD_CHOICES = ((THREADS_LONG_SHORT, "Larga + corta"), (THREADS_SHORT_SHORT, "Corta + corta"),
                        (THREADS_LONG_LONG, "Larga + larga"))
_JOINT_THREADS = {THREADS_LONG_SHORT: (COUPLER_LONG, COUPLER_SHORT), THREADS_SHORT_SHORT: (COUPLER_SHORT, COUPLER_SHORT),
                  THREADS_LONG_LONG: (COUPLER_LONG, COUPLER_LONG)}
_JOINT_THREAD_TEXT = {THREADS_LONG_SHORT: "rosca larga en la barra que termina y corta en la que sigue",
                      THREADS_SHORT_SHORT: "rosca corta en las dos barras", THREADS_LONG_LONG: "rosca larga en las dos barras"}

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


def plan_parts(total_mm: float, stock_mm: float, *, joint: str, lap_mm: float = 0.0,
               threads: str = THREADS_LONG_SHORT, start_thread: str = "", end_thread: str = "") -> tuple[BarPart, ...]:
    """Sub-marcas en las que se divide una pieza de ``total_mm`` con barras de ``stock_mm``.

    ``start_thread`` y ``end_thread`` son las roscas propias de la pieza en sus dos puntas (las de una barra recta con
    rosca para otro acoplador); las de las uniones salen de ``threads``. Las barras idénticas se agrupan en una sub-marca:
    con un acoplador queda la primera, las intermedias (``count`` > 1) y la última.
    """
    if joint == JOINT_COUPLER:
        pieces = coupler_pieces(total_mm, stock_mm)
        ending, following = _JOINT_THREADS[threads] if len(pieces) > 1 else ("", "")
    else:
        pieces = lap_pieces(total_mm, stock_mm, lap_mm)
        ending = following = ""
    last = len(pieces) - 1
    grouped: dict[tuple[float, str, str], int] = {}
    for index, length in enumerate(pieces):
        bar = (length, start_thread if index == 0 else following, end_thread if index == last else ending)
        grouped[bar] = grouped.get(bar, 0) + 1
    return tuple(BarPart(length, count, start, end) for (length, start, end), count in grouped.items())


def joined_supply(rebar: Rebar, total_mm: float, stock_mm: float, *, joint: str, lap_mm: float | None = None,
                  threads: str = THREADS_LONG_SHORT, start_thread: str = "", end_thread: str = "") -> Supply:
    """Barras que arman una pieza de ``total_mm`` mayor que la barra comercial, con sus uniones, notas y avisos."""
    warnings: tuple[str, ...] = ()
    if joint == JOINT_COUPLER:
        parts = plan_parts(total_mm, stock_mm, joint=joint, threads=threads, start_thread=start_thread,
                           end_thread=end_thread)
        bars = sum(part.count for part in parts)
        notes = (f"Suministro: {bars} barras unidas a tope con {bars - 1} acopladores "
                 f"({_JOINT_THREAD_TEXT[threads]})",)
    else:
        standard = standard_lap_mm(rebar)
        lap = standard if lap_mm is None else lap_mm
        parts = plan_parts(total_mm, stock_mm, joint=joint, lap_mm=lap, start_thread=start_thread, end_thread=end_thread)
        bars = sum(part.count for part in parts)
        if lap < standard - _EPS:
            warnings = (f"Traslape de {lap:.0f} mm menor que el de norma para espirales "
                        f"(48·d, mín. 300 mm = {standard:.0f} mm; ACI 318)",)
        notes = (f"Suministro: {bars} barras con {bars - 1} traslapes de {lap:.0f} mm "
                 f"(el acero crece {(bars - 1) * lap / 1000:.2f} m por unidad)",)
    return Supply.from_parts(parts, joint=joint, notes=notes, warnings=warnings)


def parts_text(mark: str, parts: Iterable[BarPart]) -> str:
    """Sub-marcas en texto: ``"A1.1 ×1 · 12.00 m, A1.2 ×15 · 12.00 m"`` (con su rosca si la llevan)."""
    texts = []
    for k, part in enumerate(parts, start=1):
        text = f"{mark}.{k} ×{part.count} · {part.length_mm / 1000:.2f} m"
        if part.thread_text:
            text += f" ({part.thread_text})"
        texts.append(text)
    return ", ".join(texts)


__all__ = ["JOINT_CHOICES", "JOINT_COUPLER", "JOINT_LAP", "JOINT_THREAD_CHOICES", "THREADS_LONG_LONG",
           "THREADS_LONG_SHORT", "THREADS_SHORT_SHORT", "coupler_pieces", "coupler_text", "joined_supply", "lap_pieces",
           "parts_text", "pieces_text", "plan_parts", "standard_lap_mm"]
