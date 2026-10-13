"""Resultado del cálculo de la longitud de corte de una forma."""

from __future__ import annotations

from dataclasses import dataclass, replace

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
class BarPart:
    """Una o varias barras idénticas de una pieza armada con varias barras: la **sub-marca** (``A1.1``, ``A1.2``…).

    Attributes:
        length_mm: Largo de cada barra.
        count: Cuántas barras idénticas lleva cada unidad de la pieza (las barras intermedias de una unión por acoplador
            son todas iguales: se agrupan en una sola sub-marca).
        start_thread: Rosca del extremo inicial (``"short"``, ``"long"`` o ``""`` si no la lleva).
        end_thread: Rosca del extremo final.
        first: Es la primera barra de la pieza y la forma tiene algo propio en su inicio (vueltas planas o gancho de una
            espiral): no se agrupa con las barras intermedias aunque midan lo mismo.
        last: Lo mismo para la última barra y el final de la pieza.
    """

    length_mm: float
    count: int = 1
    start_thread: str = ""
    end_thread: str = ""
    first: bool = False
    last: bool = False

    @property
    def threads(self) -> tuple[str, ...]:
        """Roscas de cada barra de esta sub-marca (inicio y final, las que lleve)."""
        return tuple(t for t in (self.start_thread, self.end_thread) if t)

    @property
    def thread_text(self) -> str:
        """Roscas en texto: ``"rosca corta al inicio, rosca larga al final"`` (vacío si no lleva)."""
        names = {"short": "rosca corta", "long": "rosca larga"}
        parts = [f"{names[t]} al {where}" for t, where in ((self.start_thread, "inicio"), (self.end_thread, "final"))
                 if t in names]
        return ", ".join(parts)


@dataclass(frozen=True)
class Supply:
    """Cómo se suministra una unidad de una forma: las barras que hay que cortar y el material que consume.

    Casi siempre es una sola barra del largo de corte. Una espiral puede llegar en rollo (``coil``) y una pieza más
    larga que la barra comercial se arma con varias barras unidas con traslapes (el material crece con ellos) o con
    acopladores (``parts`` agrupa las barras iguales en sub-marcas, cada una con las roscas de sus extremos).

    Attributes:
        pieces_mm: Largo de cada barra que se corta para una unidad, sin redondear (un solo elemento si no hay uniones).
        coil: Verdadero si la pieza sale de rollo y no de barras comerciales (no genera retales).
        parts: Barras agrupadas en sub-marcas, en el orden de la pieza; vacío si la pieza no se divide.
        joint: ``"lap"`` o ``"coupler"`` si la pieza se divide; vacío si no.
        notes: Información para el doblador (cuántas barras, qué uniones).
        warnings: Incumplimientos no fatales de la norma.
    """

    pieces_mm: tuple[float, ...]
    coil: bool = False
    parts: tuple[BarPart, ...] = ()
    joint: str = ""
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_parts(cls, parts: tuple[BarPart, ...], joint: str = "", notes: tuple[str, ...] = (),
                   warnings: tuple[str, ...] = ()) -> Supply:
        """Pieza armada con ``parts``; ``pieces_mm`` sale de ellas (cada barra tantas veces como ``count``)."""
        return cls(tuple(p.length_mm for p in parts for _ in range(p.count)), parts=parts, joint=joint, notes=notes,
                   warnings=warnings)

    def with_part_lengths(self, lengths: tuple[float, ...]) -> Supply:
        """Copia con el largo de cada sub-marca reemplazado (p. ej. por el redondeado) y ``pieces_mm`` al día."""
        parts = tuple(replace(part, length_mm=length) for part, length in zip(self.parts, lengths, strict=True))
        return replace(self, parts=parts, pieces_mm=tuple(p.length_mm for p in parts for _ in range(p.count)))

    @property
    def material_mm(self) -> float:
        """Material total por unidad: la suma de las barras (incluye los traslapes)."""
        return sum(self.pieces_mm)

    @property
    def joints(self) -> int:
        """Uniones entre barras de cada unidad (traslapes o acopladores)."""
        return 0 if self.coil else len(self.pieces_mm) - 1

    @property
    def threads(self) -> tuple[str, ...]:
        """Roscas de todas las barras de la pieza (``"short"`` / ``"long"``), por unidad."""
        return tuple(t for part in self.parts for _ in range(part.count) for t in part.threads)

    def sub_marks(self, mark: str) -> tuple[tuple[str, BarPart], ...]:
        """Sub-marcas de ``mark``: ``("A1.1", parte), ("A1.2", parte)…``; vacío si la pieza no se divide."""
        if self.joints < 1:
            return ()
        return tuple((f"{mark}.{k}", part) for k, part in enumerate(self.parts, start=1))


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
