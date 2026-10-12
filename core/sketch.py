"""Esquemas de las formas de doblado, independientes del medio de dibujo.

Un :class:`Sketch` describe la barra como polilíneas (al eje) más rótulos de cotas, en
coordenadas relativas con el eje *y* hacia arriba. Los renderizadores (PNG para Excel y
PDF, vista previa de la interfaz) lo escalan al espacio disponible.

Los esquemas son proporcionales a las cotas pero con un tramo mínimo (:func:`proportional`)
para que una pata corta, como un gancho de 250 mm junto a una barra de 5 m, siga siendo legible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class DimLabel:
    """Rótulo junto al punto ``at``, desplazado hacia ``side`` (vector unitario).

    ``kind``: ``"dim"`` cota de un tramo, ``"hook"`` largo de la extensión de un gancho (se dibuja en
    otro color) y ``"angle"`` ángulo de un doblez.
    """

    text: str
    at: Point
    side: Point = (0.0, 1.0)
    kind: str = "dim"


@dataclass(frozen=True)
class Sketch:
    """Polilíneas de la barra y rótulos de cotas."""

    paths: tuple[tuple[Point, ...], ...]
    labels: tuple[DimLabel, ...] = ()


def proportional(values: Sequence[float], minimum: float = 0.3) -> list[float]:
    """Longitudes relativas (la mayor vale 1) con un piso de ``minimum`` para tramos cortos."""
    largest = max(values)
    return [max(v / largest, minimum) for v in values]


def format_dimension(value: float) -> str:
    """Texto de una cota en mm, redondeada al milímetro como en las tablas de la planilla."""
    return f"{value:.0f}"
