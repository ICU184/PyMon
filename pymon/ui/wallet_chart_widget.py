"""Wallet ISK chart widget for PyMon.

Displays an interactive line chart of ISK balance over time
using pyqtgraph, integrated into the Wallet tab.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)


class WalletChartWidget(QWidget):
    """Interactive ISK balance chart with income/expense breakdown."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._journal_data: list[Any] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Header ──
        header = QHBoxLayout()
        self.balance_label = QLabel("💰 Wallet Chart")
        self.balance_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.balance_label.setProperty("cssClass", "widget-title")
        header.addWidget(self.balance_label)

        header.addStretch()

        header.addWidget(QLabel("Timeframe:"))
        self.range_combo = QComboBox()
        self.range_combo.addItems(["All", "7 Days", "14 Days", "30 Days"])
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        header.addWidget(self.range_combo)

        layout.addLayout(header)

        # ── Summary bar ──
        self.summary_label = QLabel()
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.summary_label.setProperty("cssClass", "summary-card")
        layout.addWidget(self.summary_label)

        # ── pyqtgraph PlotWidget ──
        pg.setConfigOptions(antialias=True, background=Colors.BG_DARKEST, foreground=Colors.TEXT_HEADING)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumHeight(250)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setLabel("left", "ISK", color=Colors.TEXT_DIM)
        self.plot_widget.setLabel("bottom", "Time", color=Colors.TEXT_DIM)
        self.plot_widget.getAxis("left").setStyle(tickFont=QFont("Segoe UI", 8))
        self.plot_widget.getAxis("bottom").setStyle(tickFont=QFont("Segoe UI", 8))

        # Custom time axis
        self._time_axis = _DateTimeAxis(orientation="bottom")
        self.plot_widget.setAxisItems({"bottom": self._time_axis})

        layout.addWidget(self.plot_widget, stretch=1)

        # ── Income vs Expense bar chart ──
        self.bar_widget = pg.PlotWidget()
        self.bar_widget.setMinimumHeight(120)
        self.bar_widget.setMaximumHeight(160)
        self.bar_widget.showGrid(x=False, y=True, alpha=0.15)
        self.bar_widget.setLabel("left", "ISK", color=Colors.TEXT_DIM)
        self.bar_widget.getAxis("left").setStyle(tickFont=QFont("Segoe UI", 8))
        self._bar_time_axis = _DateTimeAxis(orientation="bottom")
        self.bar_widget.setAxisItems({"bottom": self._bar_time_axis})

        layout.addWidget(self.bar_widget)

    # ══════════════════════════════════════════════════════════
    #  DATA UPDATE
    # ══════════════════════════════════════════════════════════

    def set_journal_data(self, journal: list[Any] | None) -> None:
        """Update journal data and redraw charts."""
        self._journal_data = journal or []
        self._redraw()

    def _on_range_changed(self, _idx: int) -> None:
        self._redraw()

    def _redraw(self) -> None:
        """Redraw all charts with current data and filters."""
        self.plot_widget.clear()
        self.bar_widget.clear()

        if not self._journal_data:
            self.balance_label.setText("💰 Wallet Chart — No Data")
            self.summary_label.setText("")
            return

        # Filter by time range
        journal = list(reversed(self._journal_data))  # oldest first
        range_text = self.range_combo.currentText()
        if range_text != "All" and journal:
            days = {"7 Days": 7, "14 Days": 14, "30 Days": 30}.get(range_text, 999)
            now = datetime.now(UTC)
            journal = [
                j for j in journal
                if (now - _parse_date(j.date)).days <= days
            ]

        if not journal:
            self.balance_label.setText("💰 Wallet Chart — No Data in Timeframe")
            self.summary_label.setText("")
            return

        # ── Balance line chart ──
        timestamps = [_parse_date(j.date).timestamp() for j in journal]
        balances = [j.balance for j in journal if j.balance is not None]

        # Ensure same length
        min_len = min(len(timestamps), len(balances))
        timestamps = timestamps[:min_len]
        balances = balances[:min_len]

        if timestamps and balances:
            # Gradient fill under the curve
            pen = pg.mkPen(color=Colors.ACCENT, width=2)
            brush = pg.mkBrush(78, 204, 163, 40)
            self.plot_widget.plot(
                timestamps, balances, pen=pen, fillLevel=min(balances) * 0.99,
                fillBrush=brush, name="ISK Balance"
            )

            # Current balance dot
            self.plot_widget.plot(
                [timestamps[-1]], [balances[-1]],
                pen=None, symbol="o", symbolSize=8,
                symbolBrush=QColor(Colors.ACCENT),
            )

        # ── Summary ──
        latest_balance = balances[-1] if balances else 0
        total_income = sum(j.amount for j in journal if j.amount and j.amount > 0)
        total_expense = sum(j.amount for j in journal if j.amount and j.amount < 0)
        net = total_income + total_expense
        net_color = Colors.ACCENT if net >= 0 else Colors.RED

        self.balance_label.setText(f"💰 {latest_balance:,.2f} ISK")
        self.summary_label.setText(
            f"<table width='100%'><tr>"
            f"<td>📈 Income: <span style='color:{Colors.ACCENT}'>+{total_income:,.2f} ISK</span></td>"
            f"<td>📉 Expenses: <span style='color:{Colors.RED}'>{total_expense:,.2f} ISK</span></td>"
            f"<td>📊 Balance: <span style='color:{net_color}'>{net:+,.2f} ISK</span></td>"
            f"<td>📝 Entries: {len(journal)}</td>"
            f"</tr></table>"
        )

        # ── Daily income/expense bar chart ──
        daily: dict[str, dict[str, float]] = {}
        for j in journal:
            day = _parse_date(j.date).strftime("%Y-%m-%d")
            if day not in daily:
                daily[day] = {"income": 0.0, "expense": 0.0, "ts": _parse_date(j.date).timestamp()}
            if j.amount and j.amount > 0:
                daily[day]["income"] += j.amount
            elif j.amount and j.amount < 0:
                daily[day]["expense"] += j.amount

        if daily:
            days_sorted = sorted(daily.keys())
            bar_ts = [daily[d]["ts"] for d in days_sorted]
            incomes = [daily[d]["income"] for d in days_sorted]
            expenses = [daily[d]["expense"] for d in days_sorted]

            bar_width = 43200  # half day in seconds

            if incomes:
                income_bars = pg.BarGraphItem(
                    x=bar_ts, height=incomes, width=bar_width,
                    brush=QColor(78, 204, 163, 150), pen=pg.mkPen(None),
                )
                self.bar_widget.addItem(income_bars)

            if expenses:
                expense_bars = pg.BarGraphItem(
                    x=bar_ts, height=expenses, width=bar_width,
                    brush=QColor(231, 76, 60, 150), pen=pg.mkPen(None),
                )
                self.bar_widget.addItem(expense_bars)


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _parse_date(date_str: str | datetime) -> datetime:
    """Parse an ISO date string or pass through a datetime."""
    if isinstance(date_str, datetime):
        if date_str.tzinfo is None:
            return date_str.replace(tzinfo=UTC)
        return date_str
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(UTC)


class _DateTimeAxis(pg.AxisItem):
    """Custom axis that formats timestamps as readable dates."""

    def tickStrings(self, values: list[float], scale: float, spacing: float) -> list[str]:
        return [
            datetime.utcfromtimestamp(v).strftime("%d.%m\n%H:%M")
            for v in values
        ]
