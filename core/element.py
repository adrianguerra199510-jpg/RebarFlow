"""Elementos estructurales y grupos de barras (marcas) que los componen."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.rebar import Rebar
from core.shape_codes import CutLength, ShapeCode


class ElementType(str, Enum):
    """Tipo de elemento estructural (el valor es el rótulo que se muestra en la planilla)."""

    BEAM = "Viga"
    COLUMN = "Columna"
    FOOTING = "Zapata"
    SLAB = "Losa"
    WALL = "Muro"
    OTHER = "Otros"


@dataclass(frozen=True)
class RebarGroup:
    """Grupo de barras idénticas (una marca) dentro de un elemento.

    Attributes:
        mark: Marca de la barra, única dentro del elemento (p. ej. ``"A1"``).
        rebar: Barra de refuerzo utilizada.
        shape: Forma de doblado con sus cotas.
        quantity: Número de barras **por unidad de elemento**.
        description: Texto libre (p. ej. "Refuerzo inferior").
        cut: Desglose de la longitud de corte; se calcula al crear el grupo, lo que valida la
            geometría de la forma con la barra elegida.
    """

    mark: str
    rebar: Rebar
    shape: ShapeCode
    quantity: int
    description: str = ""
    cut: CutLength = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.mark.strip():
            raise ValueError("La marca de la barra no puede estar vacía.")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity < 1:
            raise ValueError(f"Marca {self.mark}: la cantidad debe ser un entero ≥ 1 (recibido: {self.quantity!r}).")
        object.__setattr__(self, "cut", self.shape.cut_length(self.rebar))

    @property
    def cut_length_mm(self) -> float:
        return self.cut.total_mm


@dataclass
class StructuralElement:
    """Elemento estructural (o familia de elementos idénticos), con su ubicación opcional en la obra.

    La ubicación tiene dos niveles de agrupación, ambos opcionales: ``level`` (el primero: un nivel o piso en un
    edificio, una estructura en un puente) y ``substructure`` (el segundo: p. ej. ``"GENERICA"`` o una pila). Un
    elemento sin ninguno de los dos se lista directamente bajo el proyecto.

    Attributes:
        name: Identificador, p. ej. ``"V-101"``.
        element_type: Viga, columna, zapata, etc.
        level: Primer nivel de agrupación (p. ej. ``"Nivel 1"`` o ``"C9.6-1"``); vacío si no hay.
        quantity: Número de elementos idénticos; multiplica las barras de cada grupo.
        groups: Grupos de barras que lo arman.
        substructure: Segundo nivel de agrupación (p. ej. ``"GENERICA"``); vacío si no hay.
    """

    name: str
    element_type: ElementType
    level: str = ""
    quantity: int = 1
    groups: list[RebarGroup] = field(default_factory=list)
    substructure: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("El nombre del elemento no puede estar vacío.")
        self.level = self.level.strip()
        self.substructure = self.substructure.strip()
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity < 1:
            raise ValueError(f"{self.name}: la cantidad de elementos debe ser un entero ≥ 1 (recibido: {self.quantity!r}).")
        marks = [g.mark for g in self.groups]
        if len(marks) != len(set(marks)):
            raise ValueError(f"{self.name}: hay marcas de barra repetidas.")

    @property
    def path(self) -> tuple[str, ...]:
        """Ubicación del elemento: sus niveles de agrupación no vacíos, del primero al segundo."""
        return tuple(part for part in (self.level, self.substructure) if part)

    @property
    def heading(self) -> str:
        """Título del elemento en las planillas: ``"V-101  ·  Viga  ·  Nivel 1  ·  4 und"`` (sin ubicación si no tiene)."""
        parts = [self.name, self.element_type.value, self.location, f"{self.quantity} und"]
        return "  ·  ".join(part for part in parts if part)

    @property
    def location(self) -> str:
        """La ubicación como texto (``"C9.6-1 / GENERICA"``); vacío si el elemento no tiene."""
        return " / ".join(self.path)

    def add_group(
        self, mark: str, rebar: Rebar, shape: ShapeCode, quantity: int, description: str = ""
    ) -> RebarGroup:
        """Crea un grupo de barras, lo agrega al elemento y lo devuelve."""
        if any(g.mark == mark for g in self.groups):
            raise ValueError(f"{self.name}: la marca {mark!r} ya existe.")
        group = RebarGroup(mark, rebar, shape, quantity, description)
        self.groups.append(group)
        return group
