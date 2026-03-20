"""Schedule Editor widget – weekly training planner.

Visual weekly planner where users can mark time blocks as
'active training' or 'offline/away'. Used for more accurate
skill training time estimates based on actual play schedule.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HOURS = [f"{h:02d}:00" for h in range(24)]

# Colors
COLOR_ONLINE = QColor(Colors.GREEN)   # green — training/online
COLOR_OFFLINE = QColor("#6e1b1b")  # red — offline/away
COLOR_EMPTY = QColor(Colors.BG_DARK)    # dark — unset


class ScheduleEditorWidget(QWidget):
    """Weekly schedule editor for training planning."""

    schedule_changed = Signal()

    def __init__(
        self,
        db: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._character_id: int | None = None

        # Schedule: 7 days × 24 hours
        # Values: "online", "offline", or ""
        self._schedule: list[list[str]] = [[""] * 24 for _ in range(7)]
        self._painting = False
        self._paint_value = "online"

        self._setup_ui()

    def set_character_id(self, character_id: int) -> None:
        """Set character and load their schedule."""
        self._character_id = character_id
        self._load_schedule()
        self._refresh_display()

    # ── UI ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Title
        title = QLabel("<h3>📅 Weekly Planner – Training Times</h3>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        # Legend
        legend = QHBoxLayout()
        legend.addWidget(self._make_legend_item("🟢 Online/Training", COLOR_ONLINE))
        legend.addWidget(self._make_legend_item("🔴 Offline/Away", COLOR_OFFLINE))
        legend.addWidget(self._make_legend_item("⬛ Not Set", COLOR_EMPTY))
        legend.addStretch()
        layout.addLayout(legend)

        # Instructions
        info = QLabel(
            "<p style='color:{Colors.TEXT_DIM}'>Click on cells to mark Online/Offline times. "
            "Left click = Online (green), Right click = Offline (red). "
            "Click and drag across cells to mark multiple hours.</p>"
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        # Schedule table: rows = days, columns = hours
        self.table = QTableWidget(7, 24)
        self.table.setVerticalHeaderLabels(DAYS)
        self.table.setHorizontalHeaderLabels([f"{h}" for h in range(24)])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setMinimumSectionSize(20)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Connect mouse events for painting
        self.table.cellPressed.connect(self._on_cell_pressed)
        self.table.cellEntered.connect(self._on_cell_entered)
        self.table.setMouseTracking(True)

        layout.addWidget(self.table, stretch=1)

        # Summary
        self.summary_label = QLabel("")
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.summary_label)

        # Buttons
        btn_layout = QHBoxLayout()

        all_online_btn = QPushButton("All Online")
        all_online_btn.setToolTip("Mark all time slots as Online")
        all_online_btn.clicked.connect(self._set_all_online)
        btn_layout.addWidget(all_online_btn)

        weekday_btn = QPushButton("Weekdays 9-17h Offline")
        weekday_btn.setToolTip("Set standard work schedule")
        weekday_btn.clicked.connect(self._set_work_schedule)
        btn_layout.addWidget(weekday_btn)

        clear_btn = QPushButton("Reset")
        clear_btn.setToolTip("Clear entire schedule")
        clear_btn.clicked.connect(self._clear_schedule)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()

        save_btn = QPushButton("💾 Save")
        save_btn.clicked.connect(self._save_schedule)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

        # Initial display
        self._refresh_display()

    @staticmethod
    def _make_legend_item(text: str, color: QColor) -> QLabel:
        from pymon.ui.dark_theme import Colors
        label = QLabel(text)
        label.setStyleSheet(
            f"padding: 4px 8px; background-color: {color.name()}; "
            f"border-radius: 3px; color: {Colors.TEXT_HEADING};"
        )
        return label

    # ── Cell interactions ───────────────────────────────────────

    def _on_cell_pressed(self, row: int, col: int) -> None:
        """Handle cell click — toggle or start painting."""
        from PySide6.QtWidgets import QApplication
        modifiers = QApplication.mouseButtons()

        if modifiers & Qt.MouseButton.RightButton:
            self._paint_value = "offline"
        else:
            # Toggle: if already online, switch to offline, vice versa
            current = self._schedule[row][col]
            if current == "online":
                self._paint_value = "offline"
            else:
                self._paint_value = "online"

        self._painting = True
        self._set_cell(row, col, self._paint_value)

    def _on_cell_entered(self, row: int, col: int) -> None:
        """Paint while dragging."""
        from PySide6.QtWidgets import QApplication
        if QApplication.mouseButtons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton):
            self._set_cell(row, col, self._paint_value)

    def _set_cell(self, row: int, col: int, value: str) -> None:
        """Set a cell value and update display."""
        if 0 <= row < 7 and 0 <= col < 24:
            self._schedule[row][col] = value
            self._update_cell_display(row, col)
            self._update_summary()

    def _update_cell_display(self, row: int, col: int) -> None:
        """Update the visual appearance of a cell."""
        value = self._schedule[row][col]
        item = self.table.item(row, col)
        if not item:
            item = QTableWidgetItem()
            self.table.setItem(row, col, item)

        if value == "online":
            item.setBackground(QBrush(COLOR_ONLINE))
            item.setText("✓")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        elif value == "offline":
            item.setBackground(QBrush(COLOR_OFFLINE))
            item.setText("✗")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            item.setBackground(QBrush(COLOR_EMPTY))
            item.setText("")

    def _refresh_display(self) -> None:
        """Refresh entire table display from schedule data."""
        for row in range(7):
            for col in range(24):
                self._update_cell_display(row, col)
        self._update_summary()

    def _update_summary(self) -> None:
        """Update the summary label."""
        online_h = sum(1 for day in self._schedule for h in day if h == "online")
        offline_h = sum(1 for day in self._schedule for h in day if h == "offline")
        unset_h = 168 - online_h - offline_h
        pct_online = (online_h / 168 * 100) if online_h else 0

        self.summary_label.setText(
            f"<p>"
            f"<span style='color:{Colors.ACCENT}'>🟢 Online: {online_h}h/week ({pct_online:.0f}%)</span>"
            f" | <span style='color:{Colors.RED}'>🔴 Offline: {offline_h}h</span>"
            f" | <span style='color:{Colors.TEXT_DIM}'>Not Set: {unset_h}h</span>"
            f"</p>"
        )

    # ── Presets ─────────────────────────────────────────────────

    def _set_all_online(self) -> None:
        """Mark all hours as online."""
        self._schedule = [["online"] * 24 for _ in range(7)]
        self._refresh_display()

    def _set_work_schedule(self) -> None:
        """Set typical work schedule: weekdays 9-17 offline, rest online."""
        self._schedule = [["online"] * 24 for _ in range(7)]
        for day in range(5):  # Mon–Fri
            for hour in range(9, 17):
                self._schedule[day][hour] = "offline"
        self._refresh_display()

    def _clear_schedule(self) -> None:
        """Clear entire schedule."""
        self._schedule = [[""] * 24 for _ in range(7)]
        self._refresh_display()

    # ── Persistence ────────────────────────────────────────────

    def _save_schedule(self) -> None:
        """Save schedule to database."""
        if not self._db or not self._character_id:
            QMessageBox.information(
                self, "Save",
                "No character selected.",
            )
            return
        try:
            data = json.dumps(self._schedule)
            self._db.conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (f"schedule_{self._character_id}", data),
            )
            self._db.conn.commit()
            self.schedule_changed.emit()
            QMessageBox.information(self, "Saved", "Weekly schedule saved ✓")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed:\n{e}")

    def _load_schedule(self) -> None:
        """Load schedule from database."""
        if not self._db or not self._character_id:
            return
        try:
            row = self._db.conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (f"schedule_{self._character_id}",),
            ).fetchone()
            if row:
                data = json.loads(row["value"])
                if isinstance(data, list) and len(data) == 7:
                    self._schedule = data
                    return
        except Exception:
            logger.debug("Could not load schedule", exc_info=True)

        # Default: all online
        self._schedule = [["online"] * 24 for _ in range(7)]

    def get_online_hours_per_week(self) -> int:
        """Return total online hours per week."""
        return sum(1 for day in self._schedule for h in day if h == "online")

    def get_online_fraction(self) -> float:
        """Return fraction of the week that is online (0.0–1.0)."""
        online = self.get_online_hours_per_week()
        return online / 168.0 if online else 0.0
