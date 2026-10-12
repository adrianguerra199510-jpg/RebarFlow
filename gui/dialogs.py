"""Diálogos de edición: elemento, barra (con vista previa en vivo) y propiedades del proyecto."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import fields
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QVBoxLayout, QWidget,
)

from core.element import ElementType, RebarGroup, StructuralElement
from core.geometry import GeometryError
from core.project import Project
from core.rebar import GRADE_40, GRADE_60, GRADE_75, get_rebar, list_rebars
from core.shape_codes import ShapeCode, available_shapes
from engine.bbs_calculator import round_up_to_step
from gui.widgets import ShapePreview

_GRADES = (GRADE_40, GRADE_60, GRADE_75)
_DEFAULT_DIMENSION_MM = 500.0
_MAX_DIMENSION_MM = 100_000.0
_PAPERS = (("Carta (Letter)", "letter"), ("A4", "a4"))


def _buttons(dialog: QDialog) -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Ok).setText("Aceptar")
    box.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class ElementDialog(QDialog):
    """Alta y edición de un elemento estructural."""

    def __init__(self, parent: QWidget | None, element: StructuralElement | None = None,
                 levels: Collection[str] = ()) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar elemento" if element else "Nuevo elemento")
        self.setMinimumWidth(380)

        self.name = QLineEdit(element.name if element else "")
        self.name.setPlaceholderText("p. ej. V-101")
        self.type = QComboBox()
        for element_type in ElementType:
            self.type.addItem(element_type.value, element_type)
        self.level = QComboBox()
        self.level.setEditable(True)
        self.level.addItems(list(levels))
        self.level.setCurrentText(element.level if element else (list(levels)[-1] if levels else "Nivel 1"))
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 100_000)
        self.quantity.setSuffix(" und")
        if element:
            self.type.setCurrentIndex(self.type.findData(element.element_type))
            self.quantity.setValue(element.quantity)

        form = QFormLayout()
        form.addRow("Nombre:", self.name)
        form.addRow("Tipo:", self.type)
        form.addRow("Nivel:", self.level)
        form.addRow("Cantidad de elementos iguales:", self.quantity)
        self.buttons = _buttons(self)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

        self.name.textChanged.connect(self._validate)
        self.level.currentTextChanged.connect(self._validate)
        self._validate()

    def _validate(self) -> None:
        ok = bool(self.name.text().strip() and self.level.currentText().strip())
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def values(self) -> tuple[str, ElementType, str, int]:
        return (self.name.text().strip(), self.type.currentData(), self.level.currentText().strip(),
                self.quantity.value())


class ProjectDialog(QDialog):
    """Propiedades del proyecto: encabezado de las planillas y parámetros de cálculo."""

    def __init__(self, parent: QWidget | None, project: Project) -> None:
        super().__init__(parent)
        self.setWindowTitle("Propiedades del proyecto")
        self.setMinimumWidth(420)
        self.name = QLineEdit(project.name)
        self.author = QLineEdit(project.author)
        self.stock = QDoubleSpinBox()
        self.stock.setRange(1000, 24000)
        self.stock.setDecimals(0)
        self.stock.setSingleStep(500)
        self.stock.setSuffix(" mm")
        self.stock.setValue(project.stock_length_mm)
        self.rounding = QDoubleSpinBox()
        self.rounding.setRange(0, 100)
        self.rounding.setDecimals(0)
        self.rounding.setSuffix(" mm  (0 = sin redondeo)")
        self.rounding.setValue(project.length_rounding_mm)
        self.paper = QComboBox()
        for text, value in _PAPERS:
            self.paper.addItem(text, value)
        self.paper.setCurrentIndex(self.paper.findData(project.paper))

        form = QFormLayout()
        form.addRow("Nombre del proyecto:", self.name)
        form.addRow("Responsable:", self.author)
        form.addRow("Longitud de la barra comercial:", self.stock)
        form.addRow("Redondeo de la longitud de corte:", self.rounding)
        form.addRow("Papel del PDF:", self.paper)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self))

    def apply_to(self, project: Project) -> None:
        project.name = self.name.text().strip() or project.name
        project.author = self.author.text().strip()
        project.stock_length_mm = self.stock.value()
        project.length_rounding_mm = self.rounding.value()
        project.paper = self.paper.currentData()


class BarDialog(QDialog):
    """Alta y edición de una marca de barras, con el esquema y la longitud de corte en vivo.

    Los campos de cotas se generan a partir de los campos del ``dataclass`` de la forma elegida,
    de modo que cualquier forma registrada con ``@register_shape`` aparece sin tocar la interfaz.
    """

    def __init__(self, parent: QWidget | None, *, group: RebarGroup | None = None, suggested_mark: str = "A1",
                 used_marks: Collection[str] = (), stock_length_mm: float = 12_000.0,
                 rounding_mm: float = 5.0) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar barra" if group else "Nueva barra")
        self.setMinimumWidth(520)
        self._used_marks = set(used_marks)
        self._stock = stock_length_mm
        self._rounding = rounding_mm
        self._spins: dict[str, QDoubleSpinBox] = {}
        self._remembered: dict[str, float] = {}
        self._group: RebarGroup | None = None

        self.mark = QLineEdit(group.mark if group else suggested_mark)
        self.bar = QComboBox()
        for rebar in list_rebars():
            self.bar.addItem(rebar.label, rebar.designation)
        self.grade = QComboBox()
        for grade in _GRADES:
            self.grade.addItem(f"{grade.name} ({grade.fy_mpa:g} MPa)", grade)
        self.grade.setCurrentIndex(1)
        self.shape = QComboBox()
        for code, cls in available_shapes().items():
            self.shape.addItem(f"{code} · {cls.name}", cls)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1_000_000)
        self.quantity.setValue(group.quantity if group else 1)
        self.quantity.setSuffix(" por elemento")
        self.description = QLineEdit(group.description if group else "")
        self.description.setPlaceholderText("p. ej. Refuerzo inferior")

        self.dim_form = QFormLayout()
        self.preview = ShapePreview(440, 165)
        self.info = QLabel()
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setWordWrap(True)
        self.info.setMinimumHeight(88)
        self.info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        top = QFormLayout()
        top.addRow("Marca:", self.mark)
        top.addRow("Barra:", self.bar)
        top.addRow("Grado:", self.grade)
        top.addRow("Forma:", self.shape)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        bottom = QFormLayout()
        bottom.addRow("Cantidad:", self.quantity)
        bottom.addRow("Descripción:", self.description)
        self.buttons = _buttons(self)

        preview_row = QHBoxLayout()
        preview_row.addStretch(1)
        preview_row.addWidget(self.preview)
        preview_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(separator)
        layout.addLayout(self.dim_form)
        layout.addLayout(bottom)
        layout.addLayout(preview_row)
        layout.addWidget(self.info)
        layout.addWidget(self.buttons)

        if group:
            self.bar.setCurrentIndex(self.bar.findData(group.rebar.designation))
            grade_index = next((i for i, g in enumerate(_GRADES) if g == group.rebar.grade), 1)
            self.grade.setCurrentIndex(grade_index)
            self.shape.setCurrentIndex(self.shape.findData(type(group.shape)))
            self._remembered = {f.name: getattr(group.shape, f.name) or 0.0 for f in fields(group.shape)}
        self._rebuild_dimensions()

        self.mark.textChanged.connect(self._update)
        self.bar.currentIndexChanged.connect(self._update)
        self.grade.currentIndexChanged.connect(self._update)
        self.quantity.valueChanged.connect(self._update)
        self.shape.currentIndexChanged.connect(self._shape_changed)
        self._update()

    # ------------------------------------------------------------------ cotas dinámicas
    def _shape_class(self) -> type[ShapeCode]:
        return self.shape.currentData()

    def _shape_changed(self) -> None:
        self._remember_values()
        self._rebuild_dimensions()
        self._update()

    def _remember_values(self) -> None:
        self._remembered.update({name: spin.value() for name, spin in self._spins.items()})

    def _rebuild_dimensions(self) -> None:
        while self.dim_form.rowCount():
            self.dim_form.removeRow(0)
        self._spins = {}
        cls = self._shape_class()
        for f in fields(cls):
            optional = f.default is None
            spin = QDoubleSpinBox()
            spin.setRange(0 if optional else 0.1, _MAX_DIMENSION_MM)
            spin.setDecimals(1)
            spin.setSingleStep(10)
            spin.setSuffix(" mm")
            spin.setValue(self._remembered.get(f.name, 0.0 if optional else _DEFAULT_DIMENSION_MM))
            if optional:
                spin.setSpecialValueText("estándar (según norma)")
            spin.valueChanged.connect(self._update)
            self._spins[f.name] = spin
            self.dim_form.addRow(f"{cls.field_labels.get(f.name, f.name.upper())}:", spin)

    def _build_shape(self) -> ShapeCode:
        values: dict[str, float | None] = {}
        for f in fields(self._shape_class()):
            value = self._spins[f.name].value()
            values[f.name] = (None if value == 0.0 else value) if f.default is None else value
        return self._shape_class()(**values)

    # ------------------------------------------------------------------ cálculo en vivo
    def _update(self) -> None:
        self._group = None
        error: str | None = None
        shape: ShapeCode | None = None
        html = ""
        mark = self.mark.text().strip()
        try:
            if not mark:
                raise ValueError("Escriba la marca de la barra.")
            if mark in self._used_marks:
                raise ValueError(f"La marca {mark!r} ya existe en este elemento.")
            shape = self._build_shape()
            rebar = get_rebar(self.bar.currentData(), self.grade.currentData())
            group = RebarGroup(mark, rebar, shape, self.quantity.value(), self.description.text().strip())
            cut = group.cut
            rounded = round_up_to_step(cut.total_mm, self._rounding)
            if rounded > self._stock + 1e-6:
                raise ValueError(
                    f"La barra mide {rounded / 1000:.2f} m y excede la barra comercial de {self._stock / 1000:.2f} m; "
                    "divídala en barras traslapadas."
                )
            weight = rebar.mass_for_length(rounded / 1000)
            html = (
                f"<b>Longitud de corte: {cut.total_mm:,.1f} mm → {rounded:,.0f} mm</b>"
                f" &nbsp;·&nbsp; peso unitario <b>{weight:,.2f} kg</b><br>"
                f"<span style='color:#595959'>Σ cotas {cut.dimension_sum_mm:,.1f} mm &nbsp;·&nbsp; dobleces "
                f"{cut.bend_adjustment_mm:+,.1f} mm &nbsp;·&nbsp; extensiones {cut.extension_mm:+,.1f} mm</span>"
            )
            html += "".join(f"<br><span style='color:#595959'>{escape(n)}</span>" for n in cut.notes)
            html += "".join(f"<br><span style='color:#C00000'><b>Aviso:</b> {escape(w)}</span>" for w in cut.warnings)
            self._group = group
        except (GeometryError, ValueError, TypeError) as exc:
            error = str(exc)
        if error:
            html = f"<span style='color:#C00000'><b>{escape(error)}</b></span>"
        self.info.setText(html)
        self.preview.set_shape(shape if error is None else None, "Corrija los datos\npara ver el esquema")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self._group is not None)

    def result_group(self) -> RebarGroup:
        """Grupo de barras definido en el diálogo (solo válido tras aceptar)."""
        if self._group is None:
            raise ValueError("Los datos de la barra no son válidos.")
        return self._group
