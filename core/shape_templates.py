"""Catálogo de plantillas de formas de doblado.

Se organiza como el modelo de formas de Revit: cada forma es de **estilo** «barra» o «estribo/ligadura»
(que decide el diámetro de doblez y los ganchos estándar) y sus extremos admiten ganchos de 90°, 135° o 180°.
En todas las familias de estribos, aros y espirales el gancho del inicio y el del final se eligen por separado
(ángulo y extensión), de modo que una misma plantilla cubre el estribo con patas a 135°, a 90° o mixtas.

=======  ==============================================  ==========================================
Código   Plantilla                                       Familia
=======  ==============================================  ==========================================
``R``    Recta                                           polilínea (en ``shape_codes``)
``L``    Bastón L                                        polilínea (en ``shape_codes``)
``U``    Gancho U                                        polilínea (en ``shape_codes``)
``E``    Estribo rectangular (patas de 90° o 135°)       polígono cerrado (en ``shape_codes``)
``G``    Barra con ganchos (0/90/135/180° en cada punta) polilínea
``EU``   Estribo abierto en U (patas de 90° o 135°)      polilínea
``Z``    Barra en Z                                      polilínea
``Q``    Quiebre (barra con tramo inclinado)             polilínea
``O``    Omega (Ω)                                       polilínea
``ET``   Estribo triangular (patas de 90° o 135°)        polígono cerrado
``ETR``  Estribo trapezoidal (patas de 90° o 135°)       polígono cerrado
``AR``   Aro circular (traslape y ganchos opcionales)    geometría propia
``ES``   Espiral (vueltas extra y ganchos opcionales)    geometría propia
``X``    Personalizada (tramos y ángulos a mano)         polilínea
=======  ==============================================  ==========================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import ClassVar

from core.coupler import COUPLER_CHOICES
from core.cutlength import CutLength
from core.geometry import GeometryError
from core.params import param
from core.polybar import LETTERS, ClosedPoly, HookSpec, OpenPoly, hook_allowance, hook_tail, resolve_hook
from core.rebar import BendUse, Rebar
from core.shape_codes import (
    HOOK_CHOICES,
    RING_HOOK_CHOICES,
    SIDE_CHOICES,
    STIRRUP_HOOK_CHOICES,
    STYLE_CHOICES,
    ClosedPolyShape,
    OpenPolyShape,
    ShapeCode,
    hook_spec as _hook,
    migrate_single_hook,
    register_shape,
)
from core.sketch import DimLabel, Sketch, dimension_text, format_dimension, proportional


def _use(style: str) -> BendUse:
    return BendUse.STIRRUP if style == "stirrup" else BendUse.MAIN


# ----------------------------------------------------------- polilíneas abiertas
@register_shape
@dataclass(frozen=True)
class HookedBar(OpenPolyShape):
    """Barra recta con un gancho (0°, 90°, 135° o 180°) en cada extremo.

    ``a`` es la longitud entre los puntos más exteriores de los ganchos (o el extremo libre si no hay gancho).
    El largo de cada gancho es su extensión recta; si se omite se usa la estándar de la norma.
    """

    code: ClassVar[str] = "G"
    name: ClassVar[str] = "Barra con ganchos"
    description: ClassVar[str] = "Barra recta con ganchos de 90°, 135° o 180° en uno o ambos extremos (barras, trabas, ligaduras)."

    a: float = param("A · largo entre caras exteriores", default=1000.0)
    hook_start: int = param("Gancho inicial", "choice", 90, choices=HOOK_CHOICES)
    ext_start: float | None = param("Extensión del gancho inicial", "length", None, optional=True)
    hook_end: int = param("Gancho final", "choice", 90, choices=HOOK_CHOICES)
    ext_end: float | None = param("Extensión del gancho final", "length", None, optional=True)
    opposite: int = param("Orientación de los ganchos", "choice", 0, choices=SIDE_CHOICES)
    style: str = param("Estilo", "choice", "main", choices=STYLE_CHOICES)
    coupler_start: str = param("Coupler inicial (solo sin gancho)", "choice", "none", choices=COUPLER_CHOICES)
    coupler_end: str = param("Coupler final (solo sin gancho)", "choice", "none", choices=COUPLER_CHOICES)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.a,), (), _hook(self.hook_start, self.ext_start), _hook(self.hook_end, self.ext_end),
                        _use(self.style), bool(self.opposite), coupler_start=self.coupler_start,
                        coupler_end=self.coupler_end)


@register_shape
@dataclass(frozen=True)
class UStirrup(OpenPolyShape):
    """Estribo abierto en U (grapa) con una pata de 90° o 135° en cada extremo libre."""

    code: ClassVar[str] = "EU"
    name: ClassVar[str] = "Estribo en U"
    description: ClassVar[str] = "Estribo abierto en U (grapa); cada punta con gancho de 90° o 135°."

    a: float = param("A · ancho exterior", default=300.0)
    b: float = param("B · alto exterior", default=400.0)
    hook_start: int = param("Gancho inicial", "choice", 135, choices=STIRRUP_HOOK_CHOICES)
    ext_start: float | None = param("Extensión del gancho inicial", "length", None, optional=True)
    hook_end: int = param("Gancho final", "choice", 135, choices=STIRRUP_HOOK_CHOICES)
    ext_end: float | None = param("Extensión del gancho final", "length", None, optional=True)

    @classmethod
    def migrate(cls, parameters: dict[str, object]) -> dict[str, object]:
        return migrate_single_hook(parameters)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.b, self.a, self.b), (90.0, 90.0), _hook(self.hook_start, self.ext_start),
                        _hook(self.hook_end, self.ext_end), BendUse.STIRRUP, start_heading=-90.0,
                        names=("B", "A", "B"))


@register_shape
@dataclass(frozen=True)
class ZBar(OpenPolyShape):
    """Barra en Z: dos dobleces de 90° en sentidos opuestos (tramo, pata central y tramo)."""

    code: ClassVar[str] = "Z"
    name: ClassVar[str] = "Barra en Z"
    description: ClassVar[str] = "Dos dobleces a 90° en sentidos opuestos (empalme de columnas, desfase de barras)."

    a: float = param("A · primer tramo", default=250.0)
    b: float = param("B · pata central", default=200.0)
    c: float = param("C · segundo tramo", default=250.0)
    style: str = param("Estilo", "choice", "main", choices=STYLE_CHOICES)
    coupler_start: str = param("Coupler inicial", "choice", "none", choices=COUPLER_CHOICES)
    coupler_end: str = param("Coupler final", "choice", "none", choices=COUPLER_CHOICES)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b, "C": self.c}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.a, self.b, self.c), (90.0, -90.0), use=_use(self.style),
                        coupler_start=self.coupler_start, coupler_end=self.coupler_end)


@register_shape
@dataclass(frozen=True)
class CrankBar(OpenPolyShape):
    """Quiebre: dos tramos paralelos unidos por un tramo inclinado a ``angle`` grados.

    ``b`` es la cota exterior del tramo inclinado, medida sobre su eje entre los vértices exteriores.
    """

    code: ClassVar[str] = "Q"
    name: ClassVar[str] = "Quiebre"
    description: ClassVar[str] = "Barra con un tramo inclinado (barra levantada, desfase) a 30°, 45°, 60° o el ángulo que indique."

    a: float = param("A · primer tramo", default=600.0)
    b: float = param("B · tramo inclinado", default=300.0)
    c: float = param("C · segundo tramo", default=600.0)
    angle: float = param("Ángulo de los dobleces", "angle", 45.0, minimum=5.0, maximum=85.0)
    style: str = param("Estilo", "choice", "main", choices=STYLE_CHOICES)
    coupler_start: str = param("Coupler inicial", "choice", "none", choices=COUPLER_CHOICES)
    coupler_end: str = param("Coupler final", "choice", "none", choices=COUPLER_CHOICES)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b, "C": self.c}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.a, self.b, self.c), (self.angle, -self.angle), use=_use(self.style),
                        coupler_start=self.coupler_start, coupler_end=self.coupler_end)

    def cut_length(self, rebar: Rebar) -> CutLength:
        cut = super().cut_length(rebar)
        half = math.tan(math.radians(self.angle) / 2.0)
        rise = (self.b - rebar.diameter_mm * half) * math.sin(math.radians(self.angle)) + rebar.diameter_mm
        return replace(cut, notes=cut.notes + (f"Desnivel exterior {rise:.0f} mm",))


@register_shape
@dataclass(frozen=True)
class OmegaBar(OpenPolyShape):
    """Omega (Ω, «sombrero»): dos alas, dos patas y un tramo superior, con cuatro dobleces de 90°."""

    code: ClassVar[str] = "O"
    name: ClassVar[str] = "Omega"
    description: ClassVar[str] = "Ala, pata, tramo superior, pata y ala (grapas de unión, estribos omega)."

    a: float = param("A · ala izquierda", default=200.0)
    b: float = param("B · pata izquierda", default=300.0)
    c: float = param("C · tramo superior", default=400.0)
    d: float = param("D · pata derecha", default=300.0)
    e: float = param("E · ala derecha", default=200.0)
    style: str = param("Estilo", "choice", "main", choices=STYLE_CHOICES)
    coupler_start: str = param("Coupler inicial", "choice", "none", choices=COUPLER_CHOICES)
    coupler_end: str = param("Coupler final", "choice", "none", choices=COUPLER_CHOICES)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b, "C": self.c, "D": self.d, "E": self.e}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.a, self.b, self.c, self.d, self.e), (90.0, -90.0, -90.0, 90.0), use=_use(self.style),
                        coupler_start=self.coupler_start, coupler_end=self.coupler_end)


# ---------------------------------------------------------- polígonos cerrados
@register_shape
@dataclass(frozen=True)
class TriStirrup(ClosedPolyShape):
    """Estribo triangular cerrado definido por sus tres lados exteriores, con patas de 90° o 135°."""

    code: ClassVar[str] = "ET"
    name: ClassVar[str] = "Estribo triangular"
    description: ClassVar[str] = "Estribo cerrado de tres lados (ángulos internos distintos de 90°)."

    a: float = param("A · lado 1", default=300.0)
    b: float = param("B · lado 2", default=300.0)
    c: float = param("C · lado 3", default=300.0)
    hook_start: int = param("Gancho inicial", "choice", 135, choices=STIRRUP_HOOK_CHOICES)
    ext_start: float | None = param("Extensión del gancho inicial", "length", None, optional=True)
    hook_end: int = param("Gancho final", "choice", 135, choices=STIRRUP_HOOK_CHOICES)
    ext_end: float | None = param("Extensión del gancho final", "length", None, optional=True)

    @classmethod
    def migrate(cls, parameters: dict[str, object]) -> dict[str, object]:
        return migrate_single_hook(parameters)

    def validate(self) -> None:
        a, b, c = self.a, self.b, self.c
        if a >= b + c or b >= a + c or c >= a + b:
            raise GeometryError(f"Forma {self.code}: los lados {a:g}, {b:g} y {c:g} mm no forman un triángulo.")

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b, "C": self.c}

    def interior_angles(self) -> tuple[float, float, float]:
        """Ángulos internos (°) al final de los lados A, B y C, en ese orden."""
        a, b, c = self.a, self.b, self.c

        def angle(x: float, y: float, opposite: float) -> float:
            return math.degrees(math.acos((x * x + y * y - opposite * opposite) / (2.0 * x * y)))

        return angle(a, b, c), angle(b, c, a), angle(c, a, b)

    def poly(self) -> ClosedPoly:
        turns = tuple(180.0 - angle for angle in self.interior_angles())
        return ClosedPoly((self.a, self.b, self.c), turns, HookSpec(float(self.hook_start), self.ext_start),
                          HookSpec(float(self.hook_end), self.ext_end), names=("A", "B", "C"))


@register_shape
@dataclass(frozen=True)
class TrapStirrup(ClosedPolyShape):
    """Estribo trapezoidal cerrado (trapecio isósceles) con patas de 90° o 135°.

    Cotas: A = base mayor, B = base menor, C = altura (acotada con una línea punteada) y D = lado inclinado.
    """

    code: ClassVar[str] = "ETR"
    name: ClassVar[str] = "Estribo trapezoidal"
    description: ClassVar[str] = "Estribo cerrado de cuatro lados con dos ángulos internos distintos de 90°."

    bottom: float = param("A · base mayor", default=400.0)
    top: float = param("B · base menor", default=250.0)
    height: float = param("C · altura", default=300.0)
    hook_start: int = param("Gancho inicial", "choice", 135, choices=STIRRUP_HOOK_CHOICES)
    ext_start: float | None = param("Extensión del gancho inicial", "length", None, optional=True)
    hook_end: int = param("Gancho final", "choice", 135, choices=STIRRUP_HOOK_CHOICES)
    ext_end: float | None = param("Extensión del gancho final", "length", None, optional=True)

    @classmethod
    def migrate(cls, parameters: dict[str, object]) -> dict[str, object]:
        return migrate_single_hook(parameters)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.bottom, "B": self.top, "C": self.height, "D": self.leg()}

    def leg(self) -> float:
        """Lado inclinado exterior."""
        return math.hypot(self.height, (self.bottom - self.top) / 2.0)

    def base_angle(self) -> float:
        """Ángulo interno en los extremos de la base A (°)."""
        return math.degrees(math.atan2(self.height, (self.bottom - self.top) / 2.0))

    def poly(self) -> ClosedPoly:
        beta = self.base_angle()
        return ClosedPoly((self.bottom, self.leg(), self.top, self.leg()),
                          (180.0 - beta, beta, beta, 180.0 - beta),
                          HookSpec(float(self.hook_start), self.ext_start), HookSpec(float(self.hook_end), self.ext_end),
                          names=("A", "", "B", "D"))

    def sketch(self, rebar: Rebar | None = None) -> Sketch:
        base = super().sketch(rebar)
        # La altura C no es un lado: se acota con una línea punteada vertical, fuera del trapecio y con sus líneas de
        # referencia, a la derecha (el lado inclinado izquierdo es el que lleva el rótulo D).
        extent = max(self.bottom, self.height)
        right, h = self.bottom / extent + 0.12, self.height / extent
        top_right = (self.bottom + self.top) / 2.0 / extent
        guides = (((right, 0.0), (right, h)), ((self.bottom / extent, 0.0), (right, 0.0)), ((top_right, h), (right, h)))
        label = DimLabel(dimension_text("C", self.height), (right, h / 2.0), (1.0, 0.0))
        return Sketch(base.paths, (*base.labels, label), (*base.guides, *guides))


# ----------------------------------------------------------- geometría propia
def _arc(center: tuple[float, float], radius: float, start_deg: float, end_deg: float, steps: int = 48):
    return tuple((center[0] + radius * math.cos(math.radians(start_deg + (end_deg - start_deg) * k / steps)),
                  center[1] + radius * math.sin(math.radians(start_deg + (end_deg - start_deg) * k / steps)))
                 for k in range(steps + 1))


def _round_use(rebar: Rebar) -> BendUse:
    """Aros y espirales usan el doblez de estribo cuando la norma lo define (hasta #8)."""
    return BendUse.STIRRUP if rebar.bar_number <= 8 else BendUse.MAIN


def _min_diameter_check(code: str, rebar: Rebar, diameter: float, use: BendUse) -> None:
    minimum = rebar.bend_diameter_mm(use) + 2.0 * rebar.diameter_mm
    if diameter < minimum - 1e-6:
        raise GeometryError(
            f"Forma {code} con {rebar.designation}: el diámetro A = {diameter:g} mm es menor que el "
            f"mínimo geométrico de {minimum:.1f} mm (Ø de doblez + 2 diámetros de barra)."
        )


@register_shape
@dataclass(frozen=True)
class RingTie(ShapeCode):
    """Aro circular (estribo circular) de una vuelta, cerrado con traslape y/o con ganchos de 90° o 135°.

    ``diameter`` es el diámetro exterior (de cara exterior a cara exterior), ``lap`` el traslape (0 si los
    extremos solo se cierran con ganchos) y ``hook_start``/``hook_end`` el gancho de cada extremo, que se
    dobla hacia el interior del aro. Longitud al eje::

        L = π·(D − d) + traslape + Σ (φ·R + extensión)

    Sin ganchos equivale al código 75 de BS 8666.
    """

    code: ClassVar[str] = "AR"
    name: ClassVar[str] = "Aro circular"
    description: ClassVar[str] = (
        "Estribo circular de una vuelta, cerrado con traslape y/o con ganchos de 90° o 135° en los extremos "
        "(columnas circulares, pilotes). Con ganchos en ambos extremos ponga traslape 0."
    )

    diameter: float = param("A · diámetro exterior", default=400.0)
    lap: float = param("B · traslape", "length", 250.0, minimum=0.0)
    hook_start: int = param("Gancho inicial", "choice", 0, choices=RING_HOOK_CHOICES)
    ext_start: float | None = param("Extensión del gancho inicial", "length", None, optional=True)
    hook_end: int = param("Gancho final", "choice", 0, choices=RING_HOOK_CHOICES)
    ext_end: float | None = param("Extensión del gancho final", "length", None, optional=True)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.diameter, "B": self.lap}

    def _specs(self) -> tuple[HookSpec | None, HookSpec | None]:
        return _hook(self.hook_start, self.ext_start), _hook(self.hook_end, self.ext_end)

    def cut_length(self, rebar: Rebar) -> CutLength:
        d = rebar.diameter_mm
        use = _round_use(rebar)
        _min_diameter_check(self.code, rebar, self.diameter, use)
        hooks = hook_allowance(rebar, use, self._specs())
        notes = []
        if self.lap > 0:
            notes.append(f"Traslape {self.lap:.0f} mm")
        notes.append(f"Ø interior mínimo {rebar.bend_diameter_mm(use):.0f} mm")
        return CutLength(
            dimension_sum_mm=math.pi * self.diameter + self.lap,
            bend_adjustment_mm=-math.pi * d + hooks.arc_mm,
            extension_mm=hooks.extension_mm,
            notes=(" · ".join(notes),),
            warnings=hooks.warnings,
            hooks=hooks.infos,
        )

    def sketch(self, rebar: Rebar | None = None) -> Sketch:
        start, tail = 90.0, 0.26
        lap_deg = max(25.0, min(90.0, 360.0 * self.lap / (math.pi * self.diameter))) if self.lap > 0 else 0.0
        outer = list(_arc((0.0, 0.0), 1.0, start, start + 360.0, 96))
        inner = list(_arc((0.0, 0.0), 0.8, start, start + lap_deg, 16)) if lap_deg else []
        labels = [DimLabel(dimension_text("A", self.diameter), (0.0, 0.0), (0.0, -1.0))]
        if lap_deg:  # el traslape se rotula fuera del aro, a la izquierda de su punto medio
            middle = math.radians(start + lap_deg / 2.0)
            labels.append(DimLabel(dimension_text("B", self.lap), (1.08 * math.cos(middle), 1.08 * math.sin(middle)),
                                   (-1.0, 0.0)))

        # Ganchos: el del inicio sale del punto de partida; el del final, del extremo del traslape (o del mismo punto).
        top = (0.0, 1.0)
        tips: list[tuple[float, float] | None] = [None, None]
        if self.hook_start:
            tips[0] = hook_tail(top, 180.0, float(self.hook_start), True, tail)
            outer.insert(0, tips[0])
        if self.hook_end:
            if lap_deg:
                angle = math.radians(start + lap_deg)
                end_point, heading = (0.8 * math.cos(angle), 0.8 * math.sin(angle)), start + lap_deg + 90.0
                tips[1] = hook_tail(end_point, heading, float(self.hook_end), False, tail)
                inner.append(tips[1])
            else:
                tips[1] = hook_tail(top, 180.0, float(self.hook_end), False, tail)
                outer.append(tips[1])
        if rebar is not None and any(tips):
            labels += self._hook_labels(rebar, tips, bool(lap_deg))
        paths = (tuple(outer), tuple(inner)) if inner else (tuple(outer),)
        return Sketch(paths=paths, labels=tuple(labels), guides=(((-1.0, 0.0), (1.0, 0.0)),))

    def _hook_labels(self, rebar: Rebar, tips: list, has_lap: bool) -> list[DimLabel]:
        try:
            infos = [resolve_hook(rebar, _round_use(rebar), spec)[0] if spec else None for spec in self._specs()]
        except GeometryError:
            return []
        present = [(info, tip) for info, tip in zip(infos, tips) if info is not None and tip is not None]
        if len(present) == 2 and abs(present[0][0].extension_mm - present[1][0].extension_mm) < 0.5:
            (info, a), (_, b) = present  # dos ganchos de igual largo: un solo rótulo (bajo ambos si nacen del mismo punto)
            at = a if has_lap else ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            return [DimLabel(f"G {format_dimension(info.extension_mm)}", at, (0.0, -1.0), kind="hook")]
        return [DimLabel(f"G {format_dimension(info.extension_mm)}", tip, (0.0, -1.0), kind="hook") for info, tip in present]


@register_shape
@dataclass(frozen=True)
class Spiral(ShapeCode):
    """Espiral (hélice) con vueltas planas adicionales y ganchos opcionales en los extremos.

    ``diameter`` es el diámetro exterior, ``pitch`` el paso y ``height`` la altura exterior total. Con
    ``N = (H − d)/p`` vueltas de trabajo y ``turns_start``/``turns_end`` vueltas planas adicionales (sin paso) al
    inicio y al final (ACI 318 pide 1.5 en cada extremo)::

        L = N·√((π·(D − d))² + p²) + (turns_start + turns_end)·π·(D − d) + Σ (φ·R + extensión)

    Cada extremo admite además un gancho de 90° o 135°, que se dobla hacia el núcleo.
    """

    code: ClassVar[str] = "ES"
    name: ClassVar[str] = "Espiral"
    from_coil: ClassVar[bool] = True
    description: ClassVar[str] = (
        "Hélice continua con vueltas adicionales al inicio y al final y ganchos opcionales de 90° o 135° "
        "(refuerzo transversal de columnas circulares)."
    )

    diameter: float = param("A · diámetro exterior", default=400.0)
    pitch: float = param("B · paso", default=75.0)
    height: float = param("C · altura", default=2000.0)
    turns_start: float = param("Vueltas adicionales al inicio", "number", 1.5, minimum=0.0, maximum=5.0)
    turns_end: float = param("Vueltas adicionales al final", "number", 1.5, minimum=0.0, maximum=5.0)
    hook_start: int = param("Gancho inicial", "choice", 0, choices=RING_HOOK_CHOICES)
    ext_start: float | None = param("Extensión del gancho inicial", "length", None, optional=True)
    hook_end: int = param("Gancho final", "choice", 0, choices=RING_HOOK_CHOICES)
    ext_end: float | None = param("Extensión del gancho final", "length", None, optional=True)

    @classmethod
    def migrate(cls, parameters: dict[str, object]) -> dict[str, object]:
        migrated = dict(parameters)
        if "extra_turns" in migrated:  # antes: las mismas vueltas de anclaje en ambos extremos
            turns = migrated.pop("extra_turns")
            migrated.setdefault("turns_start", turns)
            migrated.setdefault("turns_end", turns)
        return migrated

    def dimensions(self) -> dict[str, float]:
        return {"A": self.diameter, "B": self.pitch, "C": self.height}

    def turns(self, rebar: Rebar) -> float:
        """Vueltas de trabajo (con paso) entre las vueltas adicionales de los extremos."""
        return (self.height - rebar.diameter_mm) / self.pitch

    def _specs(self) -> tuple[HookSpec | None, HookSpec | None]:
        return _hook(self.hook_start, self.ext_start), _hook(self.hook_end, self.ext_end)

    def cut_length(self, rebar: Rebar) -> CutLength:
        d = rebar.diameter_mm
        use = _round_use(rebar)
        _min_diameter_check(self.code, rebar, self.diameter, use)
        if self.pitch <= d:
            raise GeometryError(f"Forma {self.code}: el paso {self.pitch:g} mm debe ser mayor que el diámetro de la barra ({d:g} mm).")
        n = self.turns(rebar)
        if n < 1.0 - 1e-9:
            raise GeometryError(f"Forma {self.code}: la altura {self.height:g} mm no alcanza para una vuelta de paso {self.pitch:g} mm.")
        hooks = hook_allowance(rebar, use, self._specs())
        centre = math.pi * (self.diameter - d)
        flat = (self.turns_start + self.turns_end) * centre
        total = n * math.hypot(centre, self.pitch) + flat
        clear = self.pitch - d
        warnings = list(hooks.warnings)
        if clear < 25.0 - 1e-9 or clear > 75.0 + 1e-9:
            warnings.insert(0, f"Separación libre {clear:.0f} mm fuera del rango 25–75 mm (ACI 318 25.7.3.1)")
        return CutLength(
            dimension_sum_mm=total,
            bend_adjustment_mm=hooks.arc_mm,
            extension_mm=hooks.extension_mm,
            notes=(
                f"{n:.1f} vueltas + {self.turns_start:g} al inicio y {self.turns_end:g} al final"
                f" · Ø interior mínimo {rebar.bend_diameter_mm(use):.0f} mm",
            ),
            warnings=tuple(warnings),
            hooks=hooks.infos,
        )

    def sketch(self, rebar: Rebar | None = None) -> Sketch:
        width, height = proportional([self.diameter, self.height], 0.6)
        turns, steps, tail = 4.5, 180, 0.15
        # La hélice sube del extremo izquierdo al derecho; las vueltas adicionales se dibujan como anillos planos.
        helix = tuple((width / 2.0 * (1.0 - math.cos(2.0 * math.pi * turns * k / steps)), height * k / steps)
                      for k in range(steps + 1))
        bottom = ((0.0, 0.0), (width, 0.0), (0.0, 0.0)) if self.turns_start > 0 else ()
        top = ((width, height), (0.0, height), (width, height)) if self.turns_end > 0 else ()
        path = [*bottom, *helix, *top]
        labels = [
            DimLabel(dimension_text("A", self.diameter), (width / 2.0, 0.0), (0.0, -1.0)),
            DimLabel(dimension_text("B", self.pitch), (0.0, height / 2.0), (-1.0, 0.0)),
            DimLabel(dimension_text("C", self.height), (width, height / 2.0), (1.0, 0.0)),
        ]
        if self.turns_start > 0:
            labels.append(DimLabel(f"+{self.turns_start:g} vueltas", (width, 0.0), (1.0, 0.0), kind="angle"))
        if self.turns_end > 0:
            labels.append(DimLabel(f"+{self.turns_end:g} vueltas", (0.0, height), (-1.0, 0.0), kind="angle"))

        # Los ganchos se esbozan hacia afuera de los extremos (el esquema es una elevación: no muestra el plano del anillo).
        infos: list = [None, None]
        if rebar is not None:
            try:
                infos = [resolve_hook(rebar, _round_use(rebar), spec)[0] if spec else None for spec in self._specs()]
            except GeometryError:
                infos = [None, None]
        for slot, (angle, anchor, direction) in enumerate((
            (self.hook_start, (0.0, 0.0), lambda phi: 360.0 - phi),
            (self.hook_end, (width, height), lambda phi: 180.0 - phi),
        )):
            if not angle:
                continue
            heading = math.radians(direction(float(angle)))
            tip = (anchor[0] + tail * math.cos(heading), anchor[1] + tail * math.sin(heading))
            if slot == 0:
                path.insert(0, tip)
            else:
                path.append(tip)
            if infos[slot] is not None:
                labels.append(DimLabel(f"G {format_dimension(infos[slot].extension_mm)}", tip,
                                       (-1.0, 0.0) if slot == 0 else (1.0, 0.0), kind="hook"))
        return Sketch(paths=(tuple(path),), labels=tuple(labels))


# ------------------------------------------------------------------ personalizada
@register_shape
@dataclass(frozen=True)
class CustomBar(OpenPolyShape):
    """Forma dibujada a mano: tramos, ángulos de giro y ganchos opcionales en los extremos.

    ``legs`` son las cotas exteriores de cada tramo (de fuera a fuera, como en el resto del catálogo) y
    ``angles`` el giro en cada doblez entre tramos consecutivos: positivo = a la izquierda, negativo = a la
    derecha, entre 0° y 180° (excluidos). Debe haber un ángulo menos que tramos.
    """

    code: ClassVar[str] = "X"
    name: ClassVar[str] = "Personalizada"
    description: ClassVar[str] = "Defina usted los tramos, los ángulos de giro y los ganchos de la barra."

    legs: tuple[float, ...] = param("Tramos (cotas exteriores)", "lengths", (400.0, 300.0))
    angles: tuple[float, ...] = param("Giros", "angles", (90.0,), hidden=True)
    hook_start: int = param("Gancho inicial", "choice", 0, choices=HOOK_CHOICES)
    ext_start: float | None = param("Extensión del gancho inicial", "length", None, optional=True)
    hook_end: int = param("Gancho final", "choice", 0, choices=HOOK_CHOICES)
    ext_end: float | None = param("Extensión del gancho final", "length", None, optional=True)
    opposite: int = param("Orientación de los ganchos", "choice", 0, choices=SIDE_CHOICES)
    style: str = param("Estilo", "choice", "main", choices=STYLE_CHOICES)
    coupler_start: str = param("Coupler inicial (solo sin gancho)", "choice", "none", choices=COUPLER_CHOICES)
    coupler_end: str = param("Coupler final (solo sin gancho)", "choice", "none", choices=COUPLER_CHOICES)

    def validate(self) -> None:
        if len(self.angles) != len(self.legs) - 1:
            raise GeometryError(
                f"Forma {self.code}: {len(self.legs)} tramos necesitan {len(self.legs) - 1} ángulos de giro "
                f"(hay {len(self.angles)})."
            )

    def dimensions(self) -> dict[str, float]:
        return {LETTERS[i]: leg for i, leg in enumerate(self.legs[:26])}

    def poly(self) -> OpenPoly:
        return OpenPoly(self.legs, self.angles, _hook(self.hook_start, self.ext_start),
                        _hook(self.hook_end, self.ext_end), _use(self.style), bool(self.opposite), floor=0.15,
                        coupler_start=self.coupler_start, coupler_end=self.coupler_end)
