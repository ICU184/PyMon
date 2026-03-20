"""DockableTabWidget – tabs that can be detached into standalone windows.

Features:
- Double-click a tab → detach into a floating window
- Drag tab out of the tab bar → detach
- Close floating window → re-dock the tab
- Tab reordering via drag & drop within the bar
- Tab group headers (separators between categories)
- Remembers which tabs are detached (for session persistence)
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  Detached Window
# ═══════════════════════════════════════════════════════════════════════

class DetachedWindow(QWidget):
    """Floating window that wraps a detached tab widget."""

    closed = Signal(str, QWidget)  # (tab_title, widget)
    geometry_changed = Signal(str)  # tab_title – for persistence

    def __init__(
        self,
        title: str,
        widget: QWidget,
        original_icon: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.tab_title = title
        self.tab_widget = widget
        self._original_icon = original_icon

        self.setWindowTitle(f"PyMon – {title}")
        self.setMinimumSize(600, 400)
        self.resize(900, 650)

        # ── Layout ──
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar
        title_bar = QWidget()
        title_bar.setProperty("cssClass", "detached-titlebar")
        title_bar.setFixedHeight(36)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(12, 0, 8, 0)

        tb_label = QLabel(f"📌 {title}")
        tb_label.setProperty("cssClass", "widget-title")
        tb_layout.addWidget(tb_label)

        tb_layout.addStretch()

        dock_btn = QPushButton("↩ Dock")
        dock_btn.setFixedHeight(26)
        dock_btn.setToolTip("Tab back to main window")
        dock_btn.clicked.connect(self.close)
        tb_layout.addWidget(dock_btn)

        layout.addWidget(title_bar)

        # Content
        widget.setParent(self)
        layout.addWidget(widget, 1)

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Re-dock the tab on close."""
        self.closed.emit(self.tab_title, self.tab_widget)
        event.accept()

    def moveEvent(self, event: Any) -> None:
        super().moveEvent(event)
        self.geometry_changed.emit(self.tab_title)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.geometry_changed.emit(self.tab_title)


# ═══════════════════════════════════════════════════════════════════════
#  Draggable Tab Bar
# ═══════════════════════════════════════════════════════════════════════

class DraggableTabBar(QTabBar):
    """Tab bar that supports drag-to-detach and reordering."""

    tab_detach_requested = Signal(int)  # tab index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMovable(True)
        self.setTabsClosable(False)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(True)
        self.setDocumentMode(True)

        self._drag_start: QPoint | None = None
        self._drag_index: int = -1

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Double-click → detach tab."""
        idx = self.tabAt(event.pos())
        if idx >= 0:
            self.tab_detach_requested.emit(idx)
        else:
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()
            self._drag_index = self.tabAt(event.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_start is not None
            and self._drag_index >= 0
            and (event.pos() - self._drag_start).manhattanLength() > 40
        ):
            # Check if dragged out of tab bar vertically
            if not self.rect().contains(event.pos()):
                idx = self._drag_index
                self._drag_start = None
                self._drag_index = -1
                self.tab_detach_requested.emit(idx)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start = None
        self._drag_index = -1
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: Any) -> None:
        """Right-click context menu for tabs."""
        idx = self.tabAt(event.pos())
        if idx < 0:
            return

        menu = QMenu(self)

        detach_action = QAction("🗗 Detach as window", self)
        detach_action.triggered.connect(lambda: self.tab_detach_requested.emit(idx))
        menu.addAction(detach_action)

        menu.exec(event.globalPos())


# ═══════════════════════════════════════════════════════════════════════
#  DockableTabWidget
# ═══════════════════════════════════════════════════════════════════════

class DockableTabWidget(QTabWidget):
    """QTabWidget with drag-to-detach, double-click detach, and re-docking.

    Signals:
        tab_detached(str)  – emitted when a tab is detached (tab title)
        tab_docked(str)    – emitted when a tab is re-docked (tab title)
        group_detached(str) – emitted when a whole group is detached
        group_docked(str)   – emitted when a whole group is re-docked
    """

    tab_detached = Signal(str)
    tab_docked = Signal(str)
    group_detached = Signal(str)
    group_docked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Replace the default tab bar
        self._tab_bar = DraggableTabBar(self)
        self.setTabBar(self._tab_bar)
        self._tab_bar.tab_detach_requested.connect(self._detach_tab)

        # Track detached windows: title → DetachedWindow
        self._detached: dict[str, DetachedWindow] = {}

        # Track original tab order for re-docking: title → insert index
        self._tab_order: list[str] = []

        # Tab groups for visual organisation
        self._tab_groups: dict[str, list[str]] = {}  # group_name → [tab_titles]

        # Detached group windows: group_key → DetachedGroupWindow
        self._detached_groups: dict[str, DetachedWindow] = {}

    # ── Public API ───────────────────────────────────────────────

    def addTab(self, widget: QWidget, title: str) -> int:  # type: ignore[override]
        """Add a tab and register it in the order tracker."""
        idx = super().addTab(widget, title)
        if title not in self._tab_order:
            self._tab_order.append(title)
        return idx

    def add_tab_to_group(self, widget: QWidget, title: str, group: str) -> int:
        """Add a tab and assign it to a named group."""
        idx = self.addTab(widget, title)
        if group not in self._tab_groups:
            self._tab_groups[group] = []
        if title not in self._tab_groups[group]:
            self._tab_groups[group].append(title)
        return idx

    def detach_tab_by_title(self, title: str) -> bool:
        """Programmatically detach a tab by its title."""
        for i in range(self.count()):
            if self.tabText(i) == title:
                self._detach_tab(i)
                return True
        return False

    def dock_all(self) -> None:
        """Re-dock all detached windows."""
        # Copy keys since dict changes during iteration
        for title in list(self._detached.keys()):
            win = self._detached[title]
            win.close()  # triggers _redock_tab via closeEvent

    def get_detached_titles(self) -> list[str]:
        """Return titles of all currently detached tabs."""
        return list(self._detached.keys())

    def get_detached_geometries(self) -> dict[str, dict[str, int]]:
        """Return geometries of all detached windows for persistence."""
        result: dict[str, dict[str, int]] = {}
        for title, win in self._detached.items():
            g = win.geometry()
            result[title] = {
                "x": g.x(), "y": g.y(),
                "w": g.width(), "h": g.height(),
            }
        return result

    def restore_detached(self, layouts: dict[str, dict[str, int]]) -> None:
        """Restore previously detached tabs from saved layout."""
        for title, geom in layouts.items():
            if self.detach_tab_by_title(title):
                win = self._detached.get(title)
                if win and geom:
                    win.setGeometry(QRect(
                        geom.get("x", 100), geom.get("y", 100),
                        geom.get("w", 900), geom.get("h", 650),
                    ))

    def is_detached(self, title: str) -> bool:
        return title in self._detached

    # ── Internal ─────────────────────────────────────────────────

    def _detach_tab(self, index: int) -> None:
        """Remove tab at *index* and open it in a floating window."""
        if index < 0 or index >= self.count():
            return

        title = self.tabText(index)
        widget = self.widget(index)
        icon = self.tabIcon(index)

        if title in self._detached:
            # Already detached – just raise the window
            self._detached[title].raise_()
            self._detached[title].activateWindow()
            return

        # Remove from tab widget (don't delete the widget!)
        self.removeTab(index)

        # Create floating window
        win = DetachedWindow(title, widget, icon, parent=None)
        win.closed.connect(self._redock_tab)
        self._detached[title] = win

        # Position near mouse or on same screen
        cursor_pos = QApplication.instance().activeWindow()
        if cursor_pos:
            screen = cursor_pos.screen()
            if screen:
                avail = screen.availableGeometry()
                win.move(avail.x() + 50, avail.y() + 50)

        win.show()
        win.raise_()
        logger.info("Tab '%s' detached", title)
        self.tab_detached.emit(title)

    def _redock_tab(self, title: str, widget: QWidget) -> None:
        """Re-insert a tab at its original position."""
        if title in self._detached:
            win = self._detached.pop(title)
            # Don't delete the window, just hide it
            win.hide()

        # Find the best insertion index based on original order
        insert_idx = self._find_insert_index(title)

        widget.setParent(self)
        self.insertTab(insert_idx, widget, title)
        self.setCurrentIndex(insert_idx)

        logger.info("Tab '%s' re-docked at index %d", title, insert_idx)
        self.tab_docked.emit(title)

    def _find_insert_index(self, title: str) -> int:
        """Find the correct insertion index to maintain original tab order."""
        if title not in self._tab_order:
            return self.count()

        target_pos = self._tab_order.index(title)

        # Find the first tab whose original position is after this one
        for i in range(self.count()):
            tab_title = self.tabText(i)
            if tab_title in self._tab_order:
                if self._tab_order.index(tab_title) > target_pos:
                    return i

        return self.count()

    # ── Tab selection by name ────────────────────────────────────

    def select_tab_by_title(self, title: str) -> bool:
        """Switch to the tab with the given title. Returns True on success."""
        for i in range(self.count()):
            if self.tabText(i) == title:
                self.setCurrentIndex(i)
                return True
        return False

    def current_tab_title(self) -> str:
        """Return the title of the currently selected tab."""
        idx = self.currentIndex()
        return self.tabText(idx) if idx >= 0 else ""

    # ── Group detach / dock ──────────────────────────────────────

    def detach_group(self, group_key: str) -> bool:
        """Detach all tabs of a group into a single floating window with sub-tabs."""
        if group_key in self._detached_groups:
            self._detached_groups[group_key].raise_()
            self._detached_groups[group_key].activateWindow()
            return True

        tab_names = self._tab_groups.get(group_key, [])
        if not tab_names:
            return False

        # Collect widgets that are still in this tab widget
        widgets: list[tuple[str, QWidget]] = []
        for name in tab_names:
            if name in self._detached:
                continue  # skip individually detached tabs
            for i in range(self.count()):
                if self.tabText(i) == name:
                    widgets.append((name, self.widget(i)))
                    break

        if not widgets:
            return False

        # Create a container with its own QTabWidget
        container = QTabWidget()
        container.setTabPosition(QTabWidget.TabPosition.North)
        container.setDocumentMode(True)

        # Remove tabs from main widget and add to container
        for name, widget in widgets:
            for i in range(self.count()):
                if self.tabText(i) == name:
                    self.removeTab(i)
                    break
            widget.setParent(container)
            container.addTab(widget, name)

        # Create floating window
        group_label = group_key.replace("_", " ").title()
        win = DetachedWindow(f"Group: {group_label}", container, parent=None)
        win.closed.connect(lambda title, w: self._redock_group(group_key, w))
        self._detached_groups[group_key] = win

        # Position near cursor
        app = QApplication.instance()
        if app:
            active = app.activeWindow()  # type: ignore
            if active:
                screen = active.screen()  # type: ignore
                if screen:
                    avail = screen.availableGeometry()  # type: ignore
                    win.move(avail.x() + 80, avail.y() + 80)  # type: ignore

        win.show()
        win.raise_()
        logger.info("Group '%s' detached (%d tabs)", group_key, len(widgets))
        self.group_detached.emit(group_key)
        return True

    def _redock_group(self, group_key: str, container: QWidget) -> None:
        """Re-dock all tabs from a detached group window."""
        if group_key not in self._detached_groups:
            return

        win = self._detached_groups.pop(group_key)
        win.hide()

        # The container is a QTabWidget – extract its tabs
        if isinstance(container, QTabWidget):
            while container.count() > 0:
                title = container.tabText(0)
                widget = container.widget(0)
                container.removeTab(0)

                insert_idx = self._find_insert_index(title)
                widget.setParent(self)
                self.insertTab(insert_idx, widget, title)

            # Show first re-docked tab
            tab_names = self._tab_groups.get(group_key, [])
            if tab_names:
                self.select_tab_by_title(tab_names[0])

        logger.info("Group '%s' re-docked", group_key)
        self.group_docked.emit(group_key)

    def dock_all_groups(self) -> None:
        """Re-dock all detached group windows."""
        for key in list(self._detached_groups.keys()):
            win = self._detached_groups[key]
            win.close()

    def is_group_detached(self, group_key: str) -> bool:
        return group_key in self._detached_groups

    def get_detached_group_keys(self) -> list[str]:
        return list(self._detached_groups.keys())

    def get_detached_group_geometries(self) -> dict[str, dict[str, int]]:
        """Return geometries of detached group windows for persistence."""
        result: dict[str, dict[str, int]] = {}
        for key, win in self._detached_groups.items():
            g = win.geometry()
            result[key] = {
                "x": g.x(), "y": g.y(),
                "w": g.width(), "h": g.height(),
            }
        return result
