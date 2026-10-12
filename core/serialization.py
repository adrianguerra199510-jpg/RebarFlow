"""Guardado y carga de proyectos en JSON (``.rebarflow``).

El archivo guarda solo datos de entrada (barras por designación, formas por código y cotas); las
longitudes y pesos se recalculan al abrir, de modo que un archivo nunca queda desactualizado
respecto de las fórmulas.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from core.element import ElementType, RebarGroup, StructuralElement
from core.project import Project
from core.rebar import SteelGrade, get_rebar
from core.shape_codes import create_shape

FORMAT = "rebarflow-project"
VERSION = 1
FILE_SUFFIX = ".rebarflow"


def project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": VERSION,
        "name": project.name,
        "author": project.author,
        "stock_length_mm": project.stock_length_mm,
        "length_rounding_mm": project.length_rounding_mm,
        "reusable_remnant_mm": project.reusable_remnant_mm,
        "paper": project.paper,
        "elements": [
            {
                "name": element.name,
                "type": element.element_type.name,
                "level": element.level,
                "quantity": element.quantity,
                "groups": [
                    {
                        "mark": group.mark,
                        "bar": group.rebar.designation,
                        "grade": {"name": group.rebar.grade.name, "fy_mpa": group.rebar.grade.fy_mpa},
                        "shape": {"code": group.shape.code, "dimensions": asdict(group.shape)},
                        "quantity": group.quantity,
                        "description": group.description,
                    }
                    for group in element.groups
                ],
            }
            for element in project.elements
        ],
    }


def project_from_dict(data: dict[str, Any]) -> Project:
    """Reconstruye un proyecto. Lanza ``ValueError`` si el archivo no es válido."""
    if data.get("format") != FORMAT:
        raise ValueError("El archivo no es un proyecto de RebarFlow.")
    if data.get("version", 0) > VERSION:
        raise ValueError(f"El archivo es de una versión más nueva ({data['version']}) que la soportada ({VERSION}).")
    try:
        elements = []
        for item in data["elements"]:
            element = StructuralElement(item["name"], ElementType[item["type"]], item["level"], item["quantity"])
            for g in item["groups"]:
                grade = SteelGrade(g["grade"]["name"], g["grade"]["fy_mpa"])
                shape = create_shape(g["shape"]["code"], **g["shape"]["dimensions"])
                element.groups.append(
                    RebarGroup(g["mark"], get_rebar(g["bar"], grade), shape, g["quantity"], g.get("description", ""))
                )
            elements.append(element)
        return Project(
            name=data["name"],
            author=data.get("author", ""),
            stock_length_mm=data["stock_length_mm"],
            length_rounding_mm=data["length_rounding_mm"],
            reusable_remnant_mm=data.get("reusable_remnant_mm", 1000.0),
            paper=data.get("paper", "letter"),
            elements=elements,
        )
    except (KeyError, TypeError) as error:
        raise ValueError(f"Archivo de proyecto dañado o incompleto: {error!r}") from error


def save_project(project: Project, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project_to_dict(project), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_project(path: str | Path) -> Project:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"El archivo no es JSON válido: {error}") from error
    return project_from_dict(data)
