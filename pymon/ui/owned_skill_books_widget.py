"""Owned Skill Books Widget – shows skill books in assets that aren't trained."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)

# SDE category_id for Skills = 16
_SKILL_CATEGORY_ID = 16


class OwnedSkillBooksWidget(QWidget):
    """Shows skill books the character owns but hasn't yet trained."""

    def __init__(self, sde, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sde = sde

        self._all_items: list[tuple[str, str, str, int, bool]] = []  # name, group, location, qty, injected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("📚 Owned Skill Books")
        title.setProperty("cssClass", "widget-title")
        layout.addWidget(title)

        self._summary = QLabel("Loading data... ")
        self._summary.setObjectName("summary")
        layout.addWidget(self._summary)

        # Search bar
        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Search Skill Book...")
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search)
        layout.addLayout(search_row)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Skill Book", "Group", "Location", "Quantity", "Status"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setSortingEnabled(True)
        layout.addWidget(self._tree, stretch=1)

    def set_data(
        self,
        assets: list,
        trained_skills: dict[int, int],
        location_names: dict[int, str],
    ) -> None:
        """Set owned skill books data.

        Args:
            assets: List of AssetItem dataclass instances (type_id, quantity, location_id, …)
            trained_skills: Mapping skill_id → trained level (from SkillInfo list)
            location_names: Mapping location_id → resolved name
        """
        self._all_items.clear()

        # Find all skill books in assets
        skill_book_assets: list[tuple[str, str, str, int, bool]] = []
        n_injected = 0
        n_not_injected = 0

        for asset in assets:
            type_id = asset.type_id
            # Check if this type is a skill (category 16)
            cat_id = self._get_category_id(type_id)
            if cat_id != _SKILL_CATEGORY_ID:
                continue

            name = self.sde.get_type_name(type_id) or f"Type #{type_id}"
            group_name = self._get_group_name(type_id)
            loc_id = asset.location_id
            loc_name = location_names.get(loc_id, asset.location_name or f"Location #{loc_id}")
            qty = asset.quantity
            injected = type_id in trained_skills

            if injected:
                n_injected += 1
            else:
                n_not_injected += 1

            skill_book_assets.append((name, group_name, loc_name, qty, injected))

        self._all_items = sorted(skill_book_assets, key=lambda x: (x[4], x[0]))

        total = len(self._all_items)
        self._summary.setText(
            f"📚 {total} Skill Books found  |  "
            f"<span style='color:{Colors.RED}'>⬤</span> {n_not_injected} not injected  |  "
            f"<span style='color:{Colors.ACCENT}'>⬤</span> {n_injected} already trained"
        )

        self._populate_tree(self._all_items)

    def _get_category_id(self, type_id: int) -> int:
        """Get the category_id for a type via SDE lookup."""
        try:
            cat = self.sde.get_category_for_type(type_id)
            if cat:
                return cat.get("category_id", 0)
        except Exception:
            pass
        return 0

    def _get_group_name(self, type_id: int) -> str:
        """Get the group name for a type."""
        try:
            t = self.sde.get_type(type_id)
            if t:
                group_id = t.get("group_id", 0)
                return self.sde.get_group_name(group_id) or "Unknown"
        except Exception:
            pass
        return "Unknown"

    def _populate_tree(self, items: list[tuple[str, str, str, int, bool]]) -> None:
        """Populate the tree widget with skill book items."""
        self._tree.clear()

        for name, group, location, qty, injected in items:
            item = QTreeWidgetItem()
            item.setText(0, name)
            item.setText(1, group)
            item.setText(2, location)
            item.setText(3, str(qty))

            if injected:
                item.setText(4, "✓ Trained")
                item.setForeground(4, QColor(Colors.ACCENT))
                item.setForeground(0, QColor("#888"))
            else:
                item.setText(4, "✗ Not injected")
                item.setForeground(4, QColor(Colors.RED))
                f = QFont()
                f.setBold(True)
                item.setFont(0, f)

            item.setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(4, Qt.AlignmentFlag.AlignCenter)
            self._tree.addTopLevelItem(item)

    def _apply_filter(self, text: str) -> None:
        """Filter skill books by search text."""
        if not text.strip():
            self._populate_tree(self._all_items)
            return

        query = text.lower()
        filtered = [
            item for item in self._all_items
            if query in item[0].lower() or query in item[1].lower()
        ]
        self._populate_tree(filtered)
