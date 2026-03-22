"""Sidebar Navigation – collapsible group-based tab navigation.

Replaces the flat 35-tab bar with a vertical sidebar that groups tabs
into logical categories.  Each group has an icon header that can be
expanded/collapsed.  Individual tab buttons within a group switch the
main content area.  Groups (or individual tabs) can be popped out as
standalone windows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  Data model
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TabGroup:
    """Definition of a logical tab group."""
    key: str               # internal id, e.g. "character"
    label: str             # display name, e.g. "Character"
    icon: str              # emoji/icon character
    tab_names: list[str] = field(default_factory=list)
    collapsed: bool = False


# ═══════════════════════════════════════════════════════════════════════
#  Group Header Button
# ═══════════════════════════════════════════════════════════════════════

class GroupHeaderButton(QPushButton):
    """Clickable group header with expand/collapse chevron."""

    popout_requested = Signal(str)   # group_key
    collapse_toggled = Signal(str, bool)  # group_key, collapsed

    def __init__(self, group: TabGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self._collapsed = group.collapsed
        self._update_text()

        self.setProperty("cssClass", "sidebar-group-header")
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        self.clicked.connect(self._on_click)

    def _update_text(self) -> None:
        chevron = "▶" if self._collapsed else "▼"
        self.setText(f" {chevron}  {self.group.icon}  {self.group.label}")

    def _on_click(self) -> None:
        self._collapsed = not self._collapsed
        self._update_text()
        self.collapse_toggled.emit(self.group.key, self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._update_text()

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def contextMenuEvent(self, event: Any) -> None:
        menu = QMenu(self)
        popout = QAction(f"\U0001f5d7 Gruppe \u201e{self.group.label}\u201c als Fenster losl\u00f6sen", self)
        popout.triggered.connect(lambda: self.popout_requested.emit(self.group.key))
        menu.addAction(popout)
        menu.exec(event.globalPos())


# ═══════════════════════════════════════════════════════════════════════
#  Tab Item Button
# ═══════════════════════════════════════════════════════════════════════

class TabItemButton(QPushButton):
    """A single tab entry inside a group – clicking selects that tab."""

    tab_clicked = Signal(str)        # tab_name
    tab_popout = Signal(str)         # tab_name

    def __init__(self, tab_name: str, parent: QWidget | None = None) -> None:
        super().__init__(f"   {tab_name}", parent)
        self.tab_name = tab_name
        self._active = False

        self.setProperty("cssClass", "sidebar-tab-item")
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)
        self.clicked.connect(lambda: self.tab_clicked.emit(self.tab_name))

    def set_active(self, active: bool) -> None:
        self._active = active
        self.setProperty("active", active)
        # Force style refresh
        self.style().unpolish(self)
        self.style().polish(self)

    def contextMenuEvent(self, event: Any) -> None:
        menu = QMenu(self)
        popout = QAction(f"\U0001f5d7 \u201e{self.tab_name}\u201c als Fenster losl\u00f6sen", self)
        popout.triggered.connect(lambda: self.tab_popout.emit(self.tab_name))
        menu.addAction(popout)
        menu.exec(event.globalPos())


# ═══════════════════════════════════════════════════════════════════════
#  Sidebar Navigation Widget
# ═══════════════════════════════════════════════════════════════════════

class SidebarNav(QWidget):
    """Vertical sidebar with collapsible group headers and tab buttons.

    Signals:
        tab_selected(str)            – user clicked a tab entry
        tab_popout_requested(str)    – user wants to detach a single tab
        group_popout_requested(str)  – user wants to detach an entire group
    """

    tab_selected = Signal(str)
    tab_popout_requested = Signal(str)
    group_popout_requested = Signal(str)

    def __init__(self, groups: list[TabGroup], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._groups = {g.key: g for g in groups}
        self._group_headers: dict[str, GroupHeaderButton] = {}
        self._group_containers: dict[str, QWidget] = {}
        self._tab_buttons: dict[str, TabItemButton] = {}
        self._active_tab: str | None = None

        self.setProperty("cssClass", "sidebar-nav")
        self.setMinimumWidth(170)
        self.setMaximumWidth(220)

        self._build_ui(groups)

    def _build_ui(self, groups: list[TabGroup]) -> None:
        # Scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)

        for group in groups:
            self._add_group(group)

        self._layout.addStretch()
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _add_group(self, group: TabGroup) -> None:
        # Group header
        header = GroupHeaderButton(group)
        header.collapse_toggled.connect(self._on_collapse_toggled)
        header.popout_requested.connect(lambda k: self.group_popout_requested.emit(k))
        self._group_headers[group.key] = header
        self._layout.addWidget(header)

        # Tab items container
        items_widget = QWidget()
        items_layout = QVBoxLayout(items_widget)
        items_layout.setContentsMargins(0, 0, 0, 4)
        items_layout.setSpacing(1)

        for tab_name in group.tab_names:
            btn = TabItemButton(tab_name)
            btn.tab_clicked.connect(self._on_tab_clicked)
            btn.tab_popout.connect(lambda n: self.tab_popout_requested.emit(n))
            items_layout.addWidget(btn)
            self._tab_buttons[tab_name] = btn

        self._group_containers[group.key] = items_widget
        self._layout.addWidget(items_widget)

        # Apply initial collapsed state
        if group.collapsed:
            items_widget.setVisible(False)

    # ── Public API ─────────────────────────────────────────────

    def set_active_tab(self, tab_name: str) -> None:
        """Highlight the given tab in the sidebar."""
        if self._active_tab and self._active_tab in self._tab_buttons:
            self._tab_buttons[self._active_tab].set_active(False)
        self._active_tab = tab_name
        if tab_name in self._tab_buttons:
            self._tab_buttons[tab_name].set_active(True)
            # Auto-expand group if collapsed
            for group in self._groups.values():
                if tab_name in group.tab_names:
                    if self._group_headers[group.key].is_collapsed:
                        self._group_headers[group.key].set_collapsed(False)
                        self._group_containers[group.key].setVisible(True)
                    break

    def get_collapsed_groups(self) -> list[str]:
        """Return keys of collapsed groups (for layout persistence)."""
        return [k for k, h in self._group_headers.items() if h.is_collapsed]

    def set_collapsed_groups(self, keys: list[str]) -> None:
        """Restore collapsed state from saved layout."""
        for key in keys:
            if key in self._group_headers:
                self._group_headers[key].set_collapsed(True)
                self._group_containers[key].setVisible(False)

    def remove_tab(self, tab_name: str) -> None:
        """Remove a tab button (e.g. when detached)."""
        if tab_name in self._tab_buttons:
            btn = self._tab_buttons.pop(tab_name)
            btn.setVisible(False)
            btn.deleteLater()

    def has_tab(self, tab_name: str) -> bool:
        """Check if a tab button exists in the sidebar."""
        return tab_name in self._tab_buttons

    def add_tab(self, tab_name: str, group_key: str) -> None:
        """Re-add a tab button (e.g. when re-docked)."""
        if tab_name in self._tab_buttons:
            return  # already present
        if group_key not in self._groups:
            return
        group = self._groups[group_key]
        btn = TabItemButton(tab_name)
        btn.tab_clicked.connect(self._on_tab_clicked)
        btn.tab_popout.connect(lambda n: self.tab_popout_requested.emit(n))
        self._tab_buttons[tab_name] = btn

        # Insert at correct position inside group container
        container = self._group_containers[group_key]
        items_layout = container.layout()
        if items_layout is None:
            return
        # Find insertion point based on group's tab_names ordering
        count = items_layout.count()
        insert_idx = count  # default: append
        for i, name in enumerate(group.tab_names):
            if name == tab_name:
                insert_idx = i
                break
        items_layout.addWidget(btn) if insert_idx >= count else items_layout.insertWidget(insert_idx, btn)  # type: ignore[union-attr]

    def find_group_for_tab(self, tab_name: str) -> str | None:
        """Return the group key that contains the given tab name."""
        for group in self._groups.values():
            if tab_name in group.tab_names:
                return group.key
        return None

    def get_group_tab_names(self, group_key: str) -> list[str]:
        """Return tab names for a group."""
        if group_key in self._groups:
            return list(self._groups[group_key].tab_names)
        return []

    # ── Slots ──────────────────────────────────────────────────

    def _on_tab_clicked(self, tab_name: str) -> None:
        self.set_active_tab(tab_name)
        self.tab_selected.emit(tab_name)

    def _on_collapse_toggled(self, group_key: str, collapsed: bool) -> None:
        if group_key in self._group_containers:
            self._group_containers[group_key].setVisible(not collapsed)
