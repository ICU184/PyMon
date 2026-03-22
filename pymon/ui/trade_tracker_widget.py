"""Trade Tracker Widget – track buy/sell transactions, profit & loss analysis."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.api.esi_client import ESIClient
from pymon.sde.database import SDEDatabase
from pymon.services.market_service import MarketService
from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)


def _fmt_isk(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.2f} Bil"
    if value >= 1_000_000:
        return f"{value / 1_000_000:,.2f} Mil"
    if value >= 1_000:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


class TradeTrackerWidget(QWidget):
    """Tracks buy/sell transactions and calculates profit/loss per item."""

    def __init__(
        self, esi: ESIClient, sde: SDEDatabase, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = MarketService(esi, sde)
        self._sde = sde
        self._setup_ui()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Not needed – widget runs synchronous analysis."""

    # ═══════════════════════════════════════════════════════════════
    #  UI
    # ═══════════════════════════════════════════════════════════════

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title = QLabel("\U0001f4b1 Trade Tracker")
        title.setProperty("cssClass", "widget-title")
        root.addWidget(title)

        content = QVBoxLayout()
        content.setContentsMargins(8, 8, 8, 8)
        content.setSpacing(8)

        # ── Summary KPIs ──
        kpi_group = QGroupBox("Trade Overview")
        kpi_group.setProperty("cssClass", "market-card")
        kpi_layout = QHBoxLayout(kpi_group)

        self._lbl_bought = self._make_kpi("Total Bought", "---")
        self._lbl_sold = self._make_kpi("Total Sold", "---")
        self._lbl_profit = self._make_kpi("Profit / Loss", "---")
        self._lbl_items = self._make_kpi("Traded Items", "---")

        for w in (self._lbl_bought, self._lbl_sold, self._lbl_profit, self._lbl_items):
            kpi_layout.addWidget(w)
        content.addWidget(kpi_group)

        # ── Filter ──
        filter_row = QHBoxLayout()
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("\U0001f50d Filter trades\u2026")
        self._filter_input.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._filter_input, 1)
        content.addLayout(filter_row)

        # ── Trade table ──
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels([
            "Item", "Bought (Qty)", "Bought (\u2211)",
            "Ø Bought", "Sold (Qty)", "Sold (\u2211)",
            "Ø Sold", "Profit", "Margin %",
        ])
        tracker_hdr = self._table.horizontalHeader()
        tracker_hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tracker_hdr.setStretchLastSection(True)
        tracker_hdr.resizeSection(0, 160)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        content.addWidget(self._table, 1)

        root.addLayout(content, 1)

    @staticmethod
    def _make_kpi(heading: str, value: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        h = QLabel(heading)
        h.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v = QLabel(value)
        v.setObjectName("kpiValue")
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        v.setStyleSheet(f"color: {Colors.ACCENT};")
        lay.addWidget(h)
        lay.addWidget(v)
        return w

    # ═══════════════════════════════════════════════════════════════
    #  Data loading
    # ═══════════════════════════════════════════════════════════════

    def update_transactions(self, transactions: list[dict[str, Any]]) -> None:
        """Called from MainWindow when wallet transactions are fetched."""
        self._do_analysis_sync(transactions)

    def _do_analysis_sync(self, transactions: list[dict[str, Any]]) -> None:
        """Synchronous fallback when no loop is available."""
        # Build a simple analysis without async calls
        buys: dict[int, list[dict]] = {}
        sells: dict[int, list[dict]] = {}

        for tx in transactions:
            tid = tx.get("type_id", 0)
            if tx.get("is_buy"):
                buys.setdefault(tid, []).append(tx)
            else:
                sells.setdefault(tid, []).append(tx)

        items = []
        total_bought = total_sold = total_profit = 0.0
        for tid in set(buys.keys()) | set(sells.keys()):
            buy_txs = buys.get(tid, [])
            sell_txs = sells.get(tid, [])
            bought_total = sum(t.get("unit_price", 0) * t.get("quantity", 0) for t in buy_txs)
            bought_qty = sum(t.get("quantity", 0) for t in buy_txs)
            sold_total = sum(t.get("unit_price", 0) * t.get("quantity", 0) for t in sell_txs)
            sold_qty = sum(t.get("quantity", 0) for t in sell_txs)
            avg_buy = bought_total / bought_qty if bought_qty else 0
            avg_sell = sold_total / sold_qty if sold_qty else 0
            profit = sold_total - bought_total
            total_bought += bought_total
            total_sold += sold_total
            total_profit += profit

            # Resolve name: prefer from transaction, fallback to SDE
            first_tx = (buy_txs or sell_txs)[0] if (buy_txs or sell_txs) else {}
            type_name = first_tx.get("type_name") or self._sde.get_type_name(tid)

            items.append({
                "type_id": tid,
                "type_name": type_name,
                "bought_qty": bought_qty, "bought_total": bought_total,
                "avg_buy_price": avg_buy,
                "sold_qty": sold_qty, "sold_total": sold_total,
                "avg_sell_price": avg_sell,
                "profit": profit,
                "margin_pct": ((avg_sell - avg_buy) / avg_buy * 100) if avg_buy else 0,
            })

        items.sort(key=lambda x: -abs(x["profit"]))
        self._display_result({
            "total_bought": total_bought,
            "total_sold": total_sold,
            "total_profit": total_profit,
            "items": items,
        })

    # ═══════════════════════════════════════════════════════════════
    #  Display
    # ═══════════════════════════════════════════════════════════════

    def _display_result(self, result: dict[str, Any]) -> None:
        total_bought = result.get("total_bought", 0)
        total_sold = result.get("total_sold", 0)
        total_profit = result.get("total_profit", 0)
        items = result.get("items", [])

        # KPIs
        bought_v = self._lbl_bought.findChild(QLabel, "kpiValue")
        sold_v = self._lbl_sold.findChild(QLabel, "kpiValue")
        profit_v = self._lbl_profit.findChild(QLabel, "kpiValue")
        items_v = self._lbl_items.findChild(QLabel, "kpiValue")

        if bought_v:
            bought_v.setText(_fmt_isk(total_bought))
            bought_v.setStyleSheet(f"color: {Colors.RED};")
        if sold_v:
            sold_v.setText(_fmt_isk(total_sold))
            sold_v.setStyleSheet(f"color: {Colors.GREEN};")
        if profit_v:
            profit_v.setText(_fmt_isk(total_profit))
            color = Colors.GREEN if total_profit >= 0 else Colors.RED
            profit_v.setStyleSheet(f"color: {color};")
        if items_v:
            items_v.setText(str(len(items)))

        # Table
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(items))
        for r, it in enumerate(items):
            self._table.setItem(r, 0, QTableWidgetItem(it.get("type_name", "?")))
            self._table.setItem(r, 1, QTableWidgetItem(str(it.get("bought_qty", 0))))
            self._table.setItem(r, 2, QTableWidgetItem(_fmt_isk(it.get("bought_total", 0))))
            self._table.setItem(r, 3, QTableWidgetItem(_fmt_isk(it.get("avg_buy_price", 0))))
            self._table.setItem(r, 4, QTableWidgetItem(str(it.get("sold_qty", 0))))
            self._table.setItem(r, 5, QTableWidgetItem(_fmt_isk(it.get("sold_total", 0))))
            self._table.setItem(r, 6, QTableWidgetItem(_fmt_isk(it.get("avg_sell_price", 0))))

            profit = it.get("profit", 0)
            profit_item = QTableWidgetItem(_fmt_isk(profit))
            profit_item.setForeground(
                QColor(Colors.GREEN) if profit >= 0 else QColor(Colors.RED),
            )
            self._table.setItem(r, 7, profit_item)

            margin = it.get("margin_pct", 0)
            margin_item = QTableWidgetItem(f"{margin:+.1f}%")
            margin_item.setForeground(
                QColor(Colors.GREEN) if margin >= 0 else QColor(Colors.RED),
            )
            self._table.setItem(r, 8, margin_item)

        self._table.setSortingEnabled(True)

    def _apply_filter(self, text: str) -> None:
        text = text.lower()
        for r in range(self._table.rowCount()):
            item = self._table.item(r, 0)
            visible = text in item.text().lower() if item else True
            self._table.setRowHidden(r, not visible)
