"""Catálogo de plantillas de formas de doblado.

Se organiza como el modelo de formas de Revit: cada forma es de **estilo** «barra» o «estribo/ligadura»
(que decide el diámetro de doblez y los ganchos estándar) y sus extremos admiten ganchos de 90°, 135° o 180°.

=======  ==============================================  ==========================================
Código   Plantilla                                       Familia
=======  ==============================================  ==========================================
``R``    Recta                                           polilínea (en ``shape_codes``)
``L``    Bastón L                                        polilínea (en ``shape_codes``)
``U``    Gancho U                                        polilínea (en ``shape_codes``)
``E``    Estribo 135°                                    polígono cerrado (en ``shape_codes``)
``E90``  Estribo 90°                                     polígono cerrado (en ``shape_codes``)
``G``    Barra con ganchos (0/90/135/180° en cada punta) polilínea
``EU``   Estribo abierto en U con ganchos 90°/135°        polilínea
``Z``    Barra en Z                                      polilínea
``Q``    Quiebre (barra con tramo inclinado)             polilínea
``O``    Omega (Ω)                                       polilínea
``ET``   Estribo triangular                              polígono cerrado
``ETR``  Estribo trapezoidal                             polígono cerrado
``AR``   Aro circular con traslape                       geometría propia
``ES``   Espiral                                         geometría propia
``X``    Personalizada (tramos y ángulos a mano)         polilínea
=======  ==============================================  ==========================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

from core.cutlength import CutLength
from core.geometry import GeometryError
from core.params import param
from core.polybar import LETTERS, ClosedPoly, HookSpec, OpenPoly
from core.rebar import BendUse, Rebar
from core.shape_codes import ClosedPolyShape, OpenPolyShape, ShapeCode, register_shape
from core.sketch import DimLabel, Sketch, format_dimension, proportional

HOOK_CHOICES = ((0, "Sin gancho"), (90, "90°"), (135, "135°"), (180, "180°"))
STIRRUP_HOOK_CHOICES = ((90, "90°"), (135, "135°"))
STYLE_CHOICES = (("main", "Barra"), ("stirrup", "Estribo / ligadura"))
SIDE_CHOICES = ((0, "Mismo lado"), (1, "Lados opuestos"))


def _use(style: str) -> BendUse:
    return BendUse.STIRRUP if style == "stirrup" else BendUse.MAIN


def _hook(angle: int, extension: float | None) -> HookSpec | None:
    return HookSpec(float(angle), extension) if angle else None


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

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.a,), (), _hook(self.hook_start, self.ext_start), _hook(self.hook_end, self.ext_end),
                        _use(self.style), bool(self.opposite))


@register_shape
@dataclass(frozen=True)
class UStirrup(OpenPolyShape):
    """Estribo abierto en U (grapa) con ganchos de 90° o 135° en los extremos libres."""

    code: ClassVar[str] = "EU"
    name: ClassVar[str] = "Estribo en U"
    description: ClassVar[str] = "Estribo abierto en U (grapa) con ganchos a 90° o 135° en las puntas."

    a: float = param("A · ancho exterior", default=300.0)
    b: float = param("B · alto exterior", default=400.0)
    hook: int = param("Gancho de las puntas", "choice", 135, choices=STIRRUP_HOOK_CHOICES)
    hook_extension_mm: float | None = param("Extensión del gancho", "length", None, optional=True)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b}

    def poly(self) -> OpenPoly:
        spec = HookSpec(float(self.hook), self.hook_extension_mm)
        return OpenPoly((self.b, self.a, self.b), (90.0, 90.0), spec, spec, BendUse.STIRRUP, start_heading=-90.0)


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

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b, "C": self.c}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.a, self.b, self.c), (90.0, -90.0), use=_use(self.style))


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

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b, "C": self.c}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.a, self.b, self.c), (self.angle, -self.angle), use=_use(self.style))

    def cut_length(self, rebar: Rebar) -> CutLength:
        cut = super().cut_length(rebar)
        half = math.tan(math.radians(self.angle) / 2.0)
        rise = (self.b - rebar.diameter_mm * half) * math.sin(math.radians(self.angle)) + rebar.diameter_mm
        return CutLength(cut.dimension_sum_mm, cut.bend_adjustment_mm, cut.extension_mm,
                         cut.notes + (f"Desnivel exterior {rise:.0f} mm",), cut.warnings, cut.hooks)


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

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b, "C": self.c, "D": self.d, "E": self.e}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.a, self.b, self.c, self.d, self.e), (90.0, -90.0, -90.0, 90.0), use=_use(self.style))


# ---------------------------------------------------------- polígonos cerrados
@register_shape
@dataclass(frozen=True)
class TriStirrup(ClosedPolyShape):
    """Estribo triangular cerrado definido por sus tres lados exteriores, con ganchos de 90° o 135°."""

    code: ClassVar[str] = "ET"
    name: ClassVar[str] = "Estribo triangular"
    description: ClassVar[str] = "Estribo cerrado de tres lados (ángulos internos distintos de 90°)."

    a: float = param("A · lado 1", default=300.0)
    b: float = param("B · lado 2", default=300.0)
    c: float = param("C · lado 3", default=300.0)
    hook: int = param("Gancho de cierre", "choice", 135, choices=STIRRUP_HOOK_CHOICES)
    hook_extension_mm: float | None = param("Extensión del gancho", "length", None, optional=True)

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
        return ClosedPoly((self.a, self.b, self.c), turns, HookSpec(float(self.hook), self.hook_extension_mm))


@register_shape
@dataclass(frozen=True)
class TrapStirrup(ClosedPolyShape):
    """Estribo trapezoidal cerrado (trapecio isósceles) con ganchos de 90° o 135°."""

    code: ClassVar[str] = "ETR"
    name: ClassVar[str] = "Estribo trapezoidal"
    description: ClassVar[str] = "Estribo cerrado de cuatro lados con dos ángulos internos distintos de 90°."

    bottom: float = param("A · base mayor", default=400.0)
    top: float = param("B · base menor", default=250.0)
    height: float = param("C · altura", default=300.0)
    hook: int = param("Gancho de cierre", "choice", 135, choices=STIRRUP_HOOK_CHOICES)
    hook_extension_mm: float | None = param("Extensión del gancho", "length", None, optional=True)

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
                          HookSpec(float(self.hook), self.hook_extension_mm))


# ----------------------------------------------------------- geometría propia
def _arc(center: tuple[float, float], radius: float, start_deg: float, end_deg: float, steps: int = 48):
    return tuple((center[0] + radius * math.cos(math.radians(start_deg + (end_deg - start_deg) * k / steps)),
                  center[1] + radius * math.sin(math.radians(start_deg + (end_deg - start_deg) * k / steps)))
                 for k in range(steps + 1))


def _round_use(rebar: Rebar) -> BendUse:
    """Aros y espirales usan el doblez de estribo cuando la norma lo define (hasta #8)."""
    return BendUse.STIRRUP if rebar.bar_number <= 8 else BendUse.MAIN


@register_shape
@dataclass(frozen=True)
class RingTie(ShapeCode):
    """Aro circular (estribo circular) cerrado con traslape. Equivale al código 75 de BS 8666.

    ``diameter`` es el diámetro exterior (de cara exterior a cara exterior) y ``lap`` el traslape.
    Longitud al eje: ``π·(D − d) + lap``.
    """

    code: ClassVar[str] = "AR"
    name: ClassVar[str] = "Aro circular"
    description: ClassVar[str] = "Estribo circular de una vuelta con traslape (columnas circulares, pilotes)."

    diameter: float = param("A · diámetro exterior", default=400.0)
    lap: float = param("B · traslape", default=250.0)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.diameter, "B": self.lap}

    def cut_length(self, rebar: Rebar) -> CutLength:
        d = rebar.diameter_mm
        use = _round_use(rebar)
        minimum = rebar.bend_diameter_mm(use) + 2.0 * d
        if self.diameter < minimum - 1e-6:
            raise GeometryError(
                f"Forma {self.code} con {rebar.designation}: el diámetro A = {self.diameter:g} mm es menor que el "
                f"mínimo geométrico de {minimum:.1f} mm (Ø de doblez + 2 diámetros de barra)."
            )
        perimeter = math.pi * self.diameter
        return CutLength(
            dimension_sum_mm=perimeter + self.lap,
            bend_adjustment_mm=-math.pi * d,
            notes=(f"Traslape {self.lap:.0f} mm · Ø interior mínimo {rebar.bend_diameter_mm(use):.0f} mm",),
        )

    def sketch(self, rebar: Rebar | None = None) -> Sketch:
        lap_deg = max(25.0, min(90.0, 360.0 * self.lap / (math.pi * self.diameter)))
        start = 90.0
        outer = _arc((0.0, 0.0), 1.0, start, start + 360.0)
        inner = _arc((0.0, 0.0), 0.8, start, start + lap_deg, 16)
        middle = math.radians(start + lap_deg / 2.0)
        return Sketch(
            paths=(outer, inner),
            labels=(
                DimLabel(f"D {format_dimension(self.diameter)}", (0.0, -1.0), (0.0, -1.0)),
                DimLabel(f"T {format_dimension(self.lap)}", (math.cos(middle), math.sin(middle)),
                         (math.cos(middle), math.sin(middle)), kind="hook"),
            ),
        )


@register_shape
@dataclass(frozen=True)
class Spiral(ShapeCode):
    """Espiral (hélice) con vueltas de anclaje en los extremos.

    ``diameter`` es el diámetro exterior, ``pitch`` el paso y ``height`` la altura exterior total. Con
    ``N = (H − d)/p`` vueltas de trabajo y ``extra_turns`` vueltas planas de anclaje en cada extremo
    (ACI 318: 1.5)::

        L = N·√((π·(D − d))² + p²) + 2·extra_turns·π·(D − d)
    """

    code: ClassVar[str] = "ES"
    name: ClassVar[str] = "Espiral"
    from_coil: ClassVar[bool] = True
    description: ClassVar[str] = "Hélice continua con vueltas de anclaje (refuerzo transversal de columnas circulares)."

    diameter: float = param("A · diámetro exterior", default=400.0)
    pitch: float = param("B · paso", default=75.0)
    height: float = param("C · altura", default=2000.0)
    extra_turns: float = param("Vueltas de anclaje por extremo", "number", 1.5, minimum=0.0, maximum=5.0)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.diameter, "B": self.pitch, "C": self.height}

    def turns(self, rebar: Rebar) -> float:
        return (self.height - rebar.diameter_mm) / self.pitch

    def cut_length(self, rebar: Rebar) -> CutLength:
        d = rebar.diameter_mm
        use = _round_use(rebar)
        minimum = rebar.bend_diameter_mm(use) + 2.0 * d
        if self.diameter < minimum - 1e-6:
            raise GeometryError(
                f"Forma {self.code} con {rebar.designation}: el diámetro A = {self.diameter:g} mm es menor que el "
                f"mínimo geométrico de {minimum:.1f} mm (Ø de doblez + 2 diámetros de barra)."
            )
        if self.pitch <= d:
            raise GeometryError(f"Forma {self.code}: el paso {self.pitch:g} mm debe ser mayor que el diámetro de la barra ({d:g} mm).")
        n = self.turns(rebar)
        if n < 1.0 - 1e-9:
            raise GeometryError(f"Forma {self.code}: la altura {self.height:g} mm no alcanza para una vuelta de paso {self.pitch:g} mm.")
        centre = math.pi * (self.diameter - d)
        total = n * math.hypot(centre, self.pitch) + 2.0 * self.extra_turns * centre
        clear = self.pitch - d
        warnings = ()
        if clear < 25.0 - 1e-9 or clear > 75.0 + 1e-9:
            warnings = (f"Separación libre {clear:.0f} mm fuera del rango 25–75 mm (ACI 318 25.7.3.1)",)
        return CutLength(
            dimension_sum_mm=total,
            notes=(f"{n:.1f} vueltas + 2 × {self.extra_turns:g} de anclaje · Ø interior mínimo {rebar.bend_diameter_mm(use):.0f} mm",),
            warnings=warnings,
        )

    def sketch(self, rebar: Rebar | None = None) -> Sketch:
        width, height = proportional([self.diameter, self.height], 0.45)
        turns, steps = 4, 160
        points = tuple((width / 2.0 * (1.0 + math.cos(2.0 * math.pi * turns * k / steps)), height * k / steps)
                       for k in range(steps + 1))
        return Sketch(
            paths=(points,),
            labels=(
                DimLabel(f"D {format_dimension(self.diameter)}", (width / 2.0, 0.0), (0.0, -1.0)),
                DimLabel(f"H {format_dimension(self.height)}", (width, height / 2.0), (1.0, 0.0)),
                DimLabel(f"p {format_dimension(self.pitch)}", (0.0, height / 2.0), (-1.0, 0.0), kind="hook"),
            ),
        )


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
                        _hook(self.hook_end, self.ext_end), _use(self.style), bool(self.opposite), floor=0.15)
