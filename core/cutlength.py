"""Resultado del cálculo de la longitud de corte de una forma."""

from __future__ import annotations

from dataclasses import dataclass

from core.coupler import coupler_text


@dataclass(frozen=True)
class HookInfo:
    """Gancho en un extremo de la barra: ángulo del doblez y largo de la extensión recta.

    ``extension_mm`` es el tramo recto que queda después del doblez (la «pata» del gancho);
    ``standard_mm`` es la extensión mínima de la norma para ese gancho, si está definida.
    """

    angle_deg: float
    extension_mm: float
    standard_mm: float | None = None

    @property
    def text(self) -> str:
        return f"{self.angle_deg:.0f}° · {self.extension_mm:.0f}"


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
    hooks: tuple[HookInfo, ...] = ()  # ganchos de la barra, con el largo de cada uno
    couplers: tuple[str, ...] = ()  # tipo de coupler de cada extremo que lo lleva (inicio y final, en ese orden)

    @property
    def total_mm(self) -> float:
        return self.dimension_sum_mm + self.bend_adjustment_mm + self.extension_mm

    @property
    def coupler_text(self) -> str:
        """Couplers de la barra en texto: ``"2 × rosca corta"`` (vacío si no lleva)."""
        return coupler_text(self.couplers)

    @property
    def hook_text(self) -> str:
        """Ganchos en texto para las tablas: ``"2 × 135° · 75"`` (ángulo · largo de extensión en mm)."""
        counts: dict[tuple[int, int], int] = {}
        for hook in self.hooks:
            key = (round(hook.angle_deg), round(hook.extension_mm))
            counts[key] = counts.get(key, 0) + 1
        parts = [f"{n} × {a}° · {e}" if n > 1 else f"{a}° · {e}" for (a, e), n in counts.items()]
        return "  /  ".join(parts)
