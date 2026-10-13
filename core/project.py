"""Proyecto: documento que agrupa los elementos y los parámetros de cálculo y de impresión."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.element import StructuralElement

DEFAULT_PROJECT_NAME = "Proyecto sin título"
DEFAULT_GROUP_LABEL = "Nivel"
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
        group_label: Cómo se llama el primer nivel de agrupación de los elementos: ``"Nivel"`` en un edificio,
            ``"Estructura"`` en un puente, ``"Tramo"``…
        client, work_code, drawing, schedule_number, delivery_date, global_position: Datos de encabezado de la
            planilla (cliente, código de obra, plano, número de planilla, fecha de entrega, posición global); los
            vacíos no se imprimen. El nombre del proyecto es la obra.
        logo_png: Logo del encabezado de las planillas como PNG (vacío = sin logo); se guarda dentro del proyecto.
    """

    name: str = DEFAULT_PROJECT_NAME
    author: str = ""
    stock_length_mm: float = 12_000.0
    length_rounding_mm: float = 5.0
    reusable_remnant_mm: float = 1000.0
    paper: str = "letter"
    elements: list[StructuralElement] = field(default_factory=list)
    group_label: str = DEFAULT_GROUP_LABEL
    client: str = ""
    work_code: str = ""
    drawing: str = ""
    schedule_number: str = ""
    delivery_date: str = ""
    global_position: str = ""
    logo_png: bytes = b""

    def __post_init__(self) -> None:
        if self.stock_length_mm <= 0:
            raise ValueError("La longitud de la barra comercial debe ser positiva.")
        if self.length_rounding_mm < 0:
            raise ValueError("El paso de redondeo no puede ser negativo.")
        if self.reusable_remnant_mm < 0:
            raise ValueError("La longitud de retal reutilizable no puede ser negativa.")
        if self.paper not in PAPER_SIZES:
            raise ValueError(f"Papel inválido {self.paper!r} (use {' o '.join(PAPER_SIZES)}).")
        self.group_label = self.group_label.strip() or DEFAULT_GROUP_LABEL

    @property
    def levels(self) -> list[str]:
        """Primer nivel de agrupación (no vacío) en orden de aparición."""
        return [name for name in dict.fromkeys(element.level for element in self.elements) if name]

    @property
    def substructures(self) -> list[str]:
        """Segundo nivel de agrupación (no vacío) en orden de aparición."""
        return [name for name in dict.fromkeys(element.substructure for element in self.elements) if name]

    def header_fields(self) -> tuple[tuple[str, str], ...]:
        """Datos de encabezado rellenados, como ``(rótulo, valor)``, en el orden de la planilla."""
        fields = (("Cliente", self.client), ("Cód. obra", self.work_code), ("N° planilla", self.schedule_number),
                  ("Plano", self.drawing), ("P. global", self.global_position), ("F. entrega", self.delivery_date))
        return tuple((label, value.strip()) for label, value in fields if value.strip())
