"""Descripción de los parámetros de una forma, para validarlos y generar formularios.

Cada campo del ``dataclass`` de una forma puede declararse con :func:`param`, que adjunta un
:class:`ParamSpec` (rótulo, tipo, valor por defecto, límites). La interfaz construye el formulario
a partir de esos metadatos, de modo que una forma nueva aparece sin tocar el código de la ventana.

Tipos (``kind``): ``length`` (mm, > 0), ``number`` (real, ≥ ``minimum``), ``angle`` (grados entre
``minimum`` y ``maximum``), ``count`` (entero), ``choice`` (valor de ``choices``), ``lengths`` (lista
de longitudes) y ``angles`` (lista de ángulos de giro).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.geometry import GeometryError

DEFAULT_LENGTH_MM = 500.0
KINDS = ("length", "number", "angle", "count", "choice", "lengths", "angles")


@dataclass(frozen=True)
class ParamSpec:
    name: str
    label: str
    kind: str
    default: Any
    optional: bool = False
    choices: tuple[tuple[Any, str], ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    hidden: bool = False  # lo gestiona otro control del formulario (p. ej. los ángulos del editor de tramos)
    #: Condiciones ``(parámetro, valor)``: el parámetro solo se usa si todas se cumplen (el formulario lo deshabilita si no).
    depends: tuple[tuple[str, Any], ...] = ()
    auto_text: str = ""  # texto del valor «automático» (``None``) de un parámetro opcional, si no es el estándar de norma

    def active(self, values: Mapping[str, Any]) -> bool:
        """Si el parámetro se usa con los ``values`` dados (los valores que no conoce no lo desactivan)."""
        return all(values.get(name, expected) == expected for name, expected in self.depends)


def param(label: str, kind: str = "length", default: Any = DEFAULT_LENGTH_MM, *, optional: bool = False,
          choices: tuple[tuple[Any, str], ...] = (), minimum: float | None = None, maximum: float | None = None,
          hidden: bool = False, depends: tuple[tuple[str, Any], ...] = (), auto_text: str = "") -> Any:
    """Campo de ``dataclass`` con su descripción de parámetro (el nombre se toma del campo)."""
    if kind not in KINDS:
        raise ValueError(f"Tipo de parámetro desconocido: {kind!r}")
    spec = ParamSpec("", label, kind, default, optional, tuple(choices), minimum, maximum, hidden,
                     tuple(depends), auto_text)
    return field(default=default, metadata={"spec": spec})


def _number(owner: str, spec: ParamSpec, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise GeometryError(f"Forma {owner}: «{spec.label}» debe ser un número (recibido: {value!r}).")
    return float(value)


def validate_param(owner: str, spec: ParamSpec, value: Any) -> Any:
    """Valida ``value`` según ``spec`` y lo devuelve normalizado (tuplas para listas, int para opciones)."""
    if value is None:
        if spec.optional:
            return None
        raise GeometryError(f"Forma {owner}: falta «{spec.label}».")
    kind = spec.kind
    if kind in ("length", "number"):
        number = _number(owner, spec, value)
        low_ok = number >= spec.minimum if spec.minimum is not None else number > 0
        if not low_ok or (spec.maximum is not None and number > spec.maximum):
            bound = f"≥ {spec.minimum:g}" if spec.minimum is not None else "positivo"
            raise GeometryError(f"Forma {owner}: «{spec.label}» debe ser {bound} (recibido: {value!r}).")
        return value if kind == "length" and isinstance(value, (int, float)) else number
    if kind == "angle":
        number = _number(owner, spec, value)
        low = spec.minimum if spec.minimum is not None else 0.0
        high = spec.maximum if spec.maximum is not None else 180.0
        if not low <= number <= high:
            raise GeometryError(f"Forma {owner}: «{spec.label}» debe estar entre {low:g}° y {high:g}° (recibido: {value!r}).")
        return number
    if kind == "count":
        if isinstance(value, bool) or not isinstance(value, int) or value < (spec.minimum or 1):
            raise GeometryError(f"Forma {owner}: «{spec.label}» debe ser un entero ≥ {int(spec.minimum or 1)} (recibido: {value!r}).")
        return value
    if kind == "choice":
        for option, _ in spec.choices:
            if value == option:
                return option
        allowed = ", ".join(str(option) for option, _ in spec.choices)
        raise GeometryError(f"Forma {owner}: «{spec.label}» debe ser uno de {{{allowed}}} (recibido: {value!r}).")
    if kind in ("lengths", "angles"):
        try:
            items = tuple(_number(owner, spec, v) for v in value)
        except TypeError:
            raise GeometryError(f"Forma {owner}: «{spec.label}» debe ser una lista de números.") from None
        if kind == "lengths" and (not items or any(v <= 0 for v in items)):
            raise GeometryError(f"Forma {owner}: «{spec.label}» debe tener al menos un tramo y todos positivos.")
        if kind == "angles" and any(not 0 < abs(v) < 180 for v in items):
            raise GeometryError(f"Forma {owner}: los ángulos de giro deben estar entre 0° y 180° (excluidos).")
        return items
    raise GeometryError(f"Forma {owner}: tipo de parámetro no soportado {kind!r}.")
