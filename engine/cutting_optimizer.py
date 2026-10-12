"""Optimización del corte de barras comerciales: plan y secuencia de corte con el menor desperdicio.

Problema (cutting stock 1D): dadas las piezas necesarias de cada longitud, cortarlas de barras comerciales de
longitud fija usando las menos barras posibles. Se prueban cuatro estrategias y se conserva la mejor:

* **FFD** (*First Fit Decreasing*): cada pieza, de mayor a menor, va a la primera barra con espacio.
* **BFD** (*Best Fit Decreasing*): igual, pero a la barra donde queda menos sobrante.
* **LP** (Gilmore–Gomory): se resuelve la relajación lineal del problema por generación de columnas (símplex
  revisado en Python puro; cada patrón nuevo sale de una mochila con los precios duales), se redondean hacia
  abajo las repeticiones de cada patrón y las piezas que sobran se reparten con BFD. Suele quedar a pocas barras
  del óptimo. Tiene un presupuesto de tiempo, tras el cual usa lo avanzado hasta ese momento.
* **SHP** (procedimiento heurístico secuencial): en cada paso se halla, con una mochila exacta (subset-sum con
  cotas, resuelto con bitsets), el patrón que más llena una barra y se acepta si su sobrante es menor que una
  tolerancia, repitiéndolo todas las veces que alcancen las piezas; lo que queda se empaqueta con BFD. Se prueban
  varias tolerancias (0 %, 0.25 %, … de la barra). Trabaja con cantidades, así que escala a miles de estribos.

Después se intenta eliminar la barra más vacía repartiendo sus piezas entre las demás. Se elige el plan con
menos barras; a igual número, el de menos patrones distintos (más simple de ejecutar) y el que concentra el
sobrante en menos retales grandes (más fáciles de reutilizar).

El resultado, :class:`CuttingPlan`, es una **secuencia de corte**: lista de patrones numerados (cuántas barras se
cortan igual y en qué orden salen las piezas de cada barra) con el retal de cada uno.

Las longitudes se tratan en una cuadrícula entera (5 mm si todas las piezas son múltiplos de 5, si no 1 mm).
"""

from __future__ import annotations

import math
import time
from bisect import bisect_left, insort
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache

_EPS = 1e-6
STRATEGIES = ("lp", "shp", "bfd", "ffd")
LP_BUDGET_S = 2.5  # tiempo máximo de la generación de columnas por conjunto de piezas
LP_GRID_CELLS = 1200  # celdas de la cuadrícula del precio (más celdas = patrones más ajustados, pero más lento)
SHP_TOLERANCES = (0.0, 0.0025, 0.005, 0.01, 0.02, 0.05)  # sobrante máximo aceptado por patrón (fracción de la barra)


@dataclass(frozen=True)
class CutPattern:
    """Forma de cortar una barra comercial; se repite en ``count`` barras idénticas."""

    cuts: tuple[float, ...]  # largo de cada pieza, de mayor a menor (orden de corte)
    count: int
    stock_length_mm: float

    @property
    def used_mm(self) -> float:
        return sum(self.cuts)

    @property
    def remnant_mm(self) -> float:
        return self.stock_length_mm - self.used_mm

    def grouped(self) -> tuple[tuple[float, int], ...]:
        """Cortes agrupados por largo: ``((3900, 3), (1430, 1))``."""
        counts = Counter(self.cuts)
        return tuple((length, counts[length]) for length in sorted(counts, reverse=True))


@dataclass(frozen=True)
class CutStep:
    """Paso de la secuencia: las barras ``first_bar``…``last_bar`` (numeradas desde 1) se cortan con ``pattern``."""

    first_bar: int
    last_bar: int
    pattern: CutPattern

    @property
    def bars_text(self) -> str:
        return str(self.first_bar) if self.first_bar == self.last_bar else f"{self.first_bar}–{self.last_bar}"


@dataclass(frozen=True)
class CuttingPlan:
    """Plan de corte de un conjunto de piezas: patrones en orden de ejecución y datos de calidad."""

    stock_length_mm: float
    patterns: tuple[CutPattern, ...]
    strategy: str
    lower_bound_bars: int

    @property
    def stock_bars(self) -> int:
        return sum(p.count for p in self.patterns)

    @property
    def purchased_length_mm(self) -> float:
        return self.stock_bars * self.stock_length_mm

    @property
    def used_length_mm(self) -> float:
        return sum(p.used_mm * p.count for p in self.patterns)

    @property
    def remnant_length_mm(self) -> float:
        return sum(p.remnant_mm * p.count for p in self.patterns)

    @property
    def remnant_pct(self) -> float:
        """Sobrante como fracción de la longitud comprada (0 a 1)."""
        purchased = self.purchased_length_mm
        return self.remnant_length_mm / purchased if purchased else 0.0

    @property
    def is_optimal(self) -> bool:
        """Verdadero si el número de barras iguala la cota inferior ``⌈Σ piezas / barra⌉``."""
        return self.stock_bars == self.lower_bound_bars

    def sequence(self) -> tuple[CutStep, ...]:
        """Patrones numerados con el rango de barras que corta cada uno."""
        steps, first = [], 1
        for pattern in self.patterns:
            steps.append(CutStep(first, first + pattern.count - 1, pattern))
            first += pattern.count
        return tuple(steps)

    def remnants(self, min_reusable_mm: float) -> tuple[float, float]:
        """Sobrante (mm) reutilizable y desperdicio definitivo: retales ≥ ``min_reusable_mm`` se reaprovechan.

        Con ``min_reusable_mm ≤ 0`` no se considera reutilizable ningún retal.
        """
        reusable = scrap = 0.0
        for pattern in self.patterns:
            total = pattern.remnant_mm * pattern.count
            if min_reusable_mm > 0 and pattern.remnant_mm >= min_reusable_mm - _EPS:
                reusable += total
            else:
                scrap += total
        return reusable, scrap


# ----------------------------------------------------------------- heurísticas
Bin = list[float]  # largos de las piezas de una barra


def _first_fit_decreasing(pieces: Mapping[int, int], capacity: int) -> list[Bin]:
    bins: list[list] = []  # [espacio libre, piezas]
    for length in sorted(pieces, reverse=True):
        remaining = pieces[length]
        for entry in bins:
            if not remaining:
                break
            fit = min(remaining, entry[0] // length)
            if fit:
                entry[0] -= fit * length
                entry[1].extend([length] * fit)
                remaining -= fit
        per_bar = capacity // length
        while remaining:
            fit = min(remaining, per_bar)
            bins.append([capacity - fit * length, [length] * fit])
            remaining -= fit
    return [entry[1] for entry in bins]


def _best_fit_decreasing(pieces: Mapping[int, int], capacity: int) -> list[Bin]:
    bins: list[Bin] = []
    free_index: list[tuple[int, int]] = []  # (espacio libre, barra), ordenado
    for length in sorted(pieces, reverse=True):
        remaining = pieces[length]
        per_bar = capacity // length
        while remaining:
            i = bisect_left(free_index, (length, -1))  # la barra con menos espacio libre que aún cabe
            if i < len(free_index):
                free, bin_id = free_index.pop(i)
                bins[bin_id].append(length)
                insort(free_index, (free - length, bin_id))
                remaining -= 1
            else:
                fit = min(remaining, per_bar)
                bins.append([length] * fit)
                insort(free_index, (capacity - fit * length, len(bins) - 1))
                remaining -= fit
    return bins


def _best_pattern(items: Sequence[tuple[int, int]], capacity: int) -> dict[int, int]:
    """Mejor patrón de una barra: la combinación de piezas (con sus cantidades máximas) que más la llena.

    ``items`` = (largo, cantidad disponible). Es un subset-sum acotado: se parte cada cantidad en potencias de 2
    y se resuelve con un entero grande como bitset. Los grupos se procesan de mayor a menor largo y la
    reconstrucción empieza por los menores, de modo que ante empates se prefieren las piezas más largas.
    """
    groups: list[tuple[int, int, int]] = []  # (largo del grupo, largo de la pieza, piezas en el grupo)
    for length, count in sorted(items, reverse=True):
        k = 1
        while count > 0:
            take = min(k, count)
            groups.append((take * length, length, take))
            count -= take
            k *= 2
    mask = (1 << (capacity + 1)) - 1
    history = [1]
    for weight, _, _ in groups:
        previous = history[-1]
        history.append((previous | (previous << weight)) & mask)
    best = history[-1].bit_length() - 1
    taken: dict[int, int] = {}
    for index in range(len(groups) - 1, -1, -1):
        if (history[index] >> best) & 1:
            continue  # se alcanza el mismo total sin este grupo
        weight, length, take = groups[index]
        best -= weight
        taken[length] = taken.get(length, 0) + take
    return taken


def _sequential_heuristic(pieces: Mapping[int, int], capacity: int, tolerance: int) -> tuple[list[tuple[Bin, int]], dict[int, int]]:
    """Patrones (piezas, repeticiones) de sobrante ≤ ``tolerance`` y las piezas que quedan sin asignar."""
    remaining = {length: count for length, count in pieces.items() if count > 0}
    patterns: list[tuple[Bin, int]] = []
    while remaining:
        pattern = _best_pattern(list(remaining.items()), capacity)
        if not pattern or capacity - sum(length * count for length, count in pattern.items()) > tolerance:
            break
        repeat = min(remaining[length] // count for length, count in pattern.items())
        cuts: Bin = []
        for length in sorted(pattern, reverse=True):
            cuts.extend([length] * pattern[length])
        patterns.append((cuts, repeat))
        for length, count in pattern.items():
            remaining[length] -= count * repeat
            if remaining[length] == 0:
                del remaining[length]
    return patterns, remaining


def _price(duals: Sequence[float], sizes: Sequence[int], capacity: int) -> tuple[float, list[int]]:
    """Mochila no acotada exacta: el patrón de mayor valor Σ dual·cantidad con Σ largo·cantidad ≤ capacidad."""
    items = [(size, duals[i], i) for i, size in enumerate(sizes) if duals[i] > 1e-12 and size <= capacity]
    best = [0.0] * (capacity + 1)
    choice = [-1] * (capacity + 1)
    for c in range(1, capacity + 1):
        value, pick = best[c - 1], -1
        for size, dual, i in items:
            if size <= c:
                candidate = best[c - size] + dual
                if candidate > value + 1e-12:
                    value, pick = candidate, i
        best[c], choice[c] = value, pick
    pattern = [0] * len(sizes)
    c = capacity
    while c > 0:
        if choice[c] < 0:
            c -= 1
        else:
            pattern[choice[c]] += 1
            c -= sizes[choice[c]]
    return best[capacity], pattern


def _lp_solution(pieces: Mapping[int, int], capacity: int, budget_s: float) -> list[tuple[dict[int, int], float]]:
    """Patrones de la solución básica de la relajación lineal, con su uso (fraccionario).

    Símplex revisado de ``min Σ x  s.t.  A·x = d`` con columnas generadas por mochila. La base empieza con los
    patrones homogéneos (una sola longitud). El precio se calcula en una cuadrícula más gruesa (hasta ~400
    celdas) redondeando los largos hacia arriba, de modo que todo patrón generado es factible con los largos exactos.
    """
    sizes = sorted(pieces, reverse=True)
    m = len(sizes)
    demand = [float(pieces[s]) for s in sizes]
    grid = max(1, capacity // LP_GRID_CELLS)
    coarse = [-(-s // grid) for s in sizes]
    coarse_capacity = capacity // grid

    columns: list[list[int]] = []
    for i, size in enumerate(sizes):
        column = [0] * m
        column[i] = capacity // size
        columns.append(column)
    basis = list(range(m))
    inverse = [[(1.0 / columns[i][i]) if r == i else 0.0 for r in range(m)] for i in range(m)]  # B⁻¹ (diagonal)
    x_basic = [demand[i] / columns[i][i] for i in range(m)]
    deadline = time.perf_counter() + budget_s

    for _ in range(40 * m + 200):
        duals = [sum(inverse[r][j] for r in range(m)) for j in range(m)]  # y = 1ᵀ·B⁻¹
        value, pattern = _price(duals, coarse, coarse_capacity)
        if value <= 1.0 + 1e-9 or sum(pattern) == 0:
            break
        direction = [sum(inverse[r][j] * pattern[j] for j in range(m) if pattern[j]) for r in range(m)]
        leaving, ratio = -1, math.inf
        for r in range(m):
            if direction[r] > 1e-9:
                candidate = x_basic[r] / direction[r]
                if candidate < ratio - 1e-12 or (abs(candidate - ratio) <= 1e-12 and direction[r] > direction[leaving]):
                    leaving, ratio = r, candidate
        if leaving < 0:
            break
        pivot = direction[leaving]
        row = [v / pivot for v in inverse[leaving]]
        for r in range(m):
            if r != leaving and abs(direction[r]) > 1e-15:
                factor = direction[r]
                inverse[r] = [a - factor * b for a, b in zip(inverse[r], row)]
                x_basic[r] = max(0.0, x_basic[r] - ratio * factor)
        inverse[leaving] = row
        x_basic[leaving] = ratio
        columns.append(pattern)
        basis[leaving] = len(columns) - 1
        if time.perf_counter() > deadline:
            break

    solution = []
    for r in range(m):
        if x_basic[r] > 1e-9:
            column = columns[basis[r]]
            solution.append(({sizes[j]: column[j] for j in range(m) if column[j]}, x_basic[r]))
    return solution


def _lp_rounding(pieces: Mapping[int, int], capacity: int, budget_s: float) -> tuple[list[tuple[Bin, int]], dict[int, int]]:
    """Redondea hacia abajo la solución lineal; devuelve los patrones enteros y las piezas que quedan por cortar."""
    remaining = {length: count for length, count in pieces.items() if count > 0}
    patterns: list[tuple[Bin, int]] = []
    if len(remaining) < 2:
        return patterns, remaining
    for pattern, usage in sorted(_lp_solution(remaining, capacity, budget_s), key=lambda it: -it[1]):
        repeat = int(usage + 1e-9)
        if repeat >= 1:
            repeat = min(repeat, *(remaining[length] // count for length, count in pattern.items()))
        if repeat < 1:
            continue
        cuts: Bin = []
        for length in sorted(pattern, reverse=True):
            cuts.extend([length] * pattern[length])
        patterns.append((cuts, repeat))
        for length, count in pattern.items():
            remaining[length] -= count * repeat
            if remaining[length] == 0:
                del remaining[length]
    return patterns, remaining


def _eliminate_emptiest(bins: list[Bin], capacity: int, tries: int = 6) -> list[Bin]:
    """Intenta vaciar la barra más libre repartiendo sus piezas en las demás (mejor ajuste); repite mientras sirva."""
    if len(bins) > 4000:
        return bins
    bins = [list(b) for b in bins]
    failed = 0
    while len(bins) > 1 and failed < tries:
        order = sorted(range(len(bins)), key=lambda i: sum(bins[i]))
        victim = order[min(failed, len(order) - 1)]
        free = {i: capacity - sum(b) for i, b in enumerate(bins) if i != victim}
        moves: list[tuple[int, int]] = []
        for length in sorted(bins[victim], reverse=True):
            fits = [(space, i) for i, space in free.items() if space >= length]
            if not fits:
                moves = []
                break
            space, i = min(fits)
            free[i] = space - length
            moves.append((i, length))
        if moves:
            for i, length in moves:
                bins[i].append(length)
            del bins[victim]
            failed = 0
        else:
            failed += 1
    return bins


# ------------------------------------------------------------------- interfaz
def _grid(lengths: Iterable[float]) -> int:
    """Paso de la cuadrícula entera: 5 mm si todas las piezas son múltiplos de 5, si no 1 mm."""
    return 5 if all(abs(length / 5 - round(length / 5)) < 1e-9 for length in lengths) else 1


def _plan_from_bins(bins: Iterable[Bin], unit: int, stock_length_mm: float, strategy: str, lower_bound: int) -> CuttingPlan:
    counter: Counter[tuple[float, ...]] = Counter()
    for cuts in bins:
        counter[tuple(sorted((c * unit for c in cuts), reverse=True))] += 1
    return _make_plan(counter, stock_length_mm, strategy, lower_bound)


def _make_plan(counter: Mapping[tuple[float, ...], int], stock_length_mm: float, strategy: str, lower_bound: int) -> CuttingPlan:
    # Orden de ejecución: primero lo que más barras necesita y, a igual número, lo que mejor aprovecha la barra.
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], sum(kv[0]) - stock_length_mm, kv[0]))
    patterns = tuple(CutPattern(cuts, count, stock_length_mm) for cuts, count in ordered)
    return CuttingPlan(stock_length_mm, patterns, strategy, lower_bound)


def _score(plan: CuttingPlan) -> tuple:
    """Menos barras, menos patrones distintos y más sobrante concentrado en retales grandes."""
    concentration = sum(p.remnant_mm**2 * p.count for p in plan.patterns)
    return plan.stock_bars, len(plan.patterns), -concentration


def optimize_cutting(pieces: Mapping[float, int], stock_length_mm: float,
                     strategies: Sequence[str] = STRATEGIES) -> CuttingPlan:
    """Plan de corte con el menor número de barras comerciales para ``pieces`` ({largo mm: cantidad}).

    Lanza ``ValueError`` si alguna pieza es más larga que la barra comercial o si se pide una estrategia desconocida.
    El resultado se guarda en caché: pedir el mismo plan dos veces no repite el cálculo.
    """
    unknown = set(strategies) - set(STRATEGIES)
    if unknown:
        raise ValueError(f"Estrategias desconocidas: {sorted(unknown)} (disponibles: {', '.join(STRATEGIES)}).")
    key = tuple(sorted((float(length), int(count)) for length, count in pieces.items() if count > 0))
    return _optimize_cached(key, float(stock_length_mm), tuple(strategies))


@lru_cache(maxsize=256)
def _optimize_cached(key: tuple[tuple[float, int], ...], stock_length_mm: float, strategies: tuple[str, ...]) -> CuttingPlan:
    pieces = dict(key)
    if not pieces:
        return CuttingPlan(stock_length_mm, (), "—", 0)
    longest = max(pieces)
    if longest > stock_length_mm + _EPS:
        raise ValueError(f"Hay una pieza de {longest:g} mm, más larga que la barra comercial de {stock_length_mm:g} mm.")

    unit = _grid([*pieces, stock_length_mm])
    capacity = int((stock_length_mm + _EPS) // unit)
    weights: Counter[int] = Counter()
    for length, count in pieces.items():
        weights[min(capacity, math.ceil(length / unit - 1e-9))] += count  # hacia arriba: el patrón siempre es factible
    lower_bound = math.ceil(sum(w * c for w, c in weights.items()) / capacity - 1e-9)

    candidates: list[CuttingPlan] = []
    for strategy in strategies:
        if strategy == "lp":
            patterns, residual = _lp_rounding(weights, capacity, LP_BUDGET_S)
            counter = Counter()
            for cuts, repeat in patterns:
                counter[tuple(sorted((c * unit for c in cuts), reverse=True))] += repeat
            bins = _best_fit_decreasing(residual, capacity) if residual else []
            bins = _eliminate_emptiest(bins, capacity)
            for cuts in bins:
                counter[tuple(sorted((c * unit for c in cuts), reverse=True))] += 1
            candidates.append(_make_plan(counter, stock_length_mm, strategy, lower_bound))
            continue
        if strategy == "shp":
            for fraction in SHP_TOLERANCES:
                patterns, residual = _sequential_heuristic(weights, capacity, int(fraction * capacity))
                counter: Counter[tuple[float, ...]] = Counter()
                for cuts, repeat in patterns:
                    counter[tuple(sorted((c * unit for c in cuts), reverse=True))] += repeat
                bins = _best_fit_decreasing(residual, capacity) if residual else []
                bins = _eliminate_emptiest(bins, capacity)
                for cuts in bins:
                    counter[tuple(sorted((c * unit for c in cuts), reverse=True))] += 1
                candidates.append(_make_plan(counter, stock_length_mm, strategy, lower_bound))
            continue
        bins = _first_fit_decreasing(weights, capacity) if strategy == "ffd" else _best_fit_decreasing(weights, capacity)
        improved = _eliminate_emptiest(bins, capacity) if len(bins) > lower_bound else bins
        candidates.append(_plan_from_bins(improved, unit, stock_length_mm, strategy, lower_bound))
    return min(candidates, key=_score)


def compare_stock_lengths(pieces: Mapping[float, int], lengths: Sequence[float]) -> dict[float, CuttingPlan]:
    """Plan para cada longitud comercial candidata en la que quepan todas las piezas."""
    longest = max(pieces, default=0.0)
    return {length: optimize_cutting(pieces, length) for length in lengths if length >= longest - _EPS}
