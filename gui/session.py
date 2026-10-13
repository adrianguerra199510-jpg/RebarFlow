"""Proyecto abierto en la ventana: el documento y el estado de la vista que se recupera al volver a él."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.element import StructuralElement
from core.project import Project


@dataclass(eq=False)
class ProjectSession:
    """Un proyecto abierto (una pestaña de la cinta de proyectos).

    Attributes:
        project: El documento.
        path: Archivo en el que se guardó, o ``None`` si todavía no tiene.
        modified: Hay cambios sin guardar.
        element: Elemento seleccionado en el árbol.
        tab: Pestaña central activa (barras del elemento, planilla, resumen o plan de corte).
    """

    project: Project
    path: Path | None = None
    modified: bool = False
    element: StructuralElement | None = None
    tab: int = 0

    @property
    def blank(self) -> bool:
        """Proyecto recién creado y sin tocar: se puede reemplazar al abrir otro en vez de dejar una pestaña vacía."""
        return not self.modified and self.path is None and not self.project.elements
