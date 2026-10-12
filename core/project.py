"""Proyecto: documento que agrupa los elementos y los parámetros de cálculo y de impresión."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.element import StructuralElement

DEFAULT_PROJECT_NAME = "Proyecto sin título"
PAPER_SIZES = ("letter", "a4")


@dataclass
class Project:
    """Documento de trabajo de la aplicación.

    Attributes:
        name: Nombre del proyecto (encabezado de las planillas).
        author: Responsable del cálculo.
        stock_length_mm: Longitud de la barra comercial, para el cálculo de desperdicios.
        length_rounding_mm: Paso de redondeo (hacia arriba) de la longitud de corte.
        reusable_remnant_mm: Un retal de al menos esta longitud se considera reutilizable (0 = ninguno).
        paper: Papel del PDF: ``"letter"`` (carta) o ``"a4"``.
        elements: Elementos estructurales, en el orden de la planilla.
    """

    name: str = DEFAULT_PROJECT_NAME
    author: str = ""
    stock_length_mm: float = 12_000.0
    length_rounding_mm: float = 5.0
    reusable_remnant_mm: float = 1000.0
    paper: str = "letter"
    elements: list[StructuralElement] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.stock_length_mm <= 0:
            raise ValueError("La longitud de la barra comercial debe ser positiva.")
        if self.length_rounding_mm < 0:
            raise ValueError("El paso de redondeo no puede ser negativo.")
        if self.reusable_remnant_mm < 0:
            raise ValueError("La longitud de retal reutilizable no puede ser negativa.")
        if self.paper not in PAPER_SIZES:
            raise ValueError(f"Papel inválido {self.paper!r} (use {' o '.join(PAPER_SIZES)}).")

    @property
    def levels(self) -> list[str]:
        """Niveles en orden de aparición."""
        return list(dict.fromkeys(element.level for element in self.elements))
