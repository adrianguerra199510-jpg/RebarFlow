"""Geometría de doblado de barras.

Convención de dimensiones (la usual en detallado según ACI 318 / CRSI / NSR-10):
las cotas de una forma se miden **de fuera a fuera** de la barra, hasta el
vértice exterior de cada doblez. La longitud de corte se obtiene a lo largo del
eje de la barra:

    L = Σ cotas exteriores − Σ deducciones por doblez (+ extensiones de gancho)

Para un doblez de ángulo de giro θ, radio interior ``r`` y diámetro de barra
``d`` (radio al eje ``R = r + d/2``):

* longitud exterior de tangente: ``(r + d)·tan(θ/2)``
* longitud de arco al eje:       ``θ·R``
* deducción por doblez:          ``2·(r + d)·tan(θ/2) − θ·R``

Todas las longitudes están en milímetros y los ángulos en grados.
"""

from __future__ import annotations

import math


class GeometryError(ValueError):
    """Geometría imposible o no admitida por la norma (dimensión, radio, gancho)."""


def _check_angle(angle_deg: float) -> None:
    if not 0.0 < angle_deg < 180.0:
        raise GeometryError(
            f"El ángulo de giro debe estar entre 0° y 180° (recibido: {angle_deg}°)."
        )


def arc_length(angle_deg: float, radius_mm: float) -> float:
    """Longitud de un arco circular de ``angle_deg`` grados y radio ``radius_mm``."""
    return math.radians(angle_deg) * radius_mm


def outside_tangent_length(angle_deg: float, inside_radius_mm: float, bar_diameter_mm: float) -> float:
    """Distancia del vértice exterior del doblez al punto donde termina el tramo recto.

    Es también la longitud mínima de un tramo exterior que termina en un doblez.
    """
    _check_angle(angle_deg)
    return (inside_radius_mm + bar_diameter_mm) * math.tan(math.radians(angle_deg) / 2.0)


def bend_deduction(angle_deg: float, inside_radius_mm: float, bar_diameter_mm: float) -> float:
    """Deducción que se resta a la suma de cotas exteriores por cada doblez.

    Ejemplo: doblez de 90° con radio interior 3d → ``2·(4d) − (π/2)·(3.5d) ≈ 2.50d``.
    """
    _check_angle(angle_deg)
    centerline_radius = inside_radius_mm + bar_diameter_mm / 2.0
    return 2.0 * outside_tangent_length(angle_deg, inside_radius_mm, bar_diameter_mm) - arc_length(
        angle_deg, centerline_radius
    )
