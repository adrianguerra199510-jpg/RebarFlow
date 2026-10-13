"""Biblioteca extensible de formas de doblado (shape codes) y cálculo de la longitud de corte.

Cada forma es un ``dataclass`` inmutable con sus cotas **exteriores** (de fuera a fuera de la barra, ver
:mod:`core.polybar`) y un método ``cut_length(rebar)`` que devuelve un :class:`~core.cutlength.CutLength`
con el desglose del cálculo, de modo que cada planilla sea auditable.

Este módulo define la base, el registro y las formas históricas (``R``, ``L``, ``U``, ``E``); el resto del
catálogo (ganchos, estribo en U, Z, quiebres, omegas, polígonos, espirales, aros y la forma personalizada)
está en :mod:`core.shape_templates`.

Cómo agregar una forma nueva (la más simple: una polilínea)::

    @register_shape
    @dataclass(frozen=True)
    class StepBar(OpenPolyShape):
        code: ClassVar[str] = "ST"
        name: ClassVar[str] = "Escalón"
        a: float = param("A · tramo inferior", default=300.0)
        b: float = param("B · altura", default=150.0)
        c: float = param("C · tramo superior", default=300.0)

        def dimensions(self) -> dict[str, float]:
            return {"A": self.a, "B": self.b, "C": self.c}

        def poly(self) -> OpenPoly:
            return OpenPoly((self.a, self.b, self.c), (90.0, -90.0))

La validación de los parámetros (``param``) es automática y el formulario de la interfaz se genera solo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, fields, replace
from typing import ClassVar, TypeVar

from core.coupler import COUPLER_CHOICES  # noqa: F401 (se reexporta)
from core.cutlength import CutLength, HookInfo, Supply  # noqa: F401 (se reexportan)
from core.geometry import GeometryError  # noqa: F401
from core.params import DEFAULT_LENGTH_MM, ParamSpec, param, validate_param  # noqa: F401
from core.polybar import (  # noqa: F401
    ClosedPoly,
    HookSpec,
    OpenPoly,
    analyse_closed,
    analyse_open,
    closed_polygon_sketch,
    open_polyline_sketch,
)
from core.rebar import BendUse, HookType, Rebar
from core.sketch import DimLabel, Sketch, format_dimension

_EPS = 1e-6

#: Opciones de los formularios: ganchos de barra, de estribo y de aros/espirales, estilo y orientación.
HOOK_CHOICES = ((0, "Sin gancho"), (90, "90°"), (135, "135°"), (180, "180°"))
STIRRUP_HOOK_CHOICES = ((90, "90°"), (135, "135°"))
RING_HOOK_CHOICES = ((0, "Sin gancho"), (90, "90°"), (135, "135°"))
STYLE_CHOICES = (("main", "Barra"), ("stirrup", "Estribo / ligadura"))
SIDE_CHOICES = ((0, "Mismo lado"), (1, "Lados opuestos"))


def hook_spec(angle: int, extension: float | None) -> HookSpec | None:
    """Gancho pedido en un extremo: ``angle`` 0 = sin gancho; ``extension`` ``None`` = la estándar de la norma."""
    return HookSpec(float(angle), extension) if angle else None


def migrate_single_hook(parameters: dict[str, object]) -> dict[str, object]:
    """Pasa los parámetros de los estribos antiguos (un solo ``hook`` y ``hook_extension_mm`` para ambas patas)
    a los actuales (gancho y extensión del inicio y del final por separado)."""
    migrated = dict(parameters)
    if "hook" in migrated:
        hook = migrated.pop("hook")
        migrated.setdefault("hook_start", hook)
        migrated.setdefault("hook_end", hook)
    if "hook_extension_mm" in migrated:
        extension = migrated.pop("hook_extension_mm")
        migrated.setdefault("ext_start", extension)
        migrated.setdefault("ext_end", extension)
    return migrated


@dataclass(frozen=True)
class ShapeCode(ABC):
    """Base de las formas de doblado. Las subclases deben ser ``@dataclass(frozen=True)``."""

    code: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    #: Verdadero si la pieza se fabrica de rollo (espirales): no sale de barras comerciales ni tiene retales.
    from_coil: ClassVar[bool] = False
    #: Rótulo de cada campo declarado sin :func:`param` (p. ej. ``{"a": "A · tramo principal"}``).
    field_labels: ClassVar[dict[str, str]] = {}

    @classmethod
    def parameters(cls) -> tuple[ParamSpec, ...]:
        """Parámetros de la forma, en el orden de sus campos."""
        specs = []
        for f in fields(cls):
            spec = f.metadata.get("spec")
            if spec is None:  # campo histórico: una cota en mm, opcional si su valor por defecto es None
                optional = f.default is None
                spec = ParamSpec(f.name, cls.field_labels.get(f.name, f.name.upper()), "length",
                                 None if optional else DEFAULT_LENGTH_MM, optional=optional)
            else:
                spec = replace(spec, name=f.name)
            specs.append(spec)
        return tuple(specs)

    @classmethod
    def template(cls) -> ShapeCode:
        """Instancia con los valores por defecto de la plantilla."""
        return cls(**{spec.name: spec.default for spec in cls.parameters()})

    @classmethod
    def migrate(cls, parameters: dict[str, object]) -> dict[str, object]:
        """Adapta parámetros de versiones anteriores de la forma (al abrir proyectos guardados); por defecto, no cambia nada."""
        return parameters

    def __post_init__(self) -> None:
        for spec in self.parameters():
            value = getattr(self, spec.name)
            checked = validate_param(self.code, spec, value)
            if spec.kind in ("lengths", "angles") or checked != value:
                object.__setattr__(self, spec.name, checked)
        self.validate()

    def validate(self) -> None:
        """Validaciones entre campos; las subclases pueden sobrescribirla y lanzar :class:`GeometryError`."""

    @property
    def label(self) -> str:
        return f"{self.code} · {self.name}"

    @abstractmethod
    def dimensions(self) -> dict[str, float]:
        """Cotas exteriores rotuladas ("A", "B", ...) tal como aparecen en la planilla."""

    @abstractmethod
    def cut_length(self, rebar: Rebar) -> CutLength:
        """Longitud de corte para ``rebar``. Lanza :class:`GeometryError` si la forma es imposible."""

    def supply(self, rebar: Rebar, stock_length_mm: float) -> Supply:
        """Barras que se cortan para una unidad de la forma, dada la longitud de la barra comercial.

        Por defecto, una sola barra del largo de corte (de rollo si ``from_coil``); una forma que pueda armarse con
        varias barras unidas lo sobrescribe.
        """
        return Supply((self.cut_length(rebar).total_mm,), coil=type(self).from_coil)

    def sketch(self, rebar: Rebar | None = None) -> Sketch:
        """Esquema para planillas e interfaz; con ``rebar`` incluye el largo de los ganchos.

        Por defecto, una línea con las cotas rotuladas.
        """
        text = "  ".join(f"{label}={format_dimension(value)}" for label, value in self.dimensions().items())
        return Sketch(paths=(((0.0, 0.0), (1.0, 0.0)),), labels=(DimLabel(text, (0.5, 0.0), (0.0, 1.0)),))


@dataclass(frozen=True)
class OpenPolyShape(ShapeCode):
    """Forma cuyo eje es una polilínea abierta (con ganchos opcionales). Basta definir :meth:`poly`."""

    @abstractmethod
    def poly(self) -> OpenPoly:
        """Tramos, ángulos y ganchos de la forma."""

    def cut_length(self, rebar: Rebar) -> CutLength:
        return analyse_open(self.code, self.poly(), rebar).cut

    def sketch(self, rebar: Rebar | None = None) -> Sketch:
        return open_polyline_sketch(self.code, self.poly(), rebar)


@dataclass(frozen=True)
class ClosedPolyShape(ShapeCode):
    """Estribo poligonal cerrado con dos ganchos en el vértice de cierre. Basta definir :meth:`poly`."""

    @abstractmethod
    def poly(self) -> ClosedPoly:
        """Lados, giros y gancho de la forma."""

    def cut_length(self, rebar: Rebar) -> CutLength:
        return analyse_closed(self.code, self.poly(), rebar)

    def sketch(self, rebar: Rebar | None = None) -> Sketch:
        return closed_polygon_sketch(self.code, self.poly(), rebar)


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


#: Códigos retirados del catálogo y la forma que los reemplaza, con los parámetros que reproducen la anterior.
_LEGACY_SHAPES: dict[str, tuple[str, dict[str, object]]] = {
    "E90": ("E", {"hook_start": 90, "hook_end": 90}),  # el estribo de 90° es el estribo único con patas a 90°
}


def create_shape(code: str, **parameters: object) -> ShapeCode:
    """Crea una forma por código, p. ej. ``create_shape("L", a=1200, b=300)``.

    Acepta los códigos y parámetros de versiones anteriores (``E90``, ``hook``…) y los convierte a los actuales.
    """
    if code in _LEGACY_SHAPES:
        code, defaults = _LEGACY_SHAPES[code]
        parameters = {**defaults, **parameters}
    try:
        cls = _SHAPE_REGISTRY[code]
    except KeyError:
        raise KeyError(f"Forma {code!r} no registrada (disponibles: {', '.join(_SHAPE_REGISTRY)}).") from None
    return cls(**cls.migrate(parameters))


# ---------------------------------------------------------------------- formas
@register_shape
@dataclass(frozen=True)
class StraightBar(OpenPolyShape):
    """Barra recta. ``length`` es la longitud total."""

    code: ClassVar[str] = "R"
    name: ClassVar[str] = "Recta"
    description: ClassVar[str] = "Barra recta sin dobleces; admite un coupler (rosca corta o larga) en cada extremo."

    field_labels: ClassVar[dict[str, str]] = {"length": "A · longitud total"}

    length: float
    coupler_start: str = param("Coupler inicial", "choice", "none", choices=COUPLER_CHOICES)
    coupler_end: str = param("Coupler final", "choice", "none", choices=COUPLER_CHOICES)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.length}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.length,), coupler_start=self.coupler_start, coupler_end=self.coupler_end)


@register_shape
@dataclass(frozen=True)
class LBar(OpenPolyShape):
    """Bastón en L: un doblez de 90°. ``a`` = tramo principal y ``b`` = tramo del gancho, ambos exteriores."""

    code: ClassVar[str] = "L"
    name: ClassVar[str] = "Bastón L"
    description: ClassVar[str] = "Un doblez a 90°; la pata corta actúa de gancho. El otro extremo admite coupler."

    field_labels: ClassVar[dict[str, str]] = {"a": "A · tramo principal", "b": "B · tramo del gancho"}

    a: float
    b: float
    coupler_start: str = param("Coupler en el extremo de A", "choice", "none", choices=COUPLER_CHOICES)

    @classmethod
    def with_standard_hook(cls, rebar: Rebar, a: float) -> LBar:
        """L cuyo tramo ``b`` es el gancho estándar de 90° de ``rebar`` (12d de extensión)."""
        return cls(a=a, b=rebar.standard_hook(HookType.DEG_90).outside_leg_mm)

    def dimensions(self) -> dict[str, float]:
        return {"A": self.a, "B": self.b}

    def poly(self) -> OpenPoly:
        return OpenPoly((self.a, self.b), (90.0,), end_hooks=(False, True), coupler_start=self.coupler_start)


@register_shape
@dataclass(frozen=True)
class UBar(OpenPolyShape):
    """Gancho en U: dos dobleces de 90° del mismo lado.

    ``a`` = base y ``b``, ``c`` = patas; las tres cotas son exteriores (la base se mide de
    cara exterior a cara exterior de las patas).
    """

    code: ClassVar[str] = "U"
    name: ClassVar[str] = "Gancho U"
    description: ClassVar[str] = "Dos dobleces a 90° del mismo lado; las patas actúan de ganchos."

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

    def poly(self) -> OpenPoly:
        return OpenPoly((self.b, self.a, self.c), (90.0, 90.0), end_hooks=(True, True), start_heading=-90.0,
                        names=("B", "A", "C"))


@register_shape
@dataclass(frozen=True)
class Stirrup(ClosedPolyShape):
    """Estribo rectangular cerrado con una pata (gancho) en cada extremo, de 90° o 135° a elección.

    ``a`` x ``b`` son las cotas exteriores (ancho x alto, de cara exterior a cara exterior de la barra); el
    recubrimiento ya está descontado. Las dos patas nacen en la misma esquina de cierre: ``hook_start`` es el
    gancho con que empieza la barra y ``hook_end`` el con que termina (por defecto, ambos de 135°, el gancho
    sísmico). ``ext_start`` y ``ext_end`` son las extensiones rectas de cada pata; si se omiten se usa la estándar
    (mayor de 6d y 75 mm en 135°; igual en 90° para #3–#5 y 12d para #6–#8).

    Geometría al eje (rectángulo ``W x H``, ``W = a − d``, ``H = b − d``, radio al eje ``R``)::

        4 tramos rectos            2W + 2H − 8R
        3 dobleces de 90°          3·(π/2)·R
        2 ganchos de φ₁ y φ₂       (φ₁ + φ₂)·R
        2 extensiones              ext₁ + ext₂

    Se supone que cada gancho nace en la tangente de la esquina de cierre. Con φ₁ = φ₂ = 135° el total es
    ``2(a+b) + [(3π − 8)·R − 4d] + ext₁ + ext₂``.
    """

    code: ClassVar[str] = "E"
    name: ClassVar[str] = "Estribo rectangular"
    description: ClassVar[str] = "Estribo rectangular cerrado; cada pata (inicio y final) con gancho de 90° o 135°."

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

    def poly(self) -> ClosedPoly:
        return ClosedPoly((self.a, self.b, self.a, self.b), (90.0,) * 4, HookSpec(float(self.hook_start), self.ext_start),
                          HookSpec(float(self.hook_end), self.ext_end), BendUse.STIRRUP, names=("A", "B", "A", "B"))


# El resto del catálogo se registra al importar este módulo (después de definir la base y el registro).
from core import shape_templates  # noqa: E402,F401
