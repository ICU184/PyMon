"""Character Comparison Widget – side-by-side comparison of all characters."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)


@dataclass
class CharSnapshot:
    """Snapshot of one character's data for comparison."""

    character_id: int
    character_name: str = ""
    corporation_name: str = ""
    alliance_name: str = ""
    total_sp: int = 0
    unallocated_sp: int = 0
    wallet_balance: float = 0.0
    security_status: float = 0.0
    intelligence: int = 0
    memory: int = 0
    perception: int = 0
    willpower: int = 0
    charisma: int = 0
    skill_count: int = 0
    skills_at_5: int = 0
    queue_length: int = 0
    queue_finish: str = ""
    current_training: str = ""
    birthday: str = ""


# ── Row definitions ──────────────────────────────────────────────
_ROWS: list[tuple[str, str]] = [
    ("corporation_name", "Corporation"),
    ("alliance_name", "Alliance"),
    ("birthday", "Birthday"),
    ("_sep_1", ""),
    ("total_sp", "Skillpoints"),
    ("unallocated_sp", "Unallocated SP"),
    ("skill_count", "Trained Skills"),
    ("skills_at_5", "Skills at Level V"),
    ("_sep_2", ""),
    ("wallet_balance", "ISK Balance"),
    ("security_status", "Security Status"),
    ("_sep_3", ""),
    ("intelligence", "Intelligence"),
    ("memory", "Memory"),
    ("perception", "Perception"),
    ("willpower", "Willpower"),
    ("charisma", "Charisma"),
    ("_sep_4", ""),
    ("current_training", "Current Training"),
    ("queue_length", "Queue Entries"),
    ("queue_finish", "Queue Finish"),
]


def _format_isk(v: float) -> str:
    return f"{v:,.2f} ISK"


def _format_sp(v: int) -> str:
    return f"{v:,}"


def _sec_color(sec: float) -> str:
    if sec >= 0.5:
        return Colors.ACCENT
    elif sec > 0.0:
        return Colors.ORANGE
    else:
        return Colors.RED


class CharacterComparisonWidget(QWidget):
    """Tabular comparison of all registered characters."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshots: list[CharSnapshot] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("📊 Character Comparison")
        title.setProperty("cssClass", "widget-title")
        layout.addWidget(title)

        self._hint = QLabel("Loading data for all characters …")
        self._hint.setProperty("cssClass", "hint")
        layout.addWidget(self._hint)

        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

    # ── public API ───────────────────────────────────────────────
    def set_data(self, snapshots: list[CharSnapshot]) -> None:
        """Replace comparison data and rebuild the table."""
        self._snapshots = snapshots
        self._rebuild()

    # ── internal ─────────────────────────────────────────────────
    def _rebuild(self) -> None:
        snaps = self._snapshots
        if not snaps:
            self._hint.setText("No characters available.")
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            return

        self._hint.setText(f"Comparing {len(snaps)} character(s)")

        row_defs = [r for r in _ROWS]  # copy
        n_rows = len(row_defs)
        n_cols = len(snaps) + 1  # label column + one per char

        self._table.setRowCount(n_rows)
        self._table.setColumnCount(n_cols)

        # Header
        headers = [""] + [s.character_name for s in snaps]
        self._table.setHorizontalHeaderLabels(headers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        for c in range(1, n_cols):
            self._table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.Stretch
            )

        # Find best values for highlighting
        best_sp = max((s.total_sp for s in snaps), default=0)
        best_isk = max((s.wallet_balance for s in snaps), default=0)
        best_skill_count = max((s.skill_count for s in snaps), default=0)
        best_l5 = max((s.skills_at_5 for s in snaps), default=0)

        for r, (key, label) in enumerate(row_defs):
            # Separator row
            if key.startswith("_sep"):
                for c in range(n_cols):
                    item = QTableWidgetItem("")
                    item.setBackground(QColor("#111"))
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    self._table.setItem(r, c, item)
                self._table.setRowHeight(r, 6)
                continue

            # Label column
            lbl_item = QTableWidgetItem(label)
            lbl_item.setForeground(QColor(Colors.ACCENT))
            lbl_font = QFont()
            lbl_font.setBold(True)
            lbl_item.setFont(lbl_font)
            self._table.setItem(r, 0, lbl_item)

            for c, snap in enumerate(snaps, start=1):
                val = getattr(snap, key, "")
                text = ""
                fg = Colors.TEXT
                bold = False

                if key == "total_sp":
                    text = _format_sp(val)
                    if val == best_sp and len(snaps) > 1:
                        fg = "#FFD700"
                        bold = True
                elif key == "unallocated_sp":
                    text = _format_sp(val)
                elif key == "wallet_balance":
                    text = _format_isk(val)
                    if val == best_isk and len(snaps) > 1:
                        fg = "#FFD700"
                        bold = True
                elif key == "security_status":
                    text = f"{val:.2f}"
                    fg = _sec_color(val)
                elif key == "skill_count":
                    text = str(val)
                    if val == best_skill_count and len(snaps) > 1:
                        fg = "#FFD700"
                        bold = True
                elif key == "skills_at_5":
                    text = str(val)
                    if val == best_l5 and len(snaps) > 1:
                        fg = "#FFD700"
                        bold = True
                elif key == "queue_length":
                    text = str(val)
                elif key in ("intelligence", "memory", "perception", "willpower", "charisma"):
                    text = str(val)
                    # Highlight if above base (17 is base+bonus typical minimum)
                    if val >= 25:
                        fg = Colors.ACCENT
                else:
                    text = str(val) if val else "—"

                item = QTableWidgetItem(text)
                item.setForeground(QColor(fg))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if bold:
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)
                self._table.setItem(r, c, item)
