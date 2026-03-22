"""Trade Advisor Widget – buy/sell recommendations for mined & manufactured resources."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.api.esi_client import ESIClient
from pymon.sde.database import SDEDatabase
from pymon.services.market_service import (
    THE_FORGE,
    TRADE_HUBS,
    MarketService,
    TradeRecommendation,
)
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


_REC_COLORS: dict[str, str] = {
    "Place Sell Order": Colors.GREEN,
    "Place Sell Order (good margin)": Colors.GREEN,
    "Sell Immediately (Buy Order)": Colors.ACCENT,
    "Reprocess": Colors.BLUE,
    "Hold (no market)": Colors.ORANGE,
    "\u26a0\ufe0f Loss making \u2013 do not sell": Colors.RED,
}


class TradeAdvisorWidget(QWidget):
    """Recommends sell/buy/reprocess actions for mined ores and manufactured goods."""

    # Internal signals for thread-safe UI updates from worker threads
    _recs_ready = Signal(object, object)  # mining_recs, industry_recs
    _error_occurred = Signal()

    def __init__(
        self, esi: ESIClient, sde: SDEDatabase, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = MarketService(esi, sde)
        self._mining_ledger: list[dict[str, Any]] = []
        self._industry_products: list[dict[str, Any]] = []
        self._recs_ready.connect(self._on_recs_ready)
        self._error_occurred.connect(self._on_error)
        self._setup_ui()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Not needed – widget runs its own threads."""

    # ═══════════════════════════════════════════════════════════════
    #  UI
    # ═══════════════════════════════════════════════════════════════

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Controls ──
        ctrl_row = QHBoxLayout()

        title = QLabel("\U0001f4a1 Trade Advisor")
        title.setProperty("cssClass", "widget-title")
        root.addWidget(title)

        content = QVBoxLayout()
        content.setContentsMargins(8, 8, 8, 8)
        content.setSpacing(8)

        # ── Controls ──
        ctrl_row = QHBoxLayout()

        ctrl_row.addWidget(QLabel("Region:"))
        self._region_combo = QComboBox()
        for rid, name in TRADE_HUBS.items():
            self._region_combo.addItem(name, rid)
        ctrl_row.addWidget(self._region_combo, 1)

        self._refresh_btn = QPushButton("\u21bb Update Recommendations")
        self._refresh_btn.setProperty("cssClass", "accent-button")
        self._refresh_btn.clicked.connect(self._on_refresh)
        ctrl_row.addWidget(self._refresh_btn)

        content.addLayout(ctrl_row)

        # ── Summary KPIs ──
        kpi_group = QGroupBox("Summary")
        kpi_group.setProperty("cssClass", "market-card")
        kpi_layout = QHBoxLayout(kpi_group)

        self._lbl_total_sell = self._make_kpi("Total Value (Sell)", "---")
        self._lbl_total_buy = self._make_kpi("Total Value (Buy)", "---")
        self._lbl_total_items = self._make_kpi("Resources", "---")
        self._lbl_best_action = self._make_kpi("Best Action", "---")

        for w in (self._lbl_total_sell, self._lbl_total_buy,
                  self._lbl_total_items, self._lbl_best_action):
            kpi_layout.addWidget(w)
        content.addWidget(kpi_group)

        # ── Mining recommendations ──
        mining_group = QGroupBox("\u26cf Mining Ores")
        mining_group.setProperty("cssClass", "market-card")
        mining_layout = QVBoxLayout(mining_group)
        mining_layout.setContentsMargins(4, 4, 4, 4)

        self._mining_table = self._make_rec_table()
        mining_layout.addWidget(self._mining_table)
        content.addWidget(mining_group, 1)

        # ── Industry recommendations ──
        industry_group = QGroupBox("\U0001f3ed Industry Products")
        industry_group.setProperty("cssClass", "market-card")
        industry_layout = QVBoxLayout(industry_group)
        industry_layout.setContentsMargins(4, 4, 4, 4)

        self._industry_table = self._make_rec_table()
        industry_layout.addWidget(self._industry_table)
        content.addWidget(industry_group, 1)

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

    @staticmethod
    def _make_rec_table() -> QTableWidget:
        t = QTableWidget()
        t.setColumnCount(8)
        t.setHorizontalHeaderLabels([
            "Item", "Quantity", "Sell Price", "Value (Sell)",
            "Buy Price", "Daily Volume", "Margin %", "Recommendation",
        ])
        rec_hdr = t.horizontalHeader()
        rec_hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        rec_hdr.setStretchLastSection(True)
        rec_hdr.resizeSection(0, 160)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setSortingEnabled(True)
        return t

    # ═══════════════════════════════════════════════════════════════
    #  Data input
    # ═══════════════════════════════════════════════════════════════

    def set_mining_ledger(self, ledger: list[dict[str, Any]]) -> None:
        self._mining_ledger = ledger

    def set_industry_products(self, products: list[dict[str, Any]]) -> None:
        self._industry_products = products

    def _on_refresh(self) -> None:
        import threading
        region_id = self._region_combo.currentData() or THE_FORGE
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Loading\u2026")

        def _worker() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._fetch_recommendations(region_id))
            finally:
                loop.close()

        threading.Thread(target=_worker, daemon=True, name="advisor-fetch").start()

    async def _fetch_recommendations(self, region_id: int) -> None:
        try:
            mining_recs: list[TradeRecommendation] = []
            industry_recs: list[TradeRecommendation] = []

            if self._mining_ledger:
                mining_recs = await self._service.get_mining_recommendations(
                    self._mining_ledger, region_id,
                )
            if self._industry_products:
                industry_recs = await self._service.get_industry_recommendations(
                    self._industry_products, region_id,
                )

            self._recs_ready.emit(mining_recs, industry_recs)
        except Exception as e:
            logger.error("Recommendation fetch failed: %s", e)
            self._error_occurred.emit()

    def _on_recs_ready(self, mining: list[TradeRecommendation], industry: list[TradeRecommendation]) -> None:
        """Slot: called on main thread when recommendations arrive from worker."""
        self._display(mining, industry)

    def _on_error(self) -> None:
        """Slot: called on main thread when an error occurs in worker."""
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("\u21bb Update Recommendations")

    # ═══════════════════════════════════════════════════════════════
    #  Display
    # ═══════════════════════════════════════════════════════════════

    def _display(
        self,
        mining: list[TradeRecommendation],
        industry: list[TradeRecommendation],
    ) -> None:
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("\u21bb Update Recommendations")

        all_recs = mining + industry

        # KPIs
        total_sell = sum(r.total_value_sell for r in all_recs)
        total_buy = sum(r.total_value_buy for r in all_recs)

        sell_v = self._lbl_total_sell.findChild(QLabel, "kpiValue")
        buy_v = self._lbl_total_buy.findChild(QLabel, "kpiValue")
        items_v = self._lbl_total_items.findChild(QLabel, "kpiValue")
        best_v = self._lbl_best_action.findChild(QLabel, "kpiValue")

        if sell_v:
            sell_v.setText(_fmt_isk(total_sell))
            sell_v.setStyleSheet(f"color: {Colors.GREEN};")
        if buy_v:
            buy_v.setText(_fmt_isk(total_buy))
            buy_v.setStyleSheet(f"color: {Colors.ACCENT};")
        if items_v:
            items_v.setText(str(len(all_recs)))

        # Best action = most common recommendation
        if best_v and all_recs:
            from collections import Counter
            rec_counts = Counter(r.recommendation for r in all_recs)
            most_common = rec_counts.most_common(1)[0][0]
            best_v.setText(most_common)
            best_v.setStyleSheet(
                f"color: {_REC_COLORS.get(most_common, Colors.ACCENT)}; font-size: 11px;",
            )

        # Tables
        self._fill_table(self._mining_table, mining)
        self._fill_table(self._industry_table, industry)

    def _fill_table(self, table: QTableWidget, recs: list[TradeRecommendation]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(len(recs))
        for r, rec in enumerate(recs):
            table.setItem(r, 0, QTableWidgetItem(rec.type_name))
            table.setItem(r, 1, QTableWidgetItem(f"{rec.quantity_available:,}"))
            table.setItem(r, 2, QTableWidgetItem(_fmt_isk(rec.sell_price)))

            val_item = QTableWidgetItem(_fmt_isk(rec.total_value_sell))
            val_item.setForeground(QColor(Colors.GREEN))
            table.setItem(r, 3, val_item)

            table.setItem(r, 4, QTableWidgetItem(_fmt_isk(rec.buy_price)))
            table.setItem(r, 5, QTableWidgetItem(f"{rec.daily_volume:,}"))

            margin_item = QTableWidgetItem(f"{rec.margin_pct:+.1f}%")
            margin_item.setForeground(
                QColor(Colors.GREEN) if rec.margin_pct >= 0 else QColor(Colors.RED),
            )
            table.setItem(r, 6, margin_item)

            rec_item = QTableWidgetItem(rec.recommendation)
            rec_color = _REC_COLORS.get(rec.recommendation, Colors.TEXT)
            rec_item.setForeground(QColor(rec_color))
            rec_item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            table.setItem(r, 7, rec_item)

        table.setSortingEnabled(True)
