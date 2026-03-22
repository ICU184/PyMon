"""Skills Pie/Bar Chart – SP distribution by skill group using pyqtgraph."""

from __future__ import annotations

import logging
from collections import defaultdict

import pyqtgraph as pg
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)

# EVE-inspired color palette (20 colors)
_PALETTE = [
    "#4ecca3", "#e74c3c", "#3498db", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#2ecc71", "#e84393", "#00cec9",
    "#6c5ce7", "#fdcb6e", "#fab1a0", "#74b9ff", "#a29bfe",
    "#55efc4", "#ff7675", "#ffeaa7", "#dfe6e9", "#636e72",
]


def _format_sp(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    elif v >= 1_000:
        return f"{v / 1_000:.0f}k"
    return str(v)


class SkillsPieChartWidget(QWidget):
    """Horizontal bar chart showing SP distribution by skill group."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("📊 SP Distribution by Skill Group")
        title.setProperty("cssClass", "widget-title")
        layout.addWidget(title)

        self._summary = QLabel("")
        self._summary.setProperty("cssClass", "hint")
        layout.addWidget(self._summary)

        # pyqtgraph bar chart
        pg.setConfigOptions(antialias=True, background=Colors.BG_BASE, foreground=Colors.TEXT)
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setMouseEnabled(x=False, y=False)
        self._plot_widget.hideButtons()
        self._plot_widget.getPlotItem().getViewBox().setDefaultPadding(0.02)
        layout.addWidget(self._plot_widget, stretch=1)

        # Legend (custom labels below)
        self._legend_layout = QHBoxLayout()
        self._legend_layout.setContentsMargins(8, 0, 8, 8)
        self._legend_widget = QWidget()
        self._legend_widget.setLayout(self._legend_layout)
        layout.addWidget(self._legend_widget)

    def set_skills_data(self, skills: list) -> None:
        """Set skills data (list of SkillInfo) and redraw chart.

        Args:
            skills: List of SkillInfo dataclass instances with group_name, skillpoints_in_skill
        """
        if not skills:
            self._summary.setText("No skill data available.")
            return

        # Aggregate SP by group
        groups: dict[str, int] = defaultdict(int)
        for s in skills:
            groups[s.group_name or "Unknown"] += s.skillpoints_in_skill

        # Sort descending by SP
        sorted_groups = sorted(groups.items(), key=lambda x: x[1], reverse=True)
        total_sp = sum(v for _, v in sorted_groups)

        self._summary.setText(
            f"{len(sorted_groups)} Groups  |  {len(skills)} Skills  |  "
            f"{total_sp:,} SP total"
        )

        self._draw_bars(sorted_groups, total_sp)

    def _draw_bars(self, sorted_groups: list[tuple[str, int]], total_sp: int) -> None:
        """Draw horizontal bar chart."""
        self._plot_widget.clear()

        n = len(sorted_groups)
        if n == 0:
            return

        # Reverse for bottom-to-top display (largest at top)
        groups_reversed = list(reversed(sorted_groups))

        y_vals = list(range(n))
        x_vals = [sp for _, sp in groups_reversed]
        colors = [_PALETTE[i % len(_PALETTE)] for i in range(n)]
        # Reverse colors so top group gets first color
        colors = list(reversed(colors))

        brushes = [pg.mkBrush(QColor(c)) for c in colors]

        bar = pg.BarGraphItem(
            x0=0,
            y=y_vals,
            width=x_vals,
            height=0.7,
            brushes=brushes,
            pens=[pg.mkPen(QColor("#333"), width=1)] * n,
        )
        self._plot_widget.addItem(bar)

        # Y-axis labels (group names)
        y_axis = self._plot_widget.getAxis("left")
        ticks = [(i, groups_reversed[i][0]) for i in range(n)]
        y_axis.setTicks([ticks])
        y_axis.setStyle(tickLength=0)
        y_axis.setWidth(160)

        # X-axis formatting
        x_axis = self._plot_widget.getAxis("bottom")
        x_axis.setLabel("Skillpoints")

        # Add SP text labels on bars
        for i, (_name, sp) in enumerate(groups_reversed):
            pct = (sp / total_sp * 100) if total_sp > 0 else 0
            label_text = f" {_format_sp(sp)}  ({pct:.1f}%)"
            text = pg.TextItem(label_text, color=Colors.TEXT, anchor=(0, 0.5))
            text.setPos(sp, i)
            font = QFont()
            font.setPointSize(9)
            text.setFont(font)
            self._plot_widget.addItem(text)

        self._plot_widget.setYRange(-0.5, n - 0.5, padding=0.02)

        # Clear old legend
        while self._legend_layout.count():
            item = self._legend_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Show top 5 in legend
        for i, (name, sp) in enumerate(sorted_groups[:5]):
            color = _PALETTE[i % len(_PALETTE)]
            lbl = QLabel(f'<span style="color:{color}">■</span> {name}: {_format_sp(sp)}')
            lbl.setProperty("cssClass", "legend")
            self._legend_layout.addWidget(lbl)
        self._legend_layout.addStretch()
