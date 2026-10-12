"""Biblioteca extensible de formas de doblado (shape codes) y cálculo de la longitud de corte.

Cada forma es un ``dataclass`` inmutable con sus cotas **exteriores** (de fuera a fuera
de la barra, ver :mod:`core.geometry`) y un método ``cut_length(rebar)`` que devuelve un
:class:`CutLength` con el desglose del cálculo, de modo que cada planilla sea auditable.

Cómo agregar una forma nueva::

    @register_shape
    @dataclass(frozen=True)
    class ZBar(ShapeCode):
        code: ClassVar[str] = "Z"
        name: ClassVar[str] = "Barra en Z"
        a: float
        b: float
        c: float

        def dimensions(self) -> dict[str, float]:
            return {"A": self.a, "B": self.b, "C": self.c}

        def cut_length(self, rebar: Rebar) -> CutLength:
            ...  # validar geometría y devolver CutLength(...)

La validación de que toda cota sea un número positivo es automática (``__post_init__``).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from typing import ClassVar, TypeVar

from core.geometry import GeometryError, bend_deduction, outside_tangent_length
from core.rebar import BendUse, HookType, Rebar
from core.sketch import DimLabel, Sketch, format_dimension, proportional

_EPS = 1e-6


@dataclass(frozen=True)
class CutLength:
    """Desglose de la longitud de corte (mm).

    ``total = suma de cotas exteriores + ajuste por dobleces + extensiones``. El ajuste
    por dobleces es negativo cuando la barra resulta más corta que la suma de cotas.
    """

    dimension_sum_mm: float
    bend_adjustment_mm: float = 0.0
    extension_mm: float = 0.0
    notes: tuple[str, ...] = ()  # información para el doblador (diámetro de mandril, etc.)
    warnings: tuple[str, ...] = ()  # incumplimientos no fatales de la norma

    @property
    def total_mm(self) -> float:
        return self.dimension_sum_mm + self.bend_adjustment_mm + self.extension_mm


@dataclass(frozen=True)
class ShapeCode(ABC):
    """Base de las formas de doblado. Las subclases deben ser ``@dataclass(frozen=True)``."""

    code: ClassVar[str]
    name: ClassVar[str]
    #: Rótulo de cada campo para formularios (p. ej. ``{"a": "A · tramo principal"}``).
    field_labels: ClassVar[dict[str, str]] = {}

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if value is None:  # campo opcional sin definir
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise GeometryError(
                    f"Forma {self.code}: '{f.name}' debe ser un número positivo en mm (recibido: {value!r})."
                )

    @property
    def label(self) -> str:
        return f"{self.code} · {self.name}"

    @abstractmethod
    def dimensions(self) -> dict[str, float]:
        """Cotas exteriores rotuladas ("A", "B", ...) tal como aparecen en la planilla."""

    @abstractmethod
    def cut_length(self, rebar: Rebar) -> CutLength:
        """Longitud de corte para ``rebar``. Lanza :class:`GeometryError` si la forma es imposible."""

    def sketch(self) -> Sketch:
        """Esquema de la forma para planillas e interfaz. Por defecto, una línea con las cotas rotuladas."""
        text = "  ".join(f"{label}={format_dimension(value)}" for label, value in self.dimensions().items())
        return Sketch(paths=(((0.0, 0.0), (1.0, 0.0)),), labels=(DimLabel(text, (0.5, 0.0), (0.0, 1.0)),))


# ------------------------------------------------------------------- registro
_SHAPE_REGISTRY: dict[str, type[ShapeCode]] = {}
_S = TypeVar("_S", bound=type[ShapeCode])


def register_shape(cls: _S) -> _S:
    """Decorador que registra una forma por su ``code`` para poder crearla con :func:`create_shape`."""
    code = getattr(cls, "code", None)
    if not isinstance(code, str) or not code:
        raise TypeError(f"{cls.__name__} debe definir 'code' (ClassVar[str]).")
    if code in _SHAPE_REGISTRY and _SHAPE_REGISTRY[code] is not cls:
        raise ValueError(f"El código de forma {code!r} ya está registrado por {_SHAPE_REGISTRY[code].__name__}.")
    _SHAPE_REGISTRY[code] = cls
    return cls


def available_shapes() -> dict[str, type[ShapeCode]]:
    """Formas registradas, por código."""
    return dict(_SHAPE_REGISTRY)


def create_shape(code: str, **dimensions: float) -> ShapeCode:
    """Crea una forma por código, p. ej. ``create_shape("L", a=1200, b=300)``."""
    try:
        cls = _SHAPE_REGISTRY[code]
    except KeyError:
        raise KeyError(f"Forma {code!r} no registrada (disponibles: {', '.join(_SHAPE_REGISTRY)}).") from None
    return cls(**dimensions)


def _require_min(rebar: Rebar, shape: ShapeCode, label: str, value: float, minimum: float) -> None:
    if value < minimum - _EPS:
        raise GeometryError(
            f"Forma {shape.code} con {rebar.designation}: la cota {label} = {value:g} mm es menor que el "
            f"mínimo geométrico de {minimum:.1f} mm (radio de doblez + diámetro de barra)."
        )


# ---------------------------------------------------------------------- formas
@register_shape
@dataclass(frozen=True)
class StraightBar(ShapeCode):
    """Barra recta. ``length`` es la longitud total."""

    code: ClassVar[str] = "R"
    name: ClassVar[str] = "Recta"

    field_labels: ClassVar[dict[str, str]] = {"length": "A · longitud total"}

    length: float

    def dimensions(self) -> dict[str, float]:
        return {"A": self.length}

    def sketch(self) -> Sketch:
        return Sketch(
            paths=(((0.0, 0.0), (1.0, 0.0)),),
            labels=(DimLabel(format_dimension(self.length), (0.5, 0.0), (0.0, 1.0)),),
        )

    def cut_length(self, rebar: Rebar) -> CutLength:
        return CutLength(dimension_sum_mm=self.length)


@register_shape
@dataclass(frozen=True)
class LBar(ShapeCode):
    """Bastón en L: un doblez de 90°. ``a`` = tramo principal y ``b`` = tramo del gancho, ambos exteriores."""

    code: ClassVar[str] = "L"
    name: ClassVar[str] = "Bastón L"

    field_labels: ClassVar[dict[str, str]] = {"a": "A · tramo principal", "b": "B · tramo del gancho"}

    a: float
    b: float

    @classmethod
    def with_standard_hook(cls, rebar: Rebar, a: float) -> LBar:
        """L cuyo tramo ``b`` es el gancho estándar de 90° de ``rebar`` (12d de extensión)."""
        return cls(a=a, b=rebar.standard_hook(HookType.DEG_90).outside_leg_mm)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b}

    def sketch(self) -> Sketch:
        ra, rb = proportional([self.a, self.b])
        return Sketch(
            paths=(((0.0, 0.0), (ra, 0.0), (ra, rb)),),
            labels=(
                DimLabel(format_dimension(self.a), (ra / 2, 0.0), (0.0, -1.0)),
                DimLabel(format_dimension(self.b), (ra, rb / 2), (1.0, 0.0)),
            ),
        )

    def cut_length(self, rebar: Rebar) -> CutLength:
        d = rebar.diameter_mm
        r = rebar.bend_radius_mm(BendUse.MAIN)
        tangent = outside_tangent_length(90.0, r, d)
        _require_min(rebar, self, "A", self.a, tangent)
        _require_min(rebar, self, "B", self.b, tangent)
        return CutLength(
            dimension_sum_mm=self.a + self.b,
            bend_adjustment_mm=-bend_deduction(90.0, r, d),
            notes=(f"1 doblez 90° · Ø interior {2 * r:.0f} mm",),
        )


@register_shape
@dataclass(frozen=True)
class UBar(ShapeCode):
    """Gancho en U: dos dobleces de 90° del mismo lado.

    ``a`` = base y ``b``, ``c`` = patas; las tres cotas son exteriores (la base se mide de
    cara exterior a cara exterior de las patas).
    """

    code: ClassVar[str] = "U"
    name: ClassVar[str] = "Gancho U"

    field_labels: ClassVar[dict[str, str]] = {"a": "A · base", "b": "B · pata izquierda", "c": "C · pata derecha"}

    a: float
    b: float
    c: float

    @classmethod
    def with_standard_hooks(cls, rebar: Rebar, a: float) -> UBar:
        """U cuyas patas son ganchos estándar de 90° de ``rebar`` (12d de extensión)."""
        leg = rebar.standard_hook(HookType.DEG_90).outside_leg_mm
        return cls(a=a, b=leg, c=leg)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b, "C": self.c}

    def sketch(self) -> Sketch:
        ra, rb, rc = proportional([self.a, self.b, self.c])
        return Sketch(
            paths=(((0.0, rb), (0.0, 0.0), (ra, 0.0), (ra, rc)),),
            labels=(
                DimLabel(format_dimension(self.a), (ra / 2, 0.0), (0.0, -1.0)),
                DimLabel(format_dimension(self.b), (0.0, rb / 2), (-1.0, 0.0)),
                DimLabel(format_dimension(self.c), (ra, rc / 2), (1.0, 0.0)),
            ),
        )

    def cut_length(self, rebar: Rebar) -> CutLength:
        d = rebar.diameter_mm
        r = rebar.bend_radius_mm(BendUse.MAIN)
        tangent = outside_tangent_length(90.0, r, d)
        _require_min(rebar, self, "A", self.a, 2.0 * tangent)  # la base consume una tangente en cada extremo
        _require_min(rebar, self, "B", self.b, tangent)
        _require_min(rebar, self, "C", self.c, tangent)
        return CutLength(
            dimension_sum_mm=self.a + self.b + self.c,
            bend_adjustment_mm=-2.0 * bend_deduction(90.0, r, d),
            notes=(f"2 dobleces 90° · Ø interior {2 * r:.0f} mm",),
        )


@register_shape
@dataclass(frozen=True)
class Stirrup135(ShapeCode):
    """Estribo rectangular cerrado con dos ganchos sísmicos de 135° en una misma esquina.

    ``a`` x ``b`` son las cotas exteriores (ancho x alto, de cara exterior a cara exterior de
    la barra); el recubrimiento ya está descontado. ``hook_extension_mm`` es la extensión
    recta de cada gancho; si se omite se usa la estándar (mayor de 6d y 75 mm).

    Geometría al eje (rectángulo ``W x H`` con ``W = a − d``, ``H = b − d``, radio al eje
    ``R = D/2 + d/2``, ``D`` = diámetro interior de doblez del estribo)::

        4 tramos rectos            2W + 2H − 8R
        3 dobleces de 90°          3·(π/2)·R
        2 dobleces de 135°         2·(3π/4)·R
        2 extensiones              2·ext

    Se supone que cada gancho nace en la tangente de la esquina de cierre, de modo que la
    extensión penetra al núcleo a 45°. Total: ``2(a+b) + [(3π − 8)·R − 4d] + 2·ext``.
    """

    code: ClassVar[str] = "E"
    name: ClassVar[str] = "Estribo 135°"

    field_labels: ClassVar[dict[str, str]] = {
        "a": "A · ancho exterior",
        "b": "B · alto exterior",
        "hook_extension_mm": "Extensión del gancho",
    }

    a: float
    b: float
    hook_extension_mm: float | None = None

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b}

    def sketch(self) -> Sketch:
        w, h = proportional([self.a, self.b], 0.4)
        tail, gap = 0.2 * min(w, h), 0.12 * min(w, h)
        # Ambos ganchos parten de la esquina superior izquierda y entran al núcleo a 45°.
        path = ((tail, h - tail), (0.0, h), (0.0, 0.0), (w, 0.0), (w, h), (gap, h), (gap + tail, h - tail))
        return Sketch(
            paths=(path,),
            labels=(
                DimLabel(format_dimension(self.a), (w / 2, 0.0), (0.0, -1.0)),
                DimLabel(format_dimension(self.b), (w, h / 2), (1.0, 0.0)),
            ),
        )

    def cut_length(self, rebar: Rebar) -> CutLength:
        d = rebar.diameter_mm
        bend_d = rebar.bend_diameter_mm(BendUse.STIRRUP)
        radius = rebar.centerline_radius_mm(BendUse.STIRRUP)
        hook = rebar.standard_hook(HookType.DEG_135, BendUse.STIRRUP)

        # Cada lado debe conservar un tramo recto ≥ 0 entre sus dos dobleces: a − 2d ≥ D.
        _require_min(rebar, self, "A", self.a, bend_d + 2.0 * d)
        _require_min(rebar, self, "B", self.b, bend_d + 2.0 * d)

        extension = hook.extension_mm if self.hook_extension_mm is None else self.hook_extension_mm
        warnings: tuple[str, ...] = ()
        if extension < hook.extension_mm - _EPS:
            warnings = (
                f"Extensión de gancho {extension:.0f} mm < mínimo normativo {hook.extension_mm:.0f} mm "
                f"(mayor de 6d y 75 mm)",
            )
        return CutLength(
            dimension_sum_mm=2.0 * (self.a + self.b),
            bend_adjustment_mm=(3.0 * math.pi - 8.0) * radius - 4.0 * d,
            extension_mm=2.0 * extension,
            notes=(f"2 ganchos 135° · ext. {extension:.0f} mm · Ø interior {bend_d:.0f} mm",),
            warnings=warnings,
        )
