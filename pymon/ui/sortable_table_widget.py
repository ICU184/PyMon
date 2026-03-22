"""Sortable table widget with column configuration.

Provides a QTableWidget-based replacement for HTML tables with:
- Click-to-sort on any column
- Right-click column header for show/hide
- Column order persistence via settings DB
- Grouping by a chosen column
- Dark EVE-inspired styling
"""

from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)


class SortableTableWidget(QWidget):
    """A sortable, configurable table widget for PyMon tabs.

    Features:
    - Sortable columns (click header)
    - Column visibility toggle (right-click header)
    - Optional grouping by a column
    - Persistent column settings via settings DB
    - Dark theme compatible
    """

    row_double_clicked = Signal(int)  # row index

    def __init__(
        self,
        tab_key: str,
        columns: list[str],
        *,
        db: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise.

        Args:
            tab_key: Unique identifier for persisting column settings.
            columns: Column header labels.
            db: Database instance for persisting settings.
        """
        super().__init__(parent)
        self.tab_key = tab_key
        self._all_columns = list(columns)
        self._db = db
        self._visible_columns: list[int] = list(range(len(columns)))
        self._group_column: int = -1  # -1 = no grouping
        self._raw_data: list[list[Any]] = []

        self._setup_ui()
        self._load_settings()

    # ── UI ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Toolbar row
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Group by:"))
        self.group_combo = QComboBox()
        self.group_combo.setMaximumWidth(200)
        self.group_combo.addItem("— None —", -1)
        for i, col in enumerate(self._all_columns):
            self.group_combo.addItem(col, i)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        toolbar.addWidget(self.group_combo)
        toolbar.addStretch()

        self.info_label = QLabel("")
        self.info_label.setFont(QFont("Segoe UI", 9))
        toolbar.addWidget(self.info_label)
        layout.addLayout(toolbar)

        # Table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.table.horizontalHeader().customContextMenuRequested.connect(
            self._on_header_context_menu
        )
        self.table.doubleClicked.connect(
            lambda idx: self.row_double_clicked.emit(idx.row())
        )
        layout.addWidget(self.table)

    # ── Public API ──────────────────────────────────────────────

    def set_data(
        self,
        rows: list[list[Any]],
        *,
        header: str = "",
        numeric_columns: set[int] | None = None,
    ) -> None:
        """Populate the table with data.

        Args:
            rows: List of rows. Each row is a list of cell values.
            header: Optional info text shown above the table.
            numeric_columns: Column indices that should sort numerically.
        """
        self._raw_data = rows
        self._numeric_columns = numeric_columns or set()
        if header:
            self.info_label.setText(header)
        self._rebuild_table()

    def clear(self) -> None:
        """Clear the table."""
        self._raw_data = []
        self.table.setRowCount(0)
        self.info_label.setText("")

    # ── Rebuild ─────────────────────────────────────────────────

    def _rebuild_table(self) -> None:
        """Rebuild table from raw data with current column/group settings."""
        self.table.setSortingEnabled(False)

        # Set up columns (only visible ones)
        visible = [c for c in self._visible_columns if 0 <= c < len(self._all_columns)]
        self.table.setColumnCount(len(visible))
        self.table.setHorizontalHeaderLabels(
            [self._all_columns[c] for c in visible]
        )

        rows = self._raw_data
        if not rows:
            self.table.setRowCount(0)
            self.table.setSortingEnabled(True)
            return

        # Grouping
        if 0 <= self._group_column < len(self._all_columns):
            gc = self._group_column
            groups: dict[str, list[list[Any]]] = {}
            for row in rows:
                key = str(row[gc]) if gc < len(row) else ""
                groups.setdefault(key, []).append(row)

            # Build grouped display
            display_rows: list[list[Any]] = []
            for group_name in sorted(groups.keys()):
                # Group header row
                header_row = [""] * len(self._all_columns)
                header_row[0] = f"▸ {group_name} ({len(groups[group_name])})"
                display_rows.append(("__group__", header_row))
                for r in groups[group_name]:
                    display_rows.append(("__data__", r))
        else:
            display_rows = [("__data__", r) for r in rows]

        self.table.setRowCount(len(display_rows))

        for row_idx, (row_type, row_data) in enumerate(display_rows):
            for col_out, col_src in enumerate(visible):
                value = row_data[col_src] if col_src < len(row_data) else ""
                item = _SortableItem(str(value))

                if row_type == "__group__":
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setBackground(
                        __import__("PySide6.QtGui", fromlist=["QColor"]).QColor(Colors.BG_CARD)
                    )
                elif col_src in self._numeric_columns:
                    item.setData(Qt.ItemDataRole.UserRole, _parse_numeric(value))

                self.table.setItem(row_idx, col_out, item)

        # Auto-resize columns
        for c in range(len(visible)):
            self.table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents
            )
        if visible:
            self.table.horizontalHeader().setSectionResizeMode(
                len(visible) - 1, QHeaderView.ResizeMode.Stretch
            )

        self.table.setSortingEnabled(True)

    # ── Header context menu ────────────────────────────────────

    def _on_header_context_menu(self, pos) -> None:
        """Show column visibility menu on right-click."""
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {Colors.BG_CARD}; color: {Colors.TEXT_HEADING}; border: 1px solid {Colors.BORDER}; }}"
            f"QMenu::item:selected {{ background-color: {Colors.GREEN}; }}"
        )

        for i, col_name in enumerate(self._all_columns):
            action = QAction(col_name, self)
            action.setCheckable(True)
            action.setChecked(i in self._visible_columns)
            action.setData(i)
            action.triggered.connect(self._on_toggle_column)
            menu.addAction(action)

        menu.addSeparator()
        reset_action = QAction("Show all columns", self)
        reset_action.triggered.connect(self._reset_columns)
        menu.addAction(reset_action)

        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def _on_toggle_column(self) -> None:
        """Toggle column visibility."""
        action = self.sender()
        if not action:
            return
        col_idx = action.data()
        if col_idx in self._visible_columns:
            if len(self._visible_columns) > 1:
                self._visible_columns.remove(col_idx)
            else:
                return  # Don't allow hiding all columns
        else:
            self._visible_columns.append(col_idx)
            self._visible_columns.sort()

        self._rebuild_table()
        self._save_settings()

    def _reset_columns(self) -> None:
        """Show all columns."""
        self._visible_columns = list(range(len(self._all_columns)))
        self._rebuild_table()
        self._save_settings()

    def _on_group_changed(self, idx: int) -> None:
        """Change grouping column."""
        self._group_column = self.group_combo.currentData()
        self._rebuild_table()
        self._save_settings()

    # ── Persistence ────────────────────────────────────────────

    def _save_settings(self) -> None:
        """Save column visibility + group to DB."""
        if not self._db:
            return
        try:
            data = json.dumps({
                "visible": self._visible_columns,
                "group": self._group_column,
            })
            self._db.conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"table_columns_{self.tab_key}", data),
            )
            self._db.conn.commit()
        except Exception:
            logger.debug("Could not save table settings", exc_info=True)

    def _load_settings(self) -> None:
        """Load column visibility + group from DB."""
        if not self._db:
            return
        try:
            row = self._db.conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (f"table_columns_{self.tab_key}",),
            ).fetchone()
            if row:
                data = json.loads(row["value"])
                vis = data.get("visible")
                if isinstance(vis, list) and all(
                    isinstance(v, int) and 0 <= v < len(self._all_columns) for v in vis
                ):
                    self._visible_columns = vis
                grp = data.get("group", -1)
                if isinstance(grp, int) and -1 <= grp < len(self._all_columns):
                    self._group_column = grp
                    # Update combo
                    for i in range(self.group_combo.count()):
                        if self.group_combo.itemData(i) == grp:
                            self.group_combo.blockSignals(True)
                            self.group_combo.setCurrentIndex(i)
                            self.group_combo.blockSignals(False)
                            break
        except Exception:
            logger.debug("Could not load table settings", exc_info=True)


# ── Helper classes ──────────────────────────────────────────


class _SortableItem(QTableWidgetItem):
    """Table item that sorts numerically when UserRole data is set."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        my_val = self.data(Qt.ItemDataRole.UserRole)
        other_val = other.data(Qt.ItemDataRole.UserRole)
        if my_val is not None and other_val is not None:
            try:
                return float(my_val) < float(other_val)
            except (ValueError, TypeError):
                pass
        return super().__lt__(other)


def _parse_numeric(value: Any) -> float | None:
    """Try to extract a number from a string (strips ISK, commas, etc.)."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace(",", "").replace(".", "").replace(" ", "")
    s = s.replace("ISK", "").replace("%", "").replace("−", "-").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None
