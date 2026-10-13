"""Diálogos de edición: elemento, barra (con vista previa en vivo) y propiedades del proyecto."""

from __future__ import annotations

from collections.abc import Collection
from html import escape
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QVBoxLayout, QWidget,
)

from core.coupler import coupler_text
from core.element import ElementType, RebarGroup, StructuralElement
from core.geometry import GeometryError
from core.params import ParamSpec
from core.polybar import LETTERS
from core.project import Project
from core.rebar import GRADE_40, GRADE_60, GRADE_75, get_rebar, list_rebars
from core.shape_codes import ShapeCode, available_shapes
from core.splice import pieces_text
from engine.bbs_calculator import round_supply
from exporters.logo import LogoError, normalize_logo
from gui import style
from gui.widgets import ShapePreview, shape_pixmap

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
    """Alta y edición de un elemento estructural.

    Su ubicación en la obra es opcional y tiene dos niveles de agrupación: el primero se llama como el proyecto lo
    indique (``group_label``: «Nivel» en un edificio, «Estructura» en un puente) y el segundo es la subestructura. Un
    elemento sin ninguno de los dos se lista directamente bajo el proyecto.
    """

    def __init__(self, parent: QWidget | None, element: StructuralElement | None = None,
                 levels: Collection[str] = (), substructures: Collection[str] = (), group_label: str = "Nivel") -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar elemento" if element else "Nuevo elemento")
        self.setMinimumWidth(420)

        self.name = QLineEdit(element.name if element else "")
        self.name.setPlaceholderText("p. ej. V-101")
        self.type = QComboBox()
        for element_type in ElementType:
            self.type.addItem(element_type.value, element_type)
        self.level = self._group_combo(levels, element.level if element else (list(levels)[-1] if levels else ""),
                                       f"sin {group_label.lower()}")
        self.substructure = self._group_combo(substructures, element.substructure if element else "", "sin subestructura")
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 100_000)
        self.quantity.setSuffix(" und")
        if element:
            self.type.setCurrentIndex(self.type.findData(element.element_type))
            self.quantity.setValue(element.quantity)

        form = QFormLayout()
        form.addRow("Nombre:", self.name)
        form.addRow("Tipo:", self.type)
        form.addRow(f"{group_label} (opcional):", self.level)
        form.addRow("Subestructura (opcional):", self.substructure)
        form.addRow("Cantidad de elementos iguales:", self.quantity)
        hint = QLabel("Si la obra no tiene niveles (un puente, por ejemplo), deje vacío lo que no aplique: el elemento se "
                      "lista bajo la estructura y la subestructura que indique, o directamente bajo el proyecto.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.buttons = _buttons(self)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self.buttons)

        self.name.textChanged.connect(self._validate)
        self._validate()

    @staticmethod
    def _group_combo(options: Collection[str], current: str, placeholder: str) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(list(dict.fromkeys(options)))
        combo.setCurrentText(current)
        combo.lineEdit().setPlaceholderText(f"({placeholder})")
        return combo

    def _validate(self) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.name.text().strip()))

    def values(self) -> tuple[str, ElementType, str, int, str]:
        """``(nombre, tipo, nivel, cantidad, subestructura)``; nivel y subestructura pueden quedar vacíos."""
        # Qt convierte el valor de un Enum que es ``str`` en texto plano: se recupera el ``ElementType``.
        return (self.name.text().strip(), ElementType(self.type.currentData()), self.level.currentText().strip(),
                self.quantity.value(), self.substructure.currentText().strip())


class ProjectDialog(QDialog):
    """Propiedades del proyecto: datos de encabezado de la planilla, logo, agrupación y parámetros de cálculo."""

    def __init__(self, parent: QWidget | None, project: Project) -> None:
        super().__init__(parent)
        self.setWindowTitle("Propiedades del proyecto")
        self.setMinimumWidth(520)
        self._logo = project.logo_png
        self.name = QLineEdit(project.name)
        self.name.setToolTip("Es la obra: aparece como «Proyecto» en el encabezado de la planilla.")
        self.client = QLineEdit(project.client)
        self.work_code = QLineEdit(project.work_code)
        self.schedule_number = QLineEdit(project.schedule_number)
        self.drawing = QLineEdit(project.drawing)
        self.global_position = QLineEdit(project.global_position)
        self.delivery_date = QLineEdit(project.delivery_date)
        self.delivery_date.setPlaceholderText("p. ej. 15/10/2026")
        self.author = QLineEdit(project.author)
        self.group_label = QComboBox()
        self.group_label.setEditable(True)
        self.group_label.addItems(["Nivel", "Estructura", "Tramo", "Sector", "Zona"])
        self.group_label.setCurrentText(project.group_label)
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
        self.reusable = QDoubleSpinBox()
        self.reusable.setRange(0, 12000)
        self.reusable.setDecimals(0)
        self.reusable.setSingleStep(100)
        self.reusable.setSuffix(" mm  (0 = ningún retal se reutiliza)")
        self.reusable.setValue(project.reusable_remnant_mm)
        self.paper = QComboBox()
        for text, value in _PAPERS:
            self.paper.addItem(text, value)
        self.paper.setCurrentIndex(self.paper.findData(project.paper))

        self.logo_preview = QLabel()
        self.logo_preview.setObjectName("shapePreview")
        self.logo_preview.setFixedSize(190, 60)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_choose = QPushButton("Elegir logo…")
        self.logo_clear = QPushButton("Quitar")
        self.logo_choose.clicked.connect(self._choose_logo)
        self.logo_clear.clicked.connect(lambda *_: self.set_logo(b""))
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_preview)
        logo_buttons = QVBoxLayout()
        logo_buttons.addWidget(self.logo_choose)
        logo_buttons.addWidget(self.logo_clear)
        logo_buttons.addStretch(1)
        logo_row.addLayout(logo_buttons)
        logo_row.addStretch(1)

        def title(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("sectionTitle")
            return label

        header = QFormLayout()
        header.addRow("Nombre del proyecto (obra):", self.name)
        header.addRow("Cliente:", self.client)
        header.addRow("Código de obra:", self.work_code)
        header.addRow("N° de planilla:", self.schedule_number)
        header.addRow("Plano:", self.drawing)
        header.addRow("Posición global:", self.global_position)
        header.addRow("Fecha de entrega:", self.delivery_date)
        header.addRow("Responsable:", self.author)
        header.addRow("Logo:", logo_row)
        grouping = QFormLayout()
        grouping.addRow("El primer grupo de elementos se llama:", self.group_label)
        calc = QFormLayout()
        calc.addRow("Longitud de la barra comercial:", self.stock)
        calc.addRow("Redondeo de la longitud de corte:", self.rounding)
        calc.addRow("Retal reutilizable desde:", self.reusable)
        calc.addRow("Papel del PDF:", self.paper)
        layout = QVBoxLayout(self)
        layout.addWidget(title("Encabezado de la planilla"))
        layout.addLayout(header)
        layout.addWidget(title("Agrupación de los elementos"))
        layout.addLayout(grouping)
        layout.addWidget(title("Cálculo e impresión"))
        layout.addLayout(calc)
        layout.addWidget(_buttons(self))
        self.set_logo(self._logo)

    # ------------------------------------------------------------------ logo
    def logo(self) -> bytes:
        """Logo elegido como PNG normalizado (vacío = sin logo)."""
        return self._logo

    def set_logo(self, png: bytes) -> None:
        self._logo = png
        pixmap = QPixmap()
        if png and pixmap.loadFromData(png):
            self.logo_preview.setPixmap(pixmap.scaled(self.logo_preview.size() - QSize(8, 8), Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))
        else:
            self.logo_preview.setPixmap(QPixmap())
            self.logo_preview.setText("sin logo")
        self.logo_clear.setEnabled(bool(png))

    def load_logo(self, path: Path) -> None:
        """Lee la imagen de ``path`` y la deja como logo; lanza ``LogoError`` si no es una imagen."""
        self.set_logo(normalize_logo(Path(path).read_bytes()))

    def _choose_logo(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Elegir logo", "", "Imágenes (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if not name:
            return
        try:
            self.load_logo(Path(name))
        except (LogoError, OSError) as error:
            QMessageBox.warning(self, "Logo no válido", str(error))

    def apply_to(self, project: Project) -> None:
        project.name = self.name.text().strip() or project.name
        project.author = self.author.text().strip()
        project.client = self.client.text().strip()
        project.work_code = self.work_code.text().strip()
        project.schedule_number = self.schedule_number.text().strip()
        project.drawing = self.drawing.text().strip()
        project.global_position = self.global_position.text().strip()
        project.delivery_date = self.delivery_date.text().strip()
        project.group_label = self.group_label.currentText().strip() or project.group_label
        project.logo_png = self._logo
        project.stock_length_mm = self.stock.value()
        project.length_rounding_mm = self.rounding.value()
        project.reusable_remnant_mm = self.reusable.value()
        project.paper = self.paper.currentData()


class LegsEditor(QWidget):
    """Editor de tramos y ángulos de giro de la forma personalizada.

    Cada fila es un tramo con su cota exterior y el giro del doblez que lo une al siguiente (positivo = a la
    izquierda, negativo = a la derecha; la última fila no tiene giro). El dibujo de la barra se actualiza al editar.
    """

    changed = Signal()

    def __init__(self, legs: tuple[float, ...], angles: tuple[float, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Tramo", "Longitud (mm)", "Giro al final (°)"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setFixedHeight(168)
        buttons = QHBoxLayout()
        for text, slot, tip in (
            ("Agregar tramo", self.add_leg, "Agrega un tramo al final de la barra"),
            ("Quitar", self.remove_leg, "Quita el tramo seleccionado (o el último)"),
            ("Invertir", self.reverse, "Recorre la barra en sentido contrario"),
            ("Reflejar", self.mirror, "Cambia izquierda por derecha en todos los giros"),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, f=slot: f())
            buttons.addWidget(button)
        buttons.addStretch(1)
        hint = QLabel("Giro: + a la izquierda, − a la derecha. Una L es un giro de 90°; una Z, +90° y −90°.")
        hint.setObjectName("hint")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        layout.addWidget(hint)
        self.set_values(legs, angles)

    def _spin(self, value: float, low: float, high: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(1)
        spin.setSingleStep(10)
        spin.setSuffix(suffix)
        spin.setValue(value)
        spin.valueChanged.connect(lambda *_: self.changed.emit())
        return spin

    def _fill(self, legs: tuple[float, ...], angles: tuple[float, ...]) -> None:
        self.table.setRowCount(len(legs))
        for row, leg in enumerate(legs):
            self.table.setItem(row, 0, _label_item(LETTERS[row % 26]))
            self.table.setCellWidget(row, 1, self._spin(leg, 0.1, 100_000, " mm"))
            last = row == len(legs) - 1
            spin = self._spin(0.0 if last else angles[row], -179.9, 179.9, " °")
            spin.setEnabled(not last)
            self.table.setCellWidget(row, 2, spin)

    def set_values(self, legs: tuple[float, ...], angles: tuple[float, ...]) -> None:
        self._fill(tuple(legs), tuple(angles) + (90.0,) * max(0, len(legs) - 1 - len(angles)))
        self.changed.emit()

    def values(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        legs = tuple(self.table.cellWidget(r, 1).value() for r in range(self.table.rowCount()))
        angles = tuple(self.table.cellWidget(r, 2).value() for r in range(self.table.rowCount() - 1))
        return legs, angles

    def add_leg(self) -> None:
        legs, angles = self.values()
        self.set_values(legs + (300.0,), angles + (90.0,))

    def remove_leg(self) -> None:
        legs, angles = self.values()
        if len(legs) <= 1:
            return
        row = self.table.currentRow()
        row = len(legs) - 1 if row < 0 else row
        new_legs = legs[:row] + legs[row + 1:]
        # el giro que unía este tramo con el siguiente desaparece; si era el último, se quita el giro anterior
        new_angles = angles[:row] + angles[row + 1:] if row < len(angles) else angles[:-1]
        self.set_values(new_legs, new_angles)

    def reverse(self) -> None:
        legs, angles = self.values()
        self.set_values(legs[::-1], tuple(-a for a in angles[::-1]))

    def mirror(self) -> None:
        legs, angles = self.values()
        self.set_values(legs, tuple(-a for a in angles))


def _label_item(text: str):
    from PySide6.QtWidgets import QTableWidgetItem

    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def _template_icon(cls: type[ShapeCode]) -> QIcon:
    try:
        return QIcon(shape_pixmap(cls.template(), 96, 36))
    except Exception:  # noqa: BLE001 - una plantilla que no se pueda dibujar no debe impedir abrir el diálogo
        return QIcon()


class BarDialog(QDialog):
    """Alta y edición de una marca de barras, con el esquema y la longitud de corte en vivo.

    La forma se elige de una galería de plantillas (con miniatura) y el formulario de parámetros se genera a partir
    de los parámetros declarados por la forma (:meth:`~core.shape_codes.ShapeCode.parameters`): cotas, ángulos,
    ganchos, estilo… Así cualquier forma registrada con ``@register_shape`` aparece sin tocar la interfaz. La forma
    «Personalizada» abre además un editor de tramos y ángulos.
    """

    def __init__(self, parent: QWidget | None, *, group: RebarGroup | None = None, suggested_mark: str = "A1",
                 used_marks: Collection[str] = (), stock_length_mm: float = 12_000.0,
                 rounding_mm: float = 5.0) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar barra" if group else "Nueva barra")
        self.setMinimumWidth(1020)
        self._used_marks = set(used_marks)
        self._stock = stock_length_mm
        self._rounding = rounding_mm
        self._widgets: dict[str, QWidget] = {}
        self._editor: LegsEditor | None = None
        self._built_for: type[ShapeCode] | None = None  # plantilla a la que pertenecen los controles actuales
        self._remembered: dict[str, object] = {}
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
        self.shape.setIconSize(QSize(96, 36))
        self.shape.setMaxVisibleItems(18)
        for code, cls in available_shapes().items():
            self.shape.addItem(_template_icon(cls), f"{code} · {cls.name}", cls)
        self.shape_hint = QLabel()
        self.shape_hint.setObjectName("hint")
        self.shape_hint.setWordWrap(True)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1_000_000)
        self.quantity.setValue(group.quantity if group else 1)
        self.quantity.setSuffix(" por elemento")
        self.description = QLineEdit(group.description if group else "")
        self.description.setPlaceholderText("p. ej. Refuerzo inferior")

        self.param_form = QFormLayout()
        self.preview = ShapePreview(420, 158)
        self.info = QLabel()
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setWordWrap(True)
        self.info.setMinimumHeight(120)
        self.info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        top = QFormLayout()
        top.addRow("Marca:", self.mark)
        top.addRow("Barra:", self.bar)
        top.addRow("Grado:", self.grade)
        top.addRow("Plantilla de forma:", self.shape)
        top.addRow("", self.shape_hint)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        bottom = QFormLayout()
        bottom.addRow("Cantidad:", self.quantity)
        bottom.addRow("Descripción:", self.description)
        self.buttons = _buttons(self)

        form_column = QVBoxLayout()
        form_column.addLayout(top)
        form_column.addWidget(separator)
        form_column.addLayout(self.param_form)
        form_column.addLayout(bottom)
        form_column.addStretch(1)
        result_column = QVBoxLayout()
        result_column.addWidget(self.preview)
        result_column.addWidget(self.info)
        result_column.addStretch(1)
        columns = QHBoxLayout()
        columns.addLayout(form_column, 5)
        columns.addSpacing(10)
        columns.addLayout(result_column, 4)
        layout = QVBoxLayout(self)
        layout.addLayout(columns)
        layout.addWidget(self.buttons)

        if group:
            self.bar.setCurrentIndex(self.bar.findData(group.rebar.designation))
            self.grade.setCurrentIndex(next((i for i, g in enumerate(_GRADES) if g == group.rebar.grade), 1))
            self.shape.setCurrentIndex(self.shape.findData(type(group.shape)))
            self._remembered = {spec.name: getattr(group.shape, spec.name) for spec in type(group.shape).parameters()}
        self._rebuild_params()

        self.mark.textChanged.connect(self._update)
        self.bar.currentIndexChanged.connect(self._update)
        self.grade.currentIndexChanged.connect(self._update)
        self.quantity.valueChanged.connect(self._update)
        self.shape.currentIndexChanged.connect(self._shape_changed)
        self._update()

    # ------------------------------------------------------------------ parámetros dinámicos
    def _shape_class(self) -> type[ShapeCode]:
        return self.shape.currentData()

    def _shape_changed(self) -> None:
        self._remember_values()
        self._rebuild_params()
        self._update()

    def _read(self, spec: ParamSpec) -> object:
        widget = self._widgets[spec.name]
        if isinstance(widget, LegsEditor):
            return widget.values()[0]
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QSpinBox):
            return widget.value()
        value = widget.value()
        return None if spec.optional and value == 0.0 else value

    def _remember_values(self) -> None:
        """Guarda lo que el usuario editó para llevarlo a la nueva plantilla; lo que sigue en su valor por defecto
        no se arrastra (cada plantilla muestra sus propios valores)."""
        if self._built_for is None:
            return
        specs = {spec.name: spec for spec in self._built_for.parameters()}
        for name, spec in specs.items():
            if name in self._widgets:
                value = self._read(spec)
                if value == spec.default or (spec.kind == "lengths" and tuple(value) == tuple(spec.default)):
                    self._remembered.pop(name, None)
                else:
                    self._remembered[name] = value
        if self._editor is not None:
            angles = self._editor.values()[1]
            if "legs" in self._remembered or angles != tuple(specs["angles"].default):
                self._remembered["angles"] = angles
            else:
                self._remembered.pop("angles", None)

    def _make_widget(self, spec: ParamSpec) -> QWidget:
        value = self._remembered.get(spec.name, spec.default)
        if spec.kind == "choice":
            combo = QComboBox()
            for option, text in spec.choices:
                combo.addItem(text, option)
            index = combo.findData(value)
            combo.setCurrentIndex(index if index >= 0 else max(0, combo.findData(spec.default)))
            combo.currentIndexChanged.connect(lambda *_: self._update())
            return combo
        if spec.kind == "count":
            spin = QSpinBox()
            spin.setRange(int(spec.minimum or 1), int(spec.maximum or 100_000))
            spin.setValue(int(value))
            spin.valueChanged.connect(lambda *_: self._update())
            return spin
        if spec.kind == "lengths":
            angles = tuple(self._remembered.get("angles", ()))
            editor = LegsEditor(tuple(value), angles)
            editor.changed.connect(self._update)
            self._editor = editor
            return editor
        spin = QDoubleSpinBox()
        spin.setSingleStep(10)
        if spec.kind == "angle":
            spin.setDecimals(1)
            spin.setRange(spec.minimum if spec.minimum is not None else 0.1, spec.maximum if spec.maximum is not None else 179.9)
            spin.setSuffix(" °")
        elif spec.kind == "number":
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            spin.setRange(spec.minimum if spec.minimum is not None else 0.01, spec.maximum if spec.maximum is not None else 100_000)
        else:  # length
            spin.setDecimals(1)
            spin.setRange(spec.minimum if spec.minimum is not None else (0 if spec.optional else 0.1), _MAX_DIMENSION_MM)
            spin.setSuffix(" mm")
            if spec.optional:
                spin.setSpecialValueText(spec.auto_text or "estándar (según norma)")
        spin.setValue(0.0 if value is None else float(value))
        spin.valueChanged.connect(lambda *_: self._update())
        return spin

    def _rebuild_params(self) -> None:
        while self.param_form.rowCount():
            self.param_form.removeRow(0)
        self._widgets = {}
        self._editor = None
        cls = self._built_for = self._shape_class()
        self.shape_hint.setText(cls.description)
        for spec in cls.parameters():
            if spec.hidden:
                continue
            widget = self._make_widget(spec)
            self._widgets[spec.name] = widget
            if spec.kind == "lengths":
                self.param_form.addRow(widget)
            else:
                self.param_form.addRow(f"{spec.label}:", widget)

    def _sync_dependencies(self) -> None:
        """Deshabilita los parámetros que no aplican con las opciones elegidas (p. ej. el traslape si la unión es coupler)."""
        specs = self._shape_class().parameters()
        values = {spec.name: self._read(spec) for spec in specs if spec.name in self._widgets and not spec.depends}
        for spec in specs:
            widget = self._widgets.get(spec.name)
            if widget is None or not spec.depends:
                continue
            active = spec.active(values)
            widget.setEnabled(active)
            label = self.param_form.labelForField(widget)
            if label is not None:
                label.setEnabled(active)
            values[spec.name] = self._read(spec) if active else None  # lo que depende de uno inactivo también lo está

    def _build_shape(self) -> ShapeCode:
        values: dict[str, object] = {}
        for spec in self._shape_class().parameters():
            if spec.hidden and spec.kind == "angles" and self._editor is not None:
                values[spec.name] = self._editor.values()[1]
            elif spec.name in self._widgets:
                values[spec.name] = self._read(spec)
        return self._shape_class()(**values)

    # ------------------------------------------------------------------ cálculo en vivo
    def _update(self) -> None:
        if not self._widgets:  # durante la construcción del formulario
            return
        self._sync_dependencies()
        self._group = None
        error: str | None = None
        shape: ShapeCode | None = None
        rebar = None
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
            supply = round_supply(shape.supply(rebar, self._stock), self._stock, self._rounding)
            pieces = supply.pieces_mm
            rounded = supply.material_mm
            if not supply.coil and max(pieces) > self._stock + 1e-6:
                raise ValueError(
                    f"La barra mide {max(pieces) / 1000:.2f} m y excede la barra comercial de {self._stock / 1000:.2f} m; "
                    "divídala en barras traslapadas."
                )
            weight = rebar.mass_for_length(rounded / 1000)
            theme = style.current()
            length = f"{cut.total_mm:,.1f} mm → {rounded:,.0f} mm" if len(pieces) == 1 else f"{rounded:,.0f} mm"
            html = (
                f"<b>Longitud de corte: {length}</b>"
                f" &nbsp;·&nbsp; peso unitario <b>{weight:,.2f} kg</b><br>"
                f"<span style='color:{theme.muted}'>Σ cotas {cut.dimension_sum_mm:,.1f} mm &nbsp;·&nbsp; dobleces "
                f"{cut.bend_adjustment_mm:+,.1f} mm &nbsp;·&nbsp; extensiones {cut.extension_mm:+,.1f} mm</span>"
            )
            if len(pieces) > 1:
                html += (f"<br><span style='color:{theme.muted}'>Desarrollo de la forma {cut.total_mm:,.1f} mm; "
                         f"acero por unidad {rounded:,.0f} mm</span>")
                html += f"<br><b>{len(pieces)} barras: {escape(pieces_text(pieces))}</b>"
                for sub_mark, part in supply.sub_marks(mark):
                    detail = f" &nbsp;·&nbsp; {escape(part.thread_text)}" if part.thread_text else ""
                    html += (f"<br>&nbsp;&nbsp;<b>{escape(sub_mark)}</b> ×{part.count} &nbsp;·&nbsp; "
                             f"{part.length_mm:,.0f} mm{detail}")
            if cut.hooks:
                html += f"<br><span style='color:{theme.hook}'>Ganchos (° · mm): {escape(cut.hook_text)}</span>"
            threads = supply.threads if supply.parts else cut.couplers
            if threads:
                html += f"<br><span style='color:{theme.coupler}'>Roscas para acoplador: {escape(coupler_text(threads))}</span>"
            html += "".join(f"<br><span style='color:{theme.muted}'>{escape(n)}</span>" for n in cut.notes + supply.notes)
            html += "".join(f"<br><span style='color:{theme.red}'><b>Aviso:</b> {escape(w)}</span>"
                            for w in cut.warnings + supply.warnings)
            self._group = group
        except (GeometryError, ValueError, TypeError) as exc:
            error = str(exc)
        if error:
            html = f"<span style='color:{style.current().red}'><b>{escape(error)}</b></span>"
        self.info.setText(html)
        self.preview.set_shape(shape if error is None else None, "Corrija los datos\npara ver el esquema", rebar)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self._group is not None)

    def result_group(self) -> RebarGroup:
        """Grupo de barras definido en el diálogo (solo válido tras aceptar)."""
        if self._group is None:
            raise ValueError("Los datos de la barra no son válidos.")
        return self._group
