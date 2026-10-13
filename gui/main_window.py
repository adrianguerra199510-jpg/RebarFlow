"""Ventana principal: árbol del proyecto, barras del elemento, planilla, resumen y exportación."""

from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSplitter, QTabWidget, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.element import ElementType, StructuralElement
from core.project import DEFAULT_PROJECT_NAME, Project
from core.serialization import FILE_SUFFIX, load_project, project_from_dict, project_to_dict, save_project
from engine.bbs_calculator import BBSCalculator, BBSResult, ScheduleLine
from exporters.excel_exporter import ExcelExporter
from exporters.pdf_exporter import PdfExporter
from gui import style
from gui.dialogs import BarDialog, ElementDialog, ProjectDialog
from gui import icons
from gui.icon import theme_icon
from gui.project_bar import ProjectBar
from gui.session import ProjectSession
from gui.tables import CuttingPlanTable, ScheduleTable, SummaryView
from gui.widgets import BarDetailPanel
from sample_project import build_bridge_project, build_catalog_project, build_project

_PROJECT_FILTER = f"Proyecto RebarFlow (*{FILE_SUFFIX})"


class MainWindow(QMainWindow):
    """Editor de planillas de despiece con varios proyectos abiertos.

    Cada proyecto abierto es una :class:`~gui.session.ProjectSession` y una pestaña de la cinta de proyectos; ``project``,
    ``path``, ``modified`` y el elemento seleccionado son siempre los del proyecto activo.
    """

    def __init__(self, project: Project | None = None, path: Path | None = None) -> None:
        super().__init__()
        self.sessions: list[ProjectSession] = [ProjectSession(project or Project(), path)]
        self._index = 0
        self.result: BBSResult | None = None
        self.error: str | None = None
        self._icon_names: dict[QAction, str] = {}

        self._build_ui()
        self._build_actions()
        self.resize(1520, 900)
        self.refresh()

    # ------------------------------------------------------------------ proyecto activo
    @property
    def session(self) -> ProjectSession:
        """El proyecto activo (el de la pestaña seleccionada de la cinta)."""
        return self.sessions[self._index]

    @property
    def project(self) -> Project:
        return self.session.project

    @project.setter
    def project(self, value: Project) -> None:
        self.session.project = value

    @property
    def path(self) -> Path | None:
        return self.session.path

    @path.setter
    def path(self, value: Path | None) -> None:
        self.session.path = value

    @property
    def modified(self) -> bool:
        return self.session.modified

    @modified.setter
    def modified(self, value: bool) -> None:
        self.session.modified = value

    @property
    def _element(self) -> StructuralElement | None:
        return self.session.element

    @_element.setter
    def _element(self, value: StructuralElement | None) -> None:
        self.session.element = value

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

    def _action(self, text: str, slot, *, icon: str | None = None, shortcut=None, tip: str = "") -> QAction:
        """Acción de la ventana; ``icon`` es el nombre de un icono de :mod:`gui.icons` (se repinta al cambiar de tema)."""
        action = QAction(text, self)
        if icon is not None:
            self._icon_names[action] = icon
            action.setIcon(icons.icon(icon))
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.setStatusTip(tip or text)
        action.triggered.connect(lambda *_: slot())
        return action

    def _apply_icons(self) -> None:
        """Vuelve a pedir los iconos con la paleta del tema actual (tras cambiar de claro a nocturno o al revés)."""
        for action, name in self._icon_names.items():
            action.setIcon(icons.icon(name))
        for button, name in ((self.btn_add_bar, "new_bar"), (self.btn_edit_bar, "edit_bar"),
                             (self.btn_delete_bar, "delete_bar")):
            button.setIcon(icons.icon(name))

    def _build_actions(self) -> None:
        self.act_new = self._action("Nuevo proyecto", self.new_project, icon="new_project",
                                    shortcut=QKeySequence.StandardKey.New, tip="Crea un proyecto vacío en una pestaña nueva")
        self.act_open = self._action("Abrir proyecto…", self.open_project, icon="open_project",
                                     shortcut=QKeySequence.StandardKey.Open,
                                     tip="Abre uno o varios archivos de proyecto, cada uno en su pestaña")
        self.act_sample = self._action("Abrir ejemplo", self.open_sample, icon="sample",
                                       tip="Carga un proyecto de ejemplo (cimentación y 2 niveles)")
        self.act_catalog = self._action("Abrir ejemplo: catálogo de formas", self.open_catalog, icon="catalog",
                                        tip="Carga un proyecto con una barra de cada plantilla de forma")
        self.act_bridge = self._action("Abrir ejemplo: puente (sin niveles)", self.open_bridge, icon="bridge",
                                       tip="Carga un proyecto organizado por estructura y subestructura, sin niveles")
        self.act_save = self._action("Guardar proyecto", self.save_project_file, icon="save_project",
                                     shortcut=QKeySequence.StandardKey.Save, tip="Guarda el proyecto activo en su archivo")
        self.act_save_as = self._action("Guardar proyecto como…", self.save_project_as, icon="save_as",
                                        shortcut=QKeySequence.StandardKey.SaveAs)
        self.act_props = self._action("Modificar proyecto…", self.edit_project_properties, icon="edit_project",
                                      tip="Modifica el proyecto activo: nombre, datos de la obra, barra comercial, logo…")
        self.act_quit = self._action("Salir", self.close, shortcut=QKeySequence.StandardKey.Quit)
        self.act_save_all = self._action("Guardar todos los proyectos", self.save_all, icon="save_all",
                                         shortcut="Ctrl+Alt+S", tip="Guarda todos los proyectos abiertos que tengan cambios")
        self.act_duplicate = self._action("Duplicar proyecto", self.duplicate_project, icon="duplicate_project",
                                          tip="Crea una copia del proyecto activo en una pestaña nueva")
        self.act_close_project = self._action("Cerrar proyecto", self.close_project, icon="close_project",
                                              shortcut="Ctrl+W",
                                              tip="Cierra el proyecto activo (pregunta si tiene cambios sin guardar)")
        self.act_next_project = self._action("Proyecto siguiente", lambda: self._step_project(1), icon="next_project",
                                             shortcut="Ctrl+PgDown")
        self.act_prev_project = self._action("Proyecto anterior", lambda: self._step_project(-1),
                                             icon="previous_project", shortcut="Ctrl+PgUp")

        self.act_add_element = self._action("Nuevo elemento", self.add_element, icon="new_element", shortcut="Ctrl+Shift+N")
        self.act_edit_element = self._action("Editar elemento", self.edit_element, icon="edit_element")
        self.act_delete_element = self._action("Eliminar elemento", self.delete_element, icon="delete_element")
        self.act_add_bar = self._action("Nueva barra", self.add_bar, icon="new_bar", shortcut="Ctrl+B")
        self.act_edit_bar = self._action("Editar barra", self.edit_bar, icon="edit_bar")
        self.act_delete_bar = self._action("Eliminar barra", self.delete_bar, icon="delete_bar")
        self.act_excel = self._action("Exportar a Excel…", self.export_excel, icon="export_excel", shortcut="Ctrl+E",
                                      tip="Planilla en Excel con el esquema de cada barra")
        self.act_pdf = self._action("Exportar a PDF…", self.export_pdf, icon="export_pdf", shortcut="Ctrl+P",
                                    tip="Planilla en PDF con el esquema de cada barra")
        self.act_about = self._action("Acerca de RebarFlow", self.about)
        # Mostrar u ocultar el panel de detalle (la X del panel lo cierra; esta acción lo vuelve a abrir).
        self.act_detail = self.detail_dock.toggleViewAction()
        self.act_detail.setText("Detalle de barra")
        self.act_detail.setShortcut("F4")
        self._icon_names[self.act_detail] = "detail"
        self.act_detail.setIcon(icons.icon("detail"))
        self.act_detail.setStatusTip("Muestra u oculta el panel con el dibujo grande y el cálculo de la barra seleccionada")
        self.act_theme = self._action("Modo nocturno", self.toggle_theme, shortcut="Ctrl+Shift+D",
                                      tip="Cambia entre la interfaz clara y la nocturna")

        toolbar = QToolBar("Principal")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        toolbar.setIconSize(QSize(32, 32))
        for group in ((self.act_new, self.act_open, self.act_save, self.act_props, self.act_duplicate),
                      (self.act_add_element, self.act_add_bar, self.act_edit_bar, self.act_delete_bar),
                      (self.act_excel, self.act_pdf)):
            for action in group:
                toolbar.addAction(action)
            toolbar.addSeparator()
        toolbar.addAction(self.act_detail)
        self.addToolBar(toolbar)
        self.addToolBarBreak()

        # Cinta de proyectos: una pestaña por proyecto abierto y sus acciones a un clic.
        self.project_bar = ProjectBar()
        self.project_bar.selected.connect(self.select_project)
        self.project_bar.close_requested.connect(self.close_project)
        self.project_bar.edit_requested.connect(self.edit_project_properties)
        self.project_bar.moved.connect(self._on_project_moved)
        self.project_bar.menu_requested.connect(self._project_menu)
        ribbon = QToolBar("Proyectos")
        ribbon.setObjectName("projectRibbon")
        ribbon.setMovable(False)
        ribbon.setFloatable(False)
        ribbon.addWidget(self.project_bar)
        self.addToolBar(ribbon)
        self.ribbon = ribbon

        menu = self.menuBar()
        file_menu = menu.addMenu("&Archivo")
        for action in (self.act_new, self.act_open, self.act_sample, self.act_bridge, self.act_catalog, None, self.act_save,
                       self.act_save_as, self.act_save_all, None, self.act_props, None, self.act_excel, self.act_pdf, None,
                       self.act_quit):
            file_menu.addSeparator() if action is None else file_menu.addAction(action)
        project_menu = menu.addMenu("&Proyecto")
        for action in (self.act_new, self.act_props, self.act_duplicate, None, self.act_next_project,
                       self.act_prev_project, None, self.act_close_project):
            project_menu.addSeparator() if action is None else project_menu.addAction(action)
        element_menu = menu.addMenu("&Elemento")
        for action in (self.act_add_element, self.act_edit_element, self.act_delete_element):
            element_menu.addAction(action)
        bar_menu = menu.addMenu("&Barra")
        for action in (self.act_add_bar, self.act_edit_bar, self.act_delete_bar):
            bar_menu.addAction(action)
        view_menu = menu.addMenu("&Ver")
        view_menu.addAction(self.act_detail)
        view_menu.addAction(self.act_theme)
        menu.addMenu("A&yuda").addAction(self.act_about)

        # Botón del tema en la esquina superior derecha, a la altura de la barra de menús.
        self.theme_button = QToolButton()
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setDefaultAction(self.act_theme)
        self.theme_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        menu.setCornerWidget(self.theme_button, Qt.Corner.TopRightCorner)
        self._update_theme_action()
        self._apply_icons()

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

    # ------------------------------------------------------------------ tema
    def _update_theme_action(self) -> None:
        """El botón ofrece el tema contrario al actual: luna en el claro, sol en el nocturno."""
        dark = style.current().dark
        self.act_theme.setText("Modo diurno" if dark else "Modo nocturno")
        self.act_theme.setIcon(theme_icon(to_dark=not dark))

    def set_dark_mode(self, dark: bool, *, remember: bool = True) -> None:
        """Aplica el tema claro o nocturno, lo recuerda para la próxima vez y redibuja tablas, esquemas y detalle."""
        style.apply_theme(QApplication.instance(), dark)
        if remember:
            style.remember_dark(dark)
        self._update_theme_action()
        self._apply_icons()
        line = self.current_line()
        self.refresh(select_mark=line.mark if line else None)

    def toggle_theme(self) -> None:
        self.set_dark_mode(not style.current().dark)

    def current_line(self) -> ScheduleLine | None:
        rows = self.bars_table.selectionModel().selectedRows()
        return self.bars_table.line_for_row(rows[0].row()) if rows else None

    def refresh(self, select: StructuralElement | None = None, select_mark: str | None = None) -> None:
        """Recalcula la planilla y reconstruye el árbol y las tablas conservando la selección."""
        target = select or self._element
        try:
            self.result = BBSCalculator(self.project.stock_length_mm, self.project.length_rounding_mm,
                          self.project.reusable_remnant_mm, self.project.group_label).calculate(
                self.project.elements)
            self.error = None
        except ValueError as exc:  # p. ej. una barra mayor que la comercial
            self.result, self.error = None, str(exc)

        self._rebuild_tree(target)
        self._fill_tables(select_mark)
        self._update_chrome()

    def _rebuild_tree(self, target: StructuralElement | None) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        root = QTreeWidgetItem([self.project.name])
        root.setIcon(0, icons.icon("project"))
        self.tree.addTopLevelItem(root)
        nodes: dict[tuple[str, ...], QTreeWidgetItem] = {(): root}
        selected_item: QTreeWidgetItem | None = None
        first_item: QTreeWidgetItem | None = None
        for index, element in enumerate(self.project.elements):
            path = element.path  # estructura / nivel y subestructura, los que tenga
            for depth in range(1, len(path) + 1):
                if path[:depth] not in nodes:
                    node = QTreeWidgetItem(nodes[path[:depth - 1]], [path[depth - 1]])
                    node.setIcon(0, icons.icon("group"))
                    nodes[path[:depth]] = node
            item = QTreeWidgetItem(nodes[path], [f"{element.name}  ·  {element.element_type.value}  ×{element.quantity}"])
            item.setIcon(0, icons.icon("element"))
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            first_item = first_item or item
            if element is target:
                selected_item = item
        self.tree.expandAll()
        if selected_item is None:
            selected_item = first_item
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
        self.project_table.populate(schedules)
        schedule = self._element_schedule()
        self.bars_table.populate([schedule] if schedule else [])
        self.summary.populate(self.result)
        self.plan_table.populate(self.result)
        if select_mark is not None and (row := self.bars_table.row_of(select_mark)) is not None:
            self.bars_table.selectRow(row)
        self._on_bar_selection()

    def _update_chrome(self) -> None:
        element = self._element
        if element is not None:
            first, *rest = (escape(part) for part in element.heading.split("  ·  "))
            self.element_title.setText(f"<b>{first}</b>" + "".join(f" &nbsp;·&nbsp; {part}" for part in rest))
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
        self.project_bar.set_projects([(self._tab_title(i), self._tab_tip(i)) for i in range(len(self.sessions))],
                                      self._index)
        self.act_save_all.setEnabled(any(session.modified for session in self.sessions))
        self.act_next_project.setEnabled(len(self.sessions) > 1)
        self.act_prev_project.setEnabled(len(self.sessions) > 1)
        marker = "*" if self.modified else ""
        self.setWindowTitle(f"{marker}{self.project.name} — RebarFlow")

    def _tab_title(self, index: int) -> str:
        """Título de la pestaña: el nombre del proyecto, con «•» si tiene cambios y «(2)» si otro se llama igual."""
        session = self.sessions[index]
        name = session.project.name
        repeated = sum(1 for other in self.sessions[:index] if other.project.name == name)
        if repeated:
            name += f" ({repeated + 1})"
        return f"•  {name}" if session.modified else name

    def _tab_tip(self, index: int) -> str:
        session = self.sessions[index]
        place = str(session.path) if session.path else "Sin guardar"
        changes = " · con cambios sin guardar" if session.modified else ""
        return f"{session.project.name}\n{place}{changes}\nClic: seleccionar · doble clic: modificar"

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
    def _check_unique(self, name: str, level: str, substructure: str = "", ignore: StructuralElement | None = None) -> None:
        for other in self.project.elements:
            if other is not ignore and (other.name, other.level, other.substructure) == (name, level, substructure):
                where = " / ".join(part for part in (level, substructure) if part)
                raise ValueError(f"Ya existe el elemento {name!r}" + (f" en {where!r}." if where else "."))

    def add_element_values(self, name: str, element_type: ElementType, level: str = "", quantity: int = 1,
                           substructure: str = "") -> StructuralElement:
        self._check_unique(name, level.strip(), substructure.strip())
        element = StructuralElement(name, element_type, level, quantity, substructure=substructure)
        self.project.elements.append(element)
        self._mark_modified()
        self.refresh(select=element)
        return element

    def update_element_values(self, element: StructuralElement, name: str, element_type: ElementType, level: str,
                              quantity: int, substructure: str = "") -> None:
        self._check_unique(name, level.strip(), substructure.strip(), ignore=element)
        element.name, element.element_type, element.quantity = name, element_type, quantity
        element.level, element.substructure = level.strip(), substructure.strip()
        self._mark_modified()
        self.refresh(select=element)

    def delete_element_object(self, element: StructuralElement) -> None:
        index = next(i for i, e in enumerate(self.project.elements) if e is element)
        del self.project.elements[index]
        self._element = None
        self._mark_modified()
        self.refresh()

    def add_element(self) -> None:
        dialog = ElementDialog(self, levels=self.project.levels, substructures=self.project.substructures,
                               group_label=self.project.group_label)
        if dialog.exec():
            try:
                self.add_element_values(*dialog.values())
            except ValueError as exc:
                QMessageBox.warning(self, "Elemento duplicado", str(exc))

    def edit_element(self) -> None:
        element = self._element
        if element is None:
            return
        dialog = ElementDialog(self, element, self.project.levels, self.project.substructures, self.project.group_label)
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
                     f"¿Eliminar el elemento {element.name}{f' ({element.location})' if element.location else ''} y sus "
                     f"{len(element.groups)} marcas de barras?"):
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
    def edit_project_properties(self, index: int | None = None) -> None:
        """Abre las propiedades del proyecto de la pestaña ``index`` (el activo por omisión)."""
        if isinstance(index, int) and not isinstance(index, bool) and index != self._index:
            self.select_project(index)
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

    def _confirm_discard(self, session: ProjectSession | None = None) -> bool:
        """Si ``session`` (el proyecto activo por omisión) tiene cambios, pregunta si se guardan o se descartan.

        Devuelve ``False`` si el usuario cancela o no se pudo guardar. El proyecto por el que se pregunta pasa a ser el
        activo, para que se vea de cuál se trata.
        """
        session = session or self.session
        if not session.modified:
            return True
        self.select_project(self.sessions.index(session))
        box = QMessageBox(QMessageBox.Icon.Question, "Cambios sin guardar",
                          f"El proyecto «{session.project.name}» tiene cambios sin guardar. ¿Guardarlos?", parent=self)
        save = box.addButton("Guardar", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return self.save_project_file()
        return box.clickedButton() is discard

    # ------------------------------------------------------------------ varios proyectos
    def _show_session(self) -> None:
        """Muestra el proyecto activo: recupera su pestaña central y su elemento seleccionado."""
        session = self.session
        self.tabs.setCurrentIndex(session.tab)
        self.refresh(select=session.element)

    def select_project(self, index: int) -> None:
        """Cambia al proyecto de la pestaña ``index`` (un clic en la cinta)."""
        if not 0 <= index < len(self.sessions) or index == self._index:
            self._update_chrome()
            return
        self.session.tab = self.tabs.currentIndex()
        self._index = index
        self._show_session()

    def _step_project(self, step: int) -> None:
        if len(self.sessions) > 1:
            self.select_project((self._index + step) % len(self.sessions))

    def _unique_name(self, base: str) -> str:
        names = {session.project.name for session in self.sessions}
        name, n = base, 1
        while name in names:
            n += 1
            name = f"{base} {n}"
        return name

    def add_project(self, project: Project, path: Path | None = None, *, modified: bool = False,
                    reuse_blank: bool = True) -> ProjectSession:
        """Abre ``project`` en una pestaña nueva y la activa.

        Con ``reuse_blank`` (lo normal al abrir un archivo o un ejemplo) el proyecto activo reemplaza al proyecto vacío
        sin tocar en vez de dejar una pestaña vacía.
        """
        session = ProjectSession(project, path, modified)
        if reuse_blank and self.session.blank:
            self.sessions[self._index] = session
        else:
            self.session.tab = self.tabs.currentIndex()
            self.sessions.append(session)
            self._index = len(self.sessions) - 1
        self._show_session()
        return session

    def set_project(self, project: Project, path: Path | None = None) -> None:
        """Reemplaza el contenido del proyecto activo (sin abrir otra pestaña)."""
        session = self.session
        session.project, session.path, session.modified, session.element = project, path, False, None
        self.refresh()

    def new_project(self) -> None:
        self.add_project(Project(name=self._unique_name(DEFAULT_PROJECT_NAME)), reuse_blank=False)

    def duplicate_project(self, index: int | None = None) -> None:
        """Copia el proyecto de la pestaña ``index`` (el activo por omisión) en una pestaña nueva, sin archivo."""
        source = self.sessions[self._index if not isinstance(index, int) or isinstance(index, bool) else index].project
        copy = project_from_dict(project_to_dict(source))
        copy.name = self._unique_name(f"{source.name} (copia)")
        self.add_project(copy, modified=True, reuse_blank=False)

    def close_project(self, index: int | None = None) -> bool:
        """Cierra el proyecto de la pestaña ``index`` (el activo por omisión); falso si el usuario cancela.

        Al cerrar el último queda un proyecto vacío: la ventana siempre tiene un proyecto.
        """
        index = self._index if not isinstance(index, int) or isinstance(index, bool) else index
        session = self.sessions[index]
        if not self._confirm_discard(session):
            return False
        position = self.sessions.index(session)
        active = self.session
        del self.sessions[position]
        if not self.sessions:
            self.sessions.append(ProjectSession(Project()))
        if session is active:
            self._index = min(position, len(self.sessions) - 1)
        else:
            self._index = self.sessions.index(active)
        self._show_session()
        return True

    def close_other_projects(self, index: int) -> None:
        keep = self.sessions[index]
        for session in list(self.sessions):
            if session is not keep and not self.close_project(self.sessions.index(session)):
                return
        self.select_project(self.sessions.index(keep))

    def _on_project_moved(self, source: int, target: int) -> None:
        """Las pestañas se reordenan arrastrándolas: la lista de proyectos sigue el mismo orden."""
        active = self.session
        self.sessions.insert(target, self.sessions.pop(source))
        self._index = self.sessions.index(active)

    def _project_menu(self, index: int, pos) -> None:
        self._build_project_menu(index).exec(pos)

    def _build_project_menu(self, index: int) -> QMenu:
        """Menú contextual de la pestaña ``index``."""
        menu = QMenu(self)
        menu.addAction(icons.icon("edit_project"), "Modificar proyecto…", lambda: self.edit_project_properties(index))
        menu.addAction(icons.icon("duplicate_project"), "Duplicar proyecto", lambda: self.duplicate_project(index))
        menu.addAction(icons.icon("save_project"), "Guardar proyecto",
                       lambda: (self.select_project(index), self.save_project_file()))
        menu.addSeparator()
        menu.addAction(icons.icon("close_project"), "Cerrar proyecto", lambda: self.close_project(index))
        others = menu.addAction("Cerrar los demás", lambda: self.close_other_projects(index))
        others.setEnabled(len(self.sessions) > 1)
        return menu

    def save_all(self) -> bool:
        """Guarda todos los proyectos con cambios; falso si alguno no se guardó."""
        for session in list(self.sessions):
            if session.modified:
                self.select_project(self.sessions.index(session))
                if not self.save_project_file():
                    return False
        return True

    def open_sample(self) -> None:
        self.add_project(build_project())

    def open_catalog(self) -> None:
        self.add_project(build_catalog_project())

    def open_bridge(self) -> None:
        self.add_project(build_bridge_project())

    def open_path(self, path: Path) -> bool:
        """Abre un archivo de proyecto en una pestaña nueva; si ya está abierto, solo lo selecciona."""
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        for index, session in enumerate(self.sessions):
            if session.path is not None and session.path.resolve() == resolved:
                self.select_project(index)
                return True
        try:
            project = load_project(path)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "No se pudo abrir el proyecto", f"{path.name}: {exc}")
            return False
        self.add_project(project, path)
        return True

    def open_project(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Abrir proyectos", "", f"{_PROJECT_FILTER};;Todos los archivos (*)")
        for name in names:
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
        return ExcelExporter(self.project.name, self.project.author, info=self.project.header_fields(),
                             logo_png=self.project.logo_png).export(self.result, path)

    def write_pdf(self, path: Path) -> Path:
        if self.result is None:
            raise ValueError(self.error or "No hay planilla que exportar.")
        return PdfExporter(self.project.name, self.project.author, page_size=self.project.paper,
                           info=self.project.header_fields(), logo_png=self.project.logo_png).export(self.result, path)

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
        # Pregunta por cada proyecto con cambios (se va mostrando el que corresponde); cancelar en uno cancela el cierre.
        if all(self._confirm_discard(session) for session in list(self.sessions) if session.modified):
            event.accept()
        else:
            event.ignore()
