"""Motor geométrico de barras de eje poligonal: longitud de corte y esquema.

Dos familias cubren casi todo el catálogo:

* **Polilínea abierta** (:class:`OpenPoly`): tramos rectos unidos por dobleces de ángulo cualquiera, con
  un gancho opcional (90°, 135° o 180°) en cada extremo. Sirve para rectas, L, U, Z, quiebres, omegas,
  barras con ganchos, estribos abiertos y formas dibujadas a mano.
* **Polígono cerrado con ganchos** (:class:`ClosedPoly`): estribos rectangulares, triangulares,
  trapezoidales… cuyos extremos se cruzan en un vértice de cierre con dos ganchos.

Convención de cotas (la de ACI SP-66 / CRSI / BS 8666): cada tramo se mide **de fuera a fuera** de la
barra, entre los vértices donde se cortan las caras exteriores de los dobleces, proyectado sobre el eje
del tramo. Con radio interior ``r`` y diámetro ``d``, cada doblez de giro θ consume del tramo vecino la
tangente exterior ``(r + d)·tan(θ/2)``; el tramo recto que queda es ``cota − tangentes``. Para un
gancho terminal la cota llega hasta el punto más exterior del arco, ``(r + d)·sin(min(θ, 90°))``.

    L = Σ tramos rectos + Σ arcos al eje (θ·R, ``R = r + d/2``) + Σ extensiones de gancho

El resultado no depende de hacia qué lado gire cada doblez, solo de las cotas y los ángulos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.cutlength import CutLength, HookInfo
from core.geometry import GeometryError
from core.rebar import BendUse, HookType, Rebar
from core.sketch import DimLabel, Point, Sketch, format_dimension, proportional

_EPS = 1e-6
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class HookSpec:
    """Gancho pedido en un extremo: ángulo y extensión recta (``None`` → la estándar de la norma)."""

    angle_deg: float
    extension_mm: float | None = None


@dataclass(frozen=True)
class OpenPoly:
    """Barra de eje poligonal abierta.

    ``legs`` son las cotas exteriores de los tramos y ``angles`` los giros entre tramos consecutivos
    (positivo = a la izquierda). ``end_hooks`` marca los tramos de extremo que deben informarse como
    ganchos (p. ej. la pata de una L o de una U) aunque no sean un gancho normativo explícito.
    """

    legs: tuple[float, ...]
    angles: tuple[float, ...] = ()
    hook_start: HookSpec | None = None
    hook_end: HookSpec | None = None
    use: BendUse = BendUse.MAIN
    opposite: bool = False  # ganchos en lados opuestos de la barra (por defecto, del mismo lado)
    end_hooks: tuple[bool, bool] = (False, False)
    floor: float = 0.3  # tramo mínimo relativo en el esquema, para que un tramo corto siga legible
    start_heading: float = 0.0  # rumbo del primer tramo en el esquema (0° = hacia la derecha)


@dataclass(frozen=True)
class ClosedPoly:
    """Polígono cerrado recorrido en sentido antihorario con dos ganchos en el vértice de cierre.

    ``sides`` son las cotas exteriores de cada lado y ``turns`` el giro en el vértice al final de cada
    lado (todos positivos; el último es el vértice de cierre, entre el último y el primer lado).
    """

    sides: tuple[float, ...]
    turns: tuple[float, ...]
    hook: HookSpec
    use: BendUse = BendUse.STIRRUP


def angles_text(values: list[float]) -> str:
    """Ángulos agrupados: ``[90, 90, 60]`` → ``"2 × 90°, 60°"``."""
    counts: dict[int, int] = {}
    for value in values:
        counts[round(value)] = counts.get(round(value), 0) + 1
    return ", ".join(f"{n} × {angle}°" if n > 1 else f"{angle}°" for angle, n in counts.items())


def use_name(use: BendUse) -> str:
    return "estribos" if use is BendUse.STIRRUP else "barras"


def hook_extent(angle_deg: float, outer_radius_mm: float) -> float:
    """Distancia, medida sobre el tramo, entre el inicio del arco del gancho y su punto más exterior."""
    return outer_radius_mm * math.sin(math.radians(min(angle_deg, 90.0)))


def resolve_hook(rebar: Rebar, use: BendUse, hook: HookSpec) -> tuple[HookInfo, list[str]]:
    """Largo del gancho (el pedido o el estándar) y avisos si queda bajo el mínimo de la norma."""
    angle = float(hook.angle_deg)
    standard: float | None
    try:
        standard = rebar.standard_hook(HookType(int(round(angle))), use).extension_mm
    except (ValueError, GeometryError):
        standard = None
    warnings: list[str] = []
    if hook.extension_mm is None:
        if standard is None:
            raise GeometryError(
                f"{rebar.designation}: no hay gancho estándar de {angle:.0f}° para {use_name(use)}; indique la extensión."
            )
        extension = standard
    else:
        extension = float(hook.extension_mm)
        if standard is None:
            warnings.append(f"Gancho de {angle:.0f}° sin extensión estándar para {use_name(use)}; verifique la norma")
        elif extension < standard - _EPS:
            warnings.append(f"Extensión de gancho {extension:.0f} mm < mínimo normativo {standard:.0f} mm")
    return HookInfo(angle, extension, standard), warnings


@dataclass(frozen=True)
class OpenResult:
    """Resultado del análisis de una polilínea abierta."""

    cut: CutLength
    straights: tuple[float, ...]  # tramos rectos entre tangentes, uno por tramo
    start_hook: HookInfo | None  # gancho explícito del inicio
    end_hook: HookInfo | None  # gancho explícito del final
    first_tail: float | None  # pata del primer tramo informada como gancho (``end_hooks``)
    last_tail: float | None


def analyse_open(code: str, poly: OpenPoly, rebar: Rebar) -> OpenResult:
    legs, angles = poly.legs, poly.angles
    if len(angles) != len(legs) - 1:
        raise GeometryError(f"Forma {code}: {len(legs)} tramos necesitan {len(legs) - 1} ángulos de giro.")
    d = rebar.diameter_mm
    r = rebar.bend_radius_mm(poly.use)
    radius = rebar.centerline_radius_mm(poly.use)
    outer = r + d
    tans = [math.tan(math.radians(abs(a)) / 2.0) for a in angles]

    warnings: list[str] = []
    resolved: list[HookInfo | None] = [None, None]
    trims = [0.0, 0.0]
    arcs = sum(math.radians(abs(a)) for a in angles) * radius
    extensions = 0.0
    for slot, spec in enumerate((poly.hook_start, poly.hook_end)):
        if spec is None:
            continue
        info, extra = resolve_hook(rebar, poly.use, spec)
        warnings += extra
        resolved[slot] = info
        trims[slot] = hook_extent(info.angle_deg, outer)
        arcs += math.radians(info.angle_deg) * radius
        extensions += info.extension_mm

    n = len(legs)
    straights: list[float] = []
    for i, leg in enumerate(legs):
        before = trims[0] if i == 0 else outer * tans[i - 1]
        after = trims[1] if i == n - 1 else outer * tans[i]
        straight = leg - before - after
        if straight < -_EPS:
            raise GeometryError(
                f"Forma {code} con {rebar.designation}: la cota {LETTERS[i % 26]} = {leg:g} mm es menor que el "
                f"mínimo geométrico de {before + after:.1f} mm (radio de doblez + diámetro de barra)."
            )
        straights.append(max(straight, 0.0))

    standard_90: float | None
    try:
        standard_90 = rebar.standard_hook(HookType.DEG_90, poly.use).extension_mm
    except GeometryError:
        standard_90 = None
    hooks = [h for h in resolved if h is not None]
    first_tail = last_tail = None
    if poly.end_hooks[0] and angles:
        first_tail = straights[0]
        hooks.insert(0, HookInfo(abs(angles[0]), first_tail, standard_90 if round(abs(angles[0])) == 90 else None))
    if poly.end_hooks[1] and angles:
        last_tail = straights[-1]
        hooks.append(HookInfo(abs(angles[-1]), last_tail, standard_90 if round(abs(angles[-1])) == 90 else None))

    total = sum(straights) + arcs + extensions
    notes = []
    if angles:
        notes.append("Dobleces " + angles_text([abs(a) for a in angles]))
    notes.append(f"Ø interior {2 * r:.0f} mm")
    cut = CutLength(
        dimension_sum_mm=sum(legs),
        bend_adjustment_mm=total - sum(legs) - extensions,
        extension_mm=extensions,
        notes=(" · ".join(notes),),
        warnings=tuple(warnings),
        hooks=tuple(hooks),
    )
    return OpenResult(cut, tuple(straights), resolved[0], resolved[1], first_tail, last_tail)


def analyse_closed(code: str, poly: ClosedPoly, rebar: Rebar) -> CutLength:
    sides, turns = poly.sides, poly.turns
    n = len(sides)
    if len(turns) != n or n < 3:
        raise GeometryError(f"Forma {code}: un polígono cerrado necesita al menos 3 lados con su giro en cada vértice.")
    d = rebar.diameter_mm
    r = rebar.bend_radius_mm(poly.use)
    radius = rebar.centerline_radius_mm(poly.use)
    outer = r + d
    tans = [math.tan(math.radians(t) / 2.0) for t in turns]
    info, warnings = resolve_hook(rebar, poly.use, poly.hook)

    straights = []
    for i, side in enumerate(sides):
        straight = side - outer * (tans[i - 1] + tans[i])  # vértice anterior (i − 1, cíclico) y siguiente (i)
        if straight < -_EPS:
            raise GeometryError(
                f"Forma {code} con {rebar.designation}: la cota {LETTERS[i % 26]} = {side:g} mm es menor que el "
                f"mínimo geométrico de {outer * (tans[i - 1] + tans[i]):.1f} mm (radio de doblez + diámetro de barra)."
            )
        straights.append(max(straight, 0.0))

    closing = n - 1  # en el vértice de cierre los dos ganchos reemplazan al doblez
    arcs = sum(math.radians(t) * radius for j, t in enumerate(turns) if j != closing)
    arcs += 2.0 * math.radians(info.angle_deg) * radius
    extensions = 2.0 * info.extension_mm
    total = sum(straights) + arcs + extensions
    interior = angles_text([180 - t for t in turns])
    angle_note = f"Ángulos internos {interior} · " if any(abs(180 - t - 90.0) >= 0.5 for t in turns) else ""
    return CutLength(
        dimension_sum_mm=sum(sides),
        bend_adjustment_mm=total - sum(sides) - extensions,
        extension_mm=extensions,
        notes=(f"{angle_note}Ø interior {2 * r:.0f} mm",),
        warnings=tuple(warnings),
        hooks=(info, info),
    )


# ------------------------------------------------------------------ esquemas
def _dir(deg: float) -> Point:
    rad = math.radians(deg)
    return math.cos(rad), math.sin(rad)


def _unit(v: Point) -> Point:
    norm = math.hypot(*v)
    return (v[0] / norm, v[1] / norm) if norm > 1e-12 else (0.0, 1.0)


def _step(p: Point, v: Point, k: float = 1.0) -> Point:
    return p[0] + k * v[0], p[1] + k * v[1]


def _hook_label(length: float | None, at: Point, outward: Point) -> list[DimLabel]:
    if length is None:
        return []
    return [DimLabel(f"G {format_dimension(length)}", at, _unit(outward), kind="hook")]


def _bisector(previous: Point, vertex: Point, following: Point) -> Point:
    u1 = _unit((previous[0] - vertex[0], previous[1] - vertex[1]))
    u2 = _unit((following[0] - vertex[0], following[1] - vertex[1]))
    return _unit((u1[0] + u2[0], u1[1] + u2[1]))


def _hook_points(vertex: Point, leg_heading: float, phi: float, sigma: float, at_start: bool,
                 tail: float, gap: float) -> list[Point]:
    """Puntos del gancho desde el vértice hasta el extremo libre (en ese orden).

    ``sigma`` = +1 si el gancho gira a la izquierda del sentido de recorrido de la barra y −1 si a la derecha.
    """
    outward = leg_heading + 180.0 if at_start else leg_heading  # rumbo que sale de la barra por ese extremo
    if abs(phi - 180.0) < 1e-9:  # horquilla: el extremo vuelve sobre el tramo, algo separado
        elbow = _step(vertex, _dir(leg_heading + 90.0), sigma * gap)
        return [elbow, _step(elbow, _dir(outward + 180.0), tail)]
    tail_heading = outward + (-sigma if at_start else sigma) * phi
    return [_step(vertex, _dir(tail_heading), tail)]


def open_polyline_sketch(code: str, poly: OpenPoly, rebar: Rebar | None) -> Sketch:
    """Esquema de una polilínea abierta con sus cotas, ángulos y (si se conoce la barra) largo de ganchos."""
    rel = proportional(poly.legs, poly.floor)
    heading = poly.start_heading
    points: list[Point] = [(0.0, 0.0)]
    headings: list[float] = []
    for i, length in enumerate(rel):
        headings.append(heading)
        points.append(_step(points[-1], _dir(heading), length))
        if i < len(poly.angles):
            heading += poly.angles[i]

    result: OpenResult | None = None
    if rebar is not None:
        try:
            result = analyse_open(code, poly, rebar)
        except GeometryError:
            result = None  # geometría imposible: se dibuja sin largos de gancho

    sigma_start = 1.0 if sum(poly.angles) >= 0 else -1.0
    sigma_end = -sigma_start if poly.opposite else sigma_start
    tail = min(0.3, max(0.12, 0.22 * max(rel)))
    gap = 0.07
    start_pts = _hook_points(points[0], headings[0], poly.hook_start.angle_deg, sigma_start, True, tail, gap) \
        if poly.hook_start else []
    end_pts = _hook_points(points[-1], headings[-1], poly.hook_end.angle_deg, sigma_end, False, tail, gap) \
        if poly.hook_end else []
    path = (*reversed(start_pts), *points, *end_pts)

    centroid = (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
    labels: list[DimLabel] = []
    for i, length in enumerate(poly.legs):
        a, b = points[i], points[i + 1]
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        normal = (-math.sin(math.radians(headings[i])), math.cos(math.radians(headings[i])))
        if (mid[0] - centroid[0]) * normal[0] + (mid[1] - centroid[1]) * normal[1] < -1e-9:
            normal = (-normal[0], -normal[1])  # el rótulo va hacia afuera de la figura
        labels.append(DimLabel(format_dimension(length), mid, normal))
    shown: set[int] = set()
    for i, turn in enumerate(poly.angles):
        if abs(abs(turn) - 90.0) >= 0.5 and round(abs(turn)) not in shown:  # un rótulo por ángulo distinto
            shown.add(round(abs(turn)))
            labels.append(DimLabel(f"{abs(turn):.0f}°", points[i + 1],
                                   _bisector(points[i], points[i + 1], points[i + 2]), kind="angle"))

    if result is not None:
        # El largo del gancho se rotula en el extremo de la barra, hacia afuera, para no pisar las cotas.
        for info, vertex, outward in ((result.start_hook, points[0], _dir(headings[0] + 180.0)),
                                      (result.end_hook, points[-1], _dir(headings[-1]))):
            if info is not None:
                labels += _hook_label(info.extension_mm, vertex, outward)
        if result.first_tail is not None:
            labels += _hook_label(result.first_tail, points[0], (points[0][0] - points[1][0], points[0][1] - points[1][1]))
        if result.last_tail is not None:
            labels += _hook_label(result.last_tail, points[-1], (points[-1][0] - points[-2][0], points[-1][1] - points[-2][1]))
    return Sketch(paths=(tuple(path),), labels=tuple(labels))


def closed_polygon_sketch(code: str, poly: ClosedPoly, rebar: Rebar | None) -> Sketch:
    """Esquema de un polígono cerrado con sus cotas, ángulos internos y largo de ganchos."""
    n = len(poly.sides)
    heading = 0.0
    raw: list[Point] = [(0.0, 0.0)]
    headings: list[float] = []
    for i in range(n):
        headings.append(heading)
        raw.append(_step(raw[-1], _dir(heading), poly.sides[i]))
        heading += poly.turns[i]
    extent = max(max(p[0] for p in raw) - min(p[0] for p in raw), max(p[1] for p in raw) - min(p[1] for p in raw), 1e-9)
    pts = [(p[0] / extent, p[1] / extent) for p in raw[:n]]  # el último punto repite al primero

    phi = poly.hook.angle_deg
    smallest = min(poly.sides) / extent
    tail = max(0.07, 0.22 * smallest)
    gap = 0.12 * smallest
    first_dir, last_dir = headings[0], headings[n - 1]
    vertex = pts[0]
    # Primer gancho (antes de salir por el primer lado) y segundo (al llegar por el último lado).
    tail1_dir = first_dir + 180.0 - phi
    tail2_dir = last_dir + phi
    if abs(phi - 90.0) < 1e-9:  # a 90° las patas quedarían sobre los lados: se inclinan un poco hacia adentro
        tail1_dir -= 12.0
        tail2_dir += 12.0
    start = _step(vertex, _dir(tail1_dir), tail)
    back = _step(vertex, _dir(last_dir), -gap)
    end = _step(back, _dir(tail2_dir), tail)
    path = (start, *pts, back, end)

    labels: list[DimLabel] = []
    for i, side in enumerate(poly.sides):
        a, b = pts[i], pts[(i + 1) % n]
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        labels.append(DimLabel(format_dimension(side), mid, (math.sin(math.radians(headings[i])), -math.cos(math.radians(headings[i])))))
    shown: set[int] = set()
    for j, turn in enumerate(poly.turns):
        interior = 180.0 - turn
        if abs(interior - 90.0) < 0.5 or round(interior) in shown:  # un rótulo por ángulo distinto
            continue
        shown.add(round(interior))
        v = pts[(j + 1) % n]
        prev, nxt = pts[j], pts[(j + 2) % n]
        u1 = _unit((prev[0] - v[0], prev[1] - v[1]))
        u2 = _unit((nxt[0] - v[0], nxt[1] - v[1]))
        labels.append(DimLabel(f"{interior:.0f}°", v, _unit((u1[0] + u2[0], u1[1] + u2[1])), kind="angle"))
    if rebar is not None:
        try:
            info = analyse_closed_hook(code, poly, rebar)
        except GeometryError:
            info = None
        if info is not None:  # el rótulo va fuera de la esquina de cierre, donde nacen los dos ganchos
            centroid = (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
            side = -1.0 if vertex[0] <= centroid[0] else 1.0
            labels += _hook_label(info.extension_mm, vertex, (side, 0.0))
    return Sketch(paths=(path,), labels=tuple(labels))


def analyse_closed_hook(code: str, poly: ClosedPoly, rebar: Rebar) -> HookInfo:
    """Gancho resuelto de un polígono cerrado (el pedido o el estándar)."""
    return resolve_hook(rebar, poly.use, poly.hook)[0]
