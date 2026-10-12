"""Barras de refuerzo: propiedades, ganchos estándar, radios de doblez y catálogo.

Los diámetros y masas del catálogo corresponden a barras corrugadas ASTM A615/A615M
(#3 a #11, designación métrica suave 10M a 36M). El rango "10 mm a 32 mm" de uso
corriente queda cubierto por #3 (10M) a #10 (32M); se incluye además #11 (36M).

Geometría de ganchos y diámetros mínimos de doblez según ACI 318-19 (Tablas 25.3.1 y
25.3.2) y NSR-10 (C.7.1 y C.7.2). Verifique los valores contra la edición de la norma
vigente en su jurisdicción antes de emitir planos o pedidos.

Todas las longitudes están en milímetros; la masa lineal, en kg/m.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from enum import Enum

from core.geometry import GeometryError, arc_length

STEEL_DENSITY_KG_M3 = 7850.0
_MASS_TOLERANCE = 0.05  # desviación máxima admitida entre masa declarada y π/4·d²·ρ


@dataclass(frozen=True)
class SteelGrade:
    """Grado del acero: nombre comercial y esfuerzo de fluencia especificado."""

    name: str
    fy_mpa: float

    def __post_init__(self) -> None:
        if self.fy_mpa <= 0:
            raise ValueError(f"fy debe ser positivo (recibido: {self.fy_mpa}).")


GRADE_40 = SteelGrade("Grado 40", 280.0)
GRADE_60 = SteelGrade("Grado 60", 420.0)
GRADE_75 = SteelGrade("Grado 75", 520.0)


class BendUse(Enum):
    """Uso de la barra, que determina el diámetro mínimo de doblez y el gancho estándar."""

    MAIN = "main"  # barras longitudinales / de desarrollo (ACI 318-19 Tabla 25.3.1)
    STIRRUP = "stirrup"  # estribos, ligaduras y zunchos (ACI 318-19 Tabla 25.3.2)


class HookType(Enum):
    """Ángulo del gancho estándar, en grados."""

    DEG_90 = 90
    DEG_135 = 135
    DEG_180 = 180


@dataclass(frozen=True)
class StandardHook:
    """Gancho estándar ya resuelto para una barra y un uso concretos."""

    hook_type: HookType
    bar_diameter_mm: float
    bend_diameter_mm: float  # diámetro interior del doblez
    extension_mm: float  # tramo recto después del doblez

    @property
    def angle_deg(self) -> float:
        return float(self.hook_type.value)

    @property
    def centerline_radius_mm(self) -> float:
        return (self.bend_diameter_mm + self.bar_diameter_mm) / 2.0

    @property
    def arc_length_mm(self) -> float:
        """Longitud del arco del doblez medida sobre el eje de la barra."""
        return arc_length(self.angle_deg, self.centerline_radius_mm)

    @property
    def developed_length_mm(self) -> float:
        """Longitud de barra consumida por el gancho: arco + extensión recta."""
        return self.arc_length_mm + self.extension_mm

    @property
    def outside_leg_mm(self) -> float:
        """Cota exterior del gancho de 90° (dimensión "A o G" de ACI SP-66).

        Se mide desde la cara exterior del tramo recto hasta el extremo libre:
        ``extensión + D/2 + d``. Solo está definida para ganchos de 90°.
        """
        if self.hook_type is not HookType.DEG_90:
            raise GeometryError("La cota exterior A/G solo está definida para ganchos de 90°.")
        return self.extension_mm + self.bend_diameter_mm / 2.0 + self.bar_diameter_mm


@dataclass(frozen=True)
class Rebar:
    """Barra de refuerzo corrugada.

    Attributes:
        designation: Designación en pulgadas, p. ej. ``"#4"``.
        diameter_mm: Diámetro nominal.
        linear_mass_kg_m: Masa lineal nominal.
        grade: Grado del acero.
        metric_designation: Designación métrica suave opcional, p. ej. ``"13M"``.
    """

    designation: str
    diameter_mm: float
    linear_mass_kg_m: float
    grade: SteelGrade = GRADE_60
    metric_designation: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"#\d+", self.designation):
            raise ValueError(f"Designación inválida {self.designation!r}: use el formato '#N'.")
        if self.diameter_mm <= 0 or self.linear_mass_kg_m <= 0:
            raise ValueError(f"{self.designation}: diámetro y masa lineal deben ser positivos.")
        theoretical = math.pi / 4.0 * self.diameter_mm**2 * STEEL_DENSITY_KG_M3 / 1e6
        if abs(self.linear_mass_kg_m - theoretical) / theoretical > _MASS_TOLERANCE:
            raise ValueError(
                f"{self.designation}: masa {self.linear_mass_kg_m} kg/m inconsistente con el diámetro "
                f"{self.diameter_mm} mm (teórica ≈ {theoretical:.3f} kg/m)."
            )

    @property
    def bar_number(self) -> int:
        return int(self.designation[1:])

    @property
    def label(self) -> str:
        return f"{self.designation} (Ø{self.diameter_mm:g} mm)"

    def with_grade(self, grade: SteelGrade) -> Rebar:
        return replace(self, grade=grade)

    def mass_for_length(self, length_m: float) -> float:
        """Masa en kg de ``length_m`` metros de barra."""
        return length_m * self.linear_mass_kg_m

    # ------------------------------------------------------------------ doblez
    def bend_diameter_mm(self, use: BendUse = BendUse.MAIN) -> float:
        """Diámetro interior mínimo de doblez.

        * ``MAIN``    (ACI 25.3.1): #3–#8 → 6d; #9–#11 → 8d; #14–#18 → 10d.
        * ``STIRRUP`` (ACI 25.3.2): #3–#5 → 4d; #6–#8 → 6d. No se define para #9 o mayores.
        """
        n = self.bar_number
        if use is BendUse.MAIN:
            factor = 6.0 if n <= 8 else 8.0 if n <= 11 else 10.0
        else:
            if n > 8:
                raise GeometryError(
                    f"{self.designation}: la norma no define doblez estándar de estribo para barras mayores a #8."
                )
            factor = 4.0 if n <= 5 else 6.0
        return factor * self.diameter_mm

    def bend_radius_mm(self, use: BendUse = BendUse.MAIN) -> float:
        """Radio interior mínimo de doblez."""
        return self.bend_diameter_mm(use) / 2.0

    def centerline_radius_mm(self, use: BendUse = BendUse.MAIN) -> float:
        """Radio de doblez medido al eje de la barra: ``r + d/2``."""
        return self.bend_radius_mm(use) + self.diameter_mm / 2.0

    def standard_hook(self, hook_type: HookType, use: BendUse = BendUse.MAIN) -> StandardHook:
        """Gancho estándar para esta barra.

        * ``MAIN``:    90° → 12d; 180° → mayor de 4d y 65 mm. (El de 135° no se define.)
        * ``STIRRUP``: 90° → #3–#5: mayor de 6d y 75 mm; #6–#8: 12d.
                       135° → mayor de 6d y 75 mm (gancho sísmico). (El de 180° no se define.)
        """
        d = self.diameter_mm
        if use is BendUse.MAIN:
            if hook_type is HookType.DEG_90:
                extension = 12.0 * d
            elif hook_type is HookType.DEG_180:
                extension = max(4.0 * d, 65.0)
            else:
                raise GeometryError("El gancho de 135° solo está definido para estribos y ligaduras.")
        else:
            if hook_type is HookType.DEG_90:
                extension = max(6.0 * d, 75.0) if self.bar_number <= 5 else 12.0 * d
            elif hook_type is HookType.DEG_135:
                extension = max(6.0 * d, 75.0)
            else:
                raise GeometryError("El gancho de 180° no está definido para estribos y ligaduras.")
        return StandardHook(hook_type, d, self.bend_diameter_mm(use), extension)


# --------------------------------------------------------------------- catálogo
# (designación, métrica, Ø nominal mm, masa kg/m) — ASTM A615/A615M
_ASTM_A615: tuple[tuple[str, str, float, float], ...] = (
    ("#3", "10M", 9.525, 0.560),
    ("#4", "13M", 12.700, 0.994),
    ("#5", "16M", 15.875, 1.552),
    ("#6", "19M", 19.050, 2.235),
    ("#7", "22M", 22.225, 3.042),
    ("#8", "25M", 25.400, 3.973),
    ("#9", "29M", 28.650, 5.060),
    ("#10", "32M", 32.260, 6.404),
    ("#11", "36M", 35.810, 7.907),
)

REBAR_CATALOG: dict[str, Rebar] = {
    designation: Rebar(designation, diameter, mass, GRADE_60, metric)
    for designation, metric, diameter, mass in _ASTM_A615
}


def register_rebar(rebar: Rebar, *, replace_existing: bool = False) -> None:
    """Agrega una barra al catálogo (p. ej. #14, #18 o una serie métrica propia)."""
    if rebar.designation in REBAR_CATALOG and not replace_existing:
        raise ValueError(f"{rebar.designation} ya existe en el catálogo.")
    REBAR_CATALOG[rebar.designation] = rebar


def list_rebars() -> list[Rebar]:
    """Barras del catálogo ordenadas por número de barra."""
    return sorted(REBAR_CATALOG.values(), key=lambda r: r.bar_number)


def get_rebar(designation: str | int, grade: SteelGrade | None = None) -> Rebar:
    """Busca una barra por designación.

    Acepta ``"#4"``, ``"4"``, ``4`` (número de barra) o ``"13M"`` (métrica suave).
    Con ``grade`` devuelve la barra con ese grado de acero.
    """
    if isinstance(designation, int):
        key = f"#{designation}"
    else:
        text = designation.strip().upper().replace(" ", "")
        if text.endswith("M"):
            matches = [r for r in REBAR_CATALOG.values() if (r.metric_designation or "").upper() == text]
            key = matches[0].designation if matches else text
        else:
            key = text if text.startswith("#") else f"#{text}"
    try:
        rebar = REBAR_CATALOG[key]
    except KeyError:
        available = ", ".join(r.designation for r in list_rebars())
        raise KeyError(f"Barra {designation!r} no está en el catálogo (disponibles: {available}).") from None
    return rebar if grade is None else rebar.with_grade(grade)
