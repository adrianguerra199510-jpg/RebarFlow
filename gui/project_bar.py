"""Cinta de proyectos: una pestaña por proyecto abierto, con las acciones de proyecto a un clic.

Un clic en una pestaña cambia de proyecto; el doble clic abre sus propiedades; la «×» de la pestaña lo cierra y el clic
derecho ofrece el resto (modificar, duplicar, guardar, cerrar los demás). Nuevo, Abrir, Guardar, Modificar y Duplicar están
en la barra de herramientas, junto a los demás botones.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QTabBar, QToolButton, QWidget


class ProjectTabBar(QTabBar):
    """Barra de pestañas que además avisa del doble clic y del clic derecho sobre una pestaña."""

    doubleClicked = Signal(int)
    contextRequested = Signal(int, QPoint)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (API de Qt)
        index = self.tabAt(event.position().toPoint())
        if index >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit(index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        index = self.tabAt(event.pos())
        if index >= 0:
            self.contextRequested.emit(index, event.globalPos())
            event.accept()
        else:
            super().contextMenuEvent(event)


class ProjectBar(QWidget):
    """Pestañas de los proyectos abiertos."""

    selected = Signal(int)
    close_requested = Signal(int)
    edit_requested = Signal(int)
    moved = Signal(int, int)
    menu_requested = Signal(int, QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[tuple[str, str]] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.label = QLabel("Proyectos")
        self.label.setObjectName("ribbonLabel")
        self.tabs = ProjectTabBar()
        self.tabs.setObjectName("projectTabs")
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.currentChanged.connect(self.selected)
        self.tabs.tabMoved.connect(self._tab_moved)
        self.tabs.doubleClicked.connect(self.edit_requested)
        self.tabs.contextRequested.connect(self.menu_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.label)
        layout.addWidget(self.tabs, stretch=1)

    # ------------------------------------------------------------------ contenido
    def set_projects(self, entries: Sequence[tuple[str, str]], current: int) -> None:
        """Muestra una pestaña por ``(título, ayuda)`` y marca la ``current``; solo reconstruye si cambió algo."""
        entries = list(entries)
        self.tabs.blockSignals(True)
        try:
            if entries != self._entries:
                self._entries = entries
                while self.tabs.count():
                    self.tabs.removeTab(0)
                for title, tip in entries:
                    index = self.tabs.addTab(title)
                    self.tabs.setTabToolTip(index, tip)
                    self.tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, self._close_button())
            self.tabs.setCurrentIndex(current)
            self._mark_current_button()
        finally:
            self.tabs.blockSignals(False)

    def _tab_moved(self, source: int, target: int) -> None:
        self._entries.insert(target, self._entries.pop(source))
        self.moved.emit(source, target)

    def titles(self) -> list[str]:
        return [self.tabs.tabText(i) for i in range(self.tabs.count())]

    def current_index(self) -> int:
        return self.tabs.currentIndex()

    def _close_button(self) -> QToolButton:
        button = QToolButton()
        button.setObjectName("tabClose")
        button.setText("×")
        button.setToolTip("Cerrar el proyecto")
        button.setFixedSize(18, 18)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda *_, b=button: self._close_clicked(b))
        return button

    def _close_clicked(self, button: QToolButton) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.tabButton(index, QTabBar.ButtonPosition.RightSide) is button:
                self.close_requested.emit(index)
                return

    def _mark_current_button(self) -> None:
        """La «×» de la pestaña activa se dibuja con el color del texto de esa pestaña (se estiliza por propiedad)."""
        for index in range(self.tabs.count()):
            button = self.tabs.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if button is not None:
                button.setProperty("current", index == self.tabs.currentIndex())
                button.style().unpolish(button)
                button.style().polish(button)
