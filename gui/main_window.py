"""Ventana principal: árbol del proyecto, barras del elemento, planilla, resumen y exportación."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDockWidget, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSplitter, QStyle,
    QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.element import ElementType, StructuralElement
from core.project import Project
from core.serialization import FILE_SUFFIX, load_project, save_project
from engine.bbs_calculator import BBSCalculator, BBSResult, ScheduleLine, dimension_labels
from exporters.excel_exporter import ExcelExporter
from exporters.pdf_exporter import PdfExporter
from gui.dialogs import BarDialog, ElementDialog, ProjectDialog
from gui.tables import CuttingPlanTable, ScheduleTable, SummaryView
from gui.widgets import BarDetailPanel
from sample_project import build_catalog_project, build_project

_PROJECT_FILTER = f"Proyecto RebarFlow (*{FILE_SUFFIX})"


class MainWindow(QMainWindow):
    """Editor de planillas de despiece."""

    def __init__(self, project: Project | None = None, path: Path | None = None) -> None:
        super().__init__()
        self.project = project or Project()
        self.path = path
        self.modified = False
        self.result: BBSResult | None = None
        self.error: str | None = None
        self._element: StructuralElement | None = None

        self._build_ui()
        self._build_actions()
        self.resize(1520, 900)
        self.refresh()

    # ------------------------------------------------------------------ construcción
    def _build_ui(self) -> None:
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Proyecto")
        self.tree.setMinimumWidth(220)
        self.tree.currentItemChanged.connect(self._on_tree_selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_element())

        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)

        self.element_title = QLabel()
        self.element_title.setObjectName("elementTitle")
        self.btn_add_bar = QPushButton("Nueva barra")
        self.btn_edit_bar = QPushButton("Editar")
        self.btn_delete_bar = QPushButton("Eliminar")
        self.btn_add_bar.clicked.connect(self.add_bar)
        self.btn_edit_bar.clicked.connect(self.edit_bar)
        self.btn_delete_bar.clicked.connect(self.delete_bar)
        header = QHBoxLayout()
        header.addWidget(self.element_title, stretch=1)
        for button in (self.btn_add_bar, self.btn_edit_bar, self.btn_delete_bar):
            header.addWidget(button)

        self.bars_table = ScheduleTable(grouped=False)
        self.bars_table.itemSelectionChanged.connect(self._on_bar_selection)
        self.bars_table.doubleClicked.connect(lambda *_: self.edit_bar())
        element_tab = QWidget()
        element_layout = QVBoxLayout(element_tab)
        element_layout.setContentsMargins(8, 8, 8, 8)
        element_layout.addLayout(header)
        element_layout.addWidget(self.bars_table)

        self.project_table = ScheduleTable(grouped=True)
        self.project_table.itemSelectionChanged.connect(self._on_project_row_selection)
        self.summary = SummaryView()
        self.plan_table = CuttingPlanTable()

        self.tabs = QTabWidget()
        self.tabs.addTab(element_tab, "Barras del elemento")
        self.tabs.addTab(self.project_table, "Planilla del proyecto")
        self.tabs.addTab(self.summary, "Resumen")
        self.tabs.addTab(self.plan_table, "Plan de corte")

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self.banner)
        center_layout.addWidget(self.tabs, stretch=1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(center)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 900])
        self.setCentralWidget(splitter)

        self.detail = BarDetailPanel()
        self.detail_dock = QDockWidget("Detalle de barra", self)
        self.detail_dock.setWidget(self.detail)
        self.detail_dock.setMinimumWidth(380)
        self.detail_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.detail_dock)

        self.totals_label = QLabel()
        self.statusBar().addPermanentWidget(self.totals_label)

    def _action(self, text: str, slot, *, icon: QStyle.StandardPixmap | None = None, shortcut=None,
                tip: str = "") -> QAction:
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.setStatusTip(tip or text)
        action.triggered.connect(lambda *_: slot())
        return action

    def _build_actions(self) -> None:
        sp = QStyle.StandardPixmap
        self.act_new = self._action("Nuevo", self.new_project, icon=sp.SP_FileIcon, shortcut=QKeySequence.StandardKey.New)
        self.act_open = self._action("Abrir…", self.open_project, icon=sp.SP_DialogOpenButton,
                                     shortcut=QKeySequence.StandardKey.Open)
        self.act_sample = self._action("Abrir ejemplo", self.open_sample, icon=sp.SP_DirHomeIcon,
                                       tip="Carga un proyecto de ejemplo (cimentación y 2 niveles)")
        self.act_catalog = self._action("Abrir ejemplo: catálogo de formas", self.open_catalog,
                                        tip="Carga un proyecto con una barra de cada plantilla de forma")
        self.act_save = self._action("Guardar", self.save_project_file, icon=sp.SP_DialogSaveButton,
                                     shortcut=QKeySequence.StandardKey.Save)
        self.act_save_as = self._action("Guardar como…", self.save_project_as, shortcut=QKeySequence.StandardKey.SaveAs)
        self.act_props = self._action("Propiedades del proyecto…", self.edit_project_properties,
                                      icon=sp.SP_FileDialogDetailedView)
        self.act_quit = self._action("Salir", self.close, shortcut=QKeySequence.StandardKey.Quit)

        self.act_add_element = self._action("Nuevo elemento", self.add_element, icon=sp.SP_FileDialogNewFolder,
                                            shortcut="Ctrl+Shift+N")
        self.act_edit_element = self._action("Editar elemento", self.edit_element, icon=sp.SP_FileDialogContentsView)
        self.act_delete_element = self._action("Eliminar elemento", self.delete_element, icon=sp.SP_TrashIcon)
        self.act_add_bar = self._action("Nueva barra", self.add_bar, icon=sp.SP_FileDialogStart, shortcut="Ctrl+B")
        self.act_edit_bar = self._action("Editar barra", self.edit_bar, icon=sp.SP_FileDialogInfoView)
        self.act_delete_bar = self._action("Eliminar barra", self.delete_bar, icon=sp.SP_DialogDiscardButton)
        self.act_excel = self._action("Exportar a Excel…", self.export_excel, icon=sp.SP_ArrowDown, shortcut="Ctrl+E",
                                      tip="Planilla en Excel con el esquema de cada barra")
        self.act_pdf = self._action("Exportar a PDF…", self.export_pdf, icon=sp.SP_DialogSaveButton, shortcut="Ctrl+P",
                                    tip="Planilla en PDF con el esquema de cada barra")
        self.act_about = self._action("Acerca de RebarFlow", self.about)
        # Mostrar u ocultar el panel de detalle (la X del panel lo cierra; esta acción lo vuelve a abrir).
        self.act_detail = self.detail_dock.toggleViewAction()
        self.act_detail.setText("Detalle de barra")
        self.act_detail.setShortcut("F4")
        self.act_detail.setIcon(self.style().standardIcon(sp.SP_FileDialogInfoView))
        self.act_detail.setStatusTip("Muestra u oculta el panel con el dibujo grande y el cálculo de la barra seleccionada")

        toolbar = QToolBar("Principal")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for group in ((self.act_new, self.act_open, self.act_save),
                      (self.act_add_element, self.act_add_bar, self.act_edit_bar, self.act_delete_bar),
                      (self.act_excel, self.act_pdf)):
            for action in group:
                toolbar.addAction(action)
            toolbar.addSeparator()
        toolbar.addAction(self.act_detail)
        self.addToolBar(toolbar)

        menu = self.menuBar()
        file_menu = menu.addMenu("&Archivo")
        for action in (self.act_new, self.act_open, self.act_sample, self.act_catalog, None, self.act_save, self.act_save_as, None,
                       self.act_props, None, self.act_excel, self.act_pdf, None, self.act_quit):
            file_menu.addSeparator() if action is None else file_menu.addAction(action)
        element_menu = menu.addMenu("&Elemento")
        for action in (self.act_add_element, self.act_edit_element, self.act_delete_element):
            element_menu.addAction(action)
        bar_menu = menu.addMenu("&Barra")
        for action in (self.act_add_bar, self.act_edit_bar, self.act_delete_bar):
            bar_menu.addAction(action)
        menu.addMenu("&Ver").addAction(self.act_detail)
        menu.addMenu("A&yuda").addAction(self.act_about)

        # Ins / Supr actúan sobre la lista de barras cuando tiene el foco.
        for action, key in ((self.act_delete_bar, "Delete"), (self.act_edit_bar, "Return")):
            shortcut = QAction(self)
            shortcut.setShortcut(key)
            shortcut.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.triggered.connect(lambda *_, a=action: a.trigger())
            self.bars_table.addAction(shortcut)

    # ------------------------------------------------------------------ estado y refresco
    def current_element(self) -> StructuralElement | None:
        return self._element

    def current_line(self) -> ScheduleLine | None:
        rows = self.bars_table.selectionModel().selectedRows()
        return self.bars_table.line_for_row(rows[0].row()) if rows else None

    def refresh(self, select: StructuralElement | None = None, select_mark: str | None = None) -> None:
        """Recalcula la planilla y reconstruye el árbol y las tablas conservando la selección."""
        target = select or self._element
        try:
            self.result = BBSCalculator(self.project.stock_length_mm, self.project.length_rounding_mm,
                          self.project.reusable_remnant_mm).calculate(
                self.project.elements)
            self.error = None
        except ValueError as exc:  # p. ej. una barra mayor que la comercial
            self.result, self.error = None, str(exc)

        self._rebuild_tree(target)
        self._fill_tables(select_mark)
        self._update_chrome()

    def _rebuild_tree(self, target: StructuralElement | None) -> None:
        style = self.style()
        self.tree.blockSignals(True)
        self.tree.clear()
        root = QTreeWidgetItem([self.project.name])
        root.setIcon(0, style.standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon))
        self.tree.addTopLevelItem(root)
        level_items: dict[str, QTreeWidgetItem] = {}
        selected_item: QTreeWidgetItem | None = None
        for index, element in enumerate(self.project.elements):
            if element.level not in level_items:
                level_item = QTreeWidgetItem(root, [element.level])
                level_item.setIcon(0, style.standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                level_items[element.level] = level_item
            item = QTreeWidgetItem(level_items[element.level],
                                   [f"{element.name}  ·  {element.element_type.value}  ×{element.quantity}"])
            item.setIcon(0, style.standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            if element is target:
                selected_item = item
        self.tree.expandAll()
        if selected_item is None and self.project.elements:
            selected_item = level_items[self.project.elements[0].level].child(0)
        self._element = None
        if selected_item is not None:
            self._element = self.project.elements[selected_item.data(0, Qt.ItemDataRole.UserRole)]
        self.tree.setCurrentItem(selected_item or root)
        self.tree.blockSignals(False)

    def _element_schedule(self):
        if self.result is None or self._element is None:
            return None
        return next((s for s in self.result.element_schedules if s.element is self._element), None)

    def _fill_tables(self, select_mark: str | None = None) -> None:
        schedules = self.result.element_schedules if self.result else []
        self.project_table.populate(schedules, self.result.dimension_labels if self.result else ["A"])
        schedule = self._element_schedule()
        self.bars_table.populate([schedule] if schedule else [], dimension_labels(schedule.lines) if schedule else ["A"])
        self.summary.populate(self.result)
        self.plan_table.populate(self.result)
        if select_mark is not None and (row := self.bars_table.row_of(select_mark)) is not None:
            self.bars_table.selectRow(row)
        self._on_bar_selection()

    def _update_chrome(self) -> None:
        element = self._element
        if element is not None:
            self.element_title.setText(
                f"<b>{element.name}</b> &nbsp;·&nbsp; {element.element_type.value} &nbsp;·&nbsp; {element.level} "
                f"&nbsp;·&nbsp; {element.quantity} und")
        else:
            self.element_title.setText("Seleccione un elemento del árbol, o cree uno con «Nuevo elemento».")
        self.banner.setVisible(self.error is not None)
        self.banner.setText(f"No se puede calcular la planilla: {self.error}" if self.error else "")

        has_element = element is not None
        for widget in (self.act_edit_element, self.act_delete_element, self.act_add_bar, self.btn_add_bar):
            widget.setEnabled(has_element)
        self._on_bar_selection()
        exportable = self.result is not None and bool(self.result.lines)
        self.act_excel.setEnabled(exportable)
        self.act_pdf.setEnabled(exportable)

        if self.result is not None and self.result.lines:
            r = self.result
            self.totals_label.setText(
                f"Peso neto {r.total_weight_kg:,.1f} kg   ·   a comprar {r.total_purchase_weight_kg:,.1f} kg "
                f"({sum(s.stock_bars for s in r.diameter_summaries)} barras de {r.stock_length_mm / 1000:.0f} m)   ·   "
                f"desperdicio {r.total_waste_pct:.1%}   ·   {len(r.lines)} marcas")
        else:
            self.totals_label.setText("Sin barras")
        marker = "*" if self.modified else ""
        self.setWindowTitle(f"{marker}{self.project.name} — RebarFlow")

    def _mark_modified(self) -> None:
        self.modified = True

    # ------------------------------------------------------------------ selección
    def _on_tree_selection(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        index = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        self._element = self.project.elements[index] if index is not None else None
        self._fill_tables()
        self._update_chrome()

    def _on_bar_selection(self) -> None:
        line = self.current_line()
        for widget in (self.act_edit_bar, self.act_delete_bar, self.btn_edit_bar, self.btn_delete_bar):
            widget.setEnabled(line is not None)
        if line is not None or self.tabs.currentIndex() == 0:
            self.detail.show_line(line)

    def _on_project_row_selection(self) -> None:
        rows = self.project_table.selectionModel().selectedRows()
        if rows:
            self.detail.show_line(self.project_table.line_for_row(rows[0].row()))

    # ------------------------------------------------------------------ elementos
    def _check_unique(self, name: str, level: str, ignore: StructuralElement | None = None) -> None:
        for other in self.project.elements:
            if other is not ignore and other.name == name and other.level == level:
                raise ValueError(f"Ya existe el elemento {name!r} en {level!r}.")

    def add_element_values(self, name: str, element_type: ElementType, level: str, quantity: int) -> StructuralElement:
        self._check_unique(name, level)
        element = StructuralElement(name, element_type, level, quantity)
        self.project.elements.append(element)
        self._mark_modified()
        self.refresh(select=element)
        return element

    def update_element_values(self, element: StructuralElement, name: str, element_type: ElementType, level: str,
                              quantity: int) -> None:
        self._check_unique(name, level, ignore=element)
        element.name, element.element_type, element.level, element.quantity = name, element_type, level, quantity
        self._mark_modified()
        self.refresh(select=element)

    def delete_element_object(self, element: StructuralElement) -> None:
        index = next(i for i, e in enumerate(self.project.elements) if e is element)
        del self.project.elements[index]
        self._element = None
        self._mark_modified()
        self.refresh()

    def add_element(self) -> None:
        dialog = ElementDialog(self, levels=self.project.levels)
        if dialog.exec():
            try:
                self.add_element_values(*dialog.values())
            except ValueError as exc:
                QMessageBox.warning(self, "Elemento duplicado", str(exc))

    def edit_element(self) -> None:
        element = self._element
        if element is None:
            return
        dialog = ElementDialog(self, element, self.project.levels)
        if dialog.exec():
            try:
                self.update_element_values(element, *dialog.values())
            except ValueError as exc:
                QMessageBox.warning(self, "Elemento duplicado", str(exc))

    def delete_element(self) -> None:
        element = self._element
        if element is None:
            return
        if self._ask("Eliminar elemento",
                     f"¿Eliminar el elemento {element.name} ({element.level}) y sus {len(element.groups)} marcas de barras?"):
            self.delete_element_object(element)

    # ------------------------------------------------------------------ barras
    @staticmethod
    def _next_mark(element: StructuralElement) -> str:
        used = {g.mark for g in element.groups}
        n = len(used) + 1
        while f"A{n}" in used:
            n += 1
        return f"A{n}"

    def _bar_dialog(self, element: StructuralElement, group=None) -> BarDialog:
        others = [g.mark for g in element.groups if g is not group]
        return BarDialog(self, group=group, suggested_mark=self._next_mark(element), used_marks=others,
                         stock_length_mm=self.project.stock_length_mm, rounding_mm=self.project.length_rounding_mm)

    def add_group(self, element: StructuralElement, group) -> None:
        element.groups.append(group)
        self._mark_modified()
        self.refresh(select=element, select_mark=group.mark)

    def replace_group(self, element: StructuralElement, old, new) -> None:
        index = next(i for i, g in enumerate(element.groups) if g is old)
        element.groups[index] = new
        self._mark_modified()
        self.refresh(select=element, select_mark=new.mark)

    def delete_group(self, element: StructuralElement, group) -> None:
        index = next(i for i, g in enumerate(element.groups) if g is group)
        del element.groups[index]
        self._mark_modified()
        self.refresh(select=element)

    def add_bar(self) -> None:
        element = self._element
        if element is None:
            return
        dialog = self._bar_dialog(element)
        if dialog.exec():
            self.add_group(element, dialog.result_group())

    def edit_bar(self) -> None:
        element, line = self._element, self.current_line()
        if element is None or line is None:
            return
        dialog = self._bar_dialog(element, line.group)
        if dialog.exec():
            self.replace_group(element, line.group, dialog.result_group())

    def delete_bar(self) -> None:
        element, line = self._element, self.current_line()
        if element is None or line is None:
            return
        if self._ask("Eliminar barra", f"¿Eliminar la marca {line.mark} de {element.name}?"):
            self.delete_group(element, line.group)

    # ------------------------------------------------------------------ proyecto y archivos
    def edit_project_properties(self) -> None:
        dialog = ProjectDialog(self, self.project)
        if dialog.exec():
            dialog.apply_to(self.project)
            self._mark_modified()
            self.refresh()

    def _ask(self, title: str, text: str) -> bool:
        """Pregunta de sí/no con los botones en español."""
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self)
        yes = box.addButton("Sí", QMessageBox.ButtonRole.YesRole)
        box.addButton("No", QMessageBox.ButtonRole.NoRole)
        box.exec()
        return box.clickedButton() is yes

    def _confirm_discard(self) -> bool:
        if not self.modified:
            return True
        box = QMessageBox(QMessageBox.Icon.Question, "Cambios sin guardar",
                          f"El proyecto «{self.project.name}» tiene cambios sin guardar. ¿Guardarlos?", parent=self)
        save = box.addButton("Guardar", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return self.save_project_file()
        return box.clickedButton() is discard

    def set_project(self, project: Project, path: Path | None = None) -> None:
        self.project, self.path, self.modified, self._element = project, path, False, None
        self.refresh()

    def new_project(self) -> None:
        if self._confirm_discard():
            self.set_project(Project())

    def open_sample(self) -> None:
        if self._confirm_discard():
            self.set_project(build_project())

    def open_catalog(self) -> None:
        if self._confirm_discard():
            self.set_project(build_catalog_project())

    def open_path(self, path: Path) -> bool:
        try:
            self.set_project(load_project(path), path)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "No se pudo abrir el proyecto", f"{path.name}: {exc}")
            return False
        return True

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        name, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", "", f"{_PROJECT_FILTER};;Todos los archivos (*)")
        if name:
            self.open_path(Path(name))

    def write_project(self, path: Path) -> None:
        save_project(self.project, path)
        self.path, self.modified = path, False
        self._update_chrome()
        self.statusBar().showMessage(f"Proyecto guardado en {path}", 6000)

    def save_project_file(self) -> bool:
        if self.path is None:
            return self.save_project_as()
        try:
            self.write_project(self.path)
        except OSError as exc:
            QMessageBox.critical(self, "No se pudo guardar", str(exc))
            return False
        return True

    def save_project_as(self) -> bool:
        suggested = (self.path or Path(self.project.name.replace(" ", "_") + FILE_SUFFIX)).as_posix()
        name, _ = QFileDialog.getSaveFileName(self, "Guardar proyecto", suggested, _PROJECT_FILTER)
        if not name:
            return False
        path = Path(name)
        if path.suffix != FILE_SUFFIX:
            path = path.with_suffix(FILE_SUFFIX)
        try:
            self.write_project(path)
        except OSError as exc:
            QMessageBox.critical(self, "No se pudo guardar", str(exc))
            return False
        return True

    # ------------------------------------------------------------------ exportación
    def write_excel(self, path: Path) -> Path:
        if self.result is None:
            raise ValueError(self.error or "No hay planilla que exportar.")
        return ExcelExporter(self.project.name, self.project.author).export(self.result, path)

    def write_pdf(self, path: Path) -> Path:
        if self.result is None:
            raise ValueError(self.error or "No hay planilla que exportar.")
        return PdfExporter(self.project.name, self.project.author, page_size=self.project.paper).export(
            self.result, path)

    def _export(self, kind: str, suffix: str, writer) -> None:
        suggested = Path(self.project.name.replace(" ", "_") + suffix).as_posix()
        name, _ = QFileDialog.getSaveFileName(self, f"Exportar a {kind}", suggested, f"{kind} (*{suffix})")
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        try:
            writer(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, f"No se pudo exportar a {kind}", str(exc))
            return
        self.statusBar().showMessage(f"Planilla exportada a {path}", 8000)
        if self._ask("Exportación completa", f"Se creó {path.name}.\n¿Abrirlo ahora?"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def export_excel(self) -> None:
        self._export("Excel", ".xlsx", self.write_excel)

    def export_pdf(self) -> None:
        self._export("PDF", ".pdf", self.write_pdf)

    # ------------------------------------------------------------------ varios
    def about(self) -> None:
        QMessageBox.about(
            self, "Acerca de RebarFlow",
            "<b>RebarFlow</b><br>Planillas de despiece de acero de refuerzo (BBS).<br><br>"
            "Cotas exteriores; ganchos y dobleces según ACI 318 / NSR-10. Verifique los valores contra la norma "
            "vigente de su proyecto.")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (API de Qt)
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
