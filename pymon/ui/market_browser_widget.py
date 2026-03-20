"""Market Browser Widget – search items, view order book, price history & region comparison."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.api.esi_client import ESIClient
from pymon.sde.database import SDEDatabase
from pymon.services.market_service import (
    THE_FORGE,
    TRADE_HUBS,
    MarketService,
    MarketSnapshot,
    PriceHistoryDay,
    RegionComparison,
)
from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)

# Try to import pyqtgraph for price charts
try:
    import pyqtgraph as pg

    _HAS_PYQTGRAPH = True
except ImportError:
    _HAS_PYQTGRAPH = False


def _fmt_isk(value: float) -> str:
    """Format ISK value with thousand separators."""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.2f} Mrd"
    if value >= 1_000_000:
        return f"{value / 1_000_000:,.2f} Mio"
    if value >= 1_000:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def _fmt_vol(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:,.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:,.1f}k"
    return str(value)


class MarketBrowserWidget(QWidget):
    """Interactive market browser with search, order book, price chart & region comparison."""

    # Emitted when user selects a type (for cross-widget linking)
    type_selected = Signal(int, str)  # type_id, type_name

    # Internal signals for thread-safe UI updates from worker threads
    _data_ready = Signal(object, object, object, object)  # snap, history, comparison, orders
    _error_occurred = Signal(str)  # error message

    def __init__(
        self, esi: ESIClient, sde: SDEDatabase, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.sde = sde
        self._service = MarketService(esi, sde)
        self._current_type_id: int | None = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._do_search)
        self._data_ready.connect(self._on_data_ready)
        self._error_occurred.connect(self._on_error)
        self._setup_ui()
        self._load_market_tree()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Not needed – widget runs its own threads."""

    # ═══════════════════════════════════════════════════════════════
    #  UI Setup
    # ═══════════════════════════════════════════════════════════════

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title = QLabel("\U0001f4c8 Market Browser")
        title.setProperty("cssClass", "widget-title")
        root.addWidget(title)

        # Horizontal splitter: left (search/tree) | right (details)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── LEFT: Search + Market Group Tree ──
        left = QWidget()
        left.setMinimumWidth(260)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText("\U0001f50d Search item\u2026")
        self._search.textChanged.connect(self._on_search_text)
        left_layout.addWidget(self._search)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Market Group / Item"])
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch,
        )
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        self._tree.itemExpanded.connect(self._on_tree_item_expanded)
        left_layout.addWidget(self._tree)

        splitter.addWidget(left)

        # ── RIGHT: Details area ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(6)

        # Item header
        self._item_header = QLabel("Select an item from the market tree or search.")
        self._item_header.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._item_header.setStyleSheet(f"color: {Colors.GOLD};")
        right_layout.addWidget(self._item_header)

        # Region selector
        region_row = QHBoxLayout()
        region_row.addWidget(QLabel("Region:"))
        self._region_combo = QComboBox()
        for rid, name in TRADE_HUBS.items():
            self._region_combo.addItem(name, rid)
        self._region_combo.currentIndexChanged.connect(self._on_region_changed)
        region_row.addWidget(self._region_combo, 1)
        right_layout.addLayout(region_row)

        # ── Snapshot card ──
        snap_group = QGroupBox("Price Overview")
        snap_group.setProperty("cssClass", "market-card")
        snap_layout = QHBoxLayout(snap_group)

        self._lbl_sell = self._kpi_label("Best Sell", "---")
        self._lbl_buy = self._kpi_label("Best Buy", "---")
        self._lbl_spread = self._kpi_label("Spread", "---")
        self._lbl_avg = self._kpi_label("Avg Price (global)", "---")

        for w in (self._lbl_sell, self._lbl_buy, self._lbl_spread, self._lbl_avg):
            snap_layout.addWidget(w)
        right_layout.addWidget(snap_group)

        # ── Order book tables side-by-side ──
        orders_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._sell_table = self._make_order_table("Sell Orders")
        self._buy_table = self._make_order_table("Buy Orders")

        sell_group = QGroupBox("Sell Orders")
        sell_group.setProperty("cssClass", "market-card")
        sl = QVBoxLayout(sell_group)
        sl.setContentsMargins(2, 2, 2, 2)
        sl.addWidget(self._sell_table)
        orders_splitter.addWidget(sell_group)

        buy_group = QGroupBox("Buy Orders")
        buy_group.setProperty("cssClass", "market-card")
        bl = QVBoxLayout(buy_group)
        bl.setContentsMargins(2, 2, 2, 2)
        bl.addWidget(self._buy_table)
        orders_splitter.addWidget(buy_group)

        right_layout.addWidget(orders_splitter, 1)

        # ── Price history chart ──
        chart_group = QGroupBox("Price History (90 Days)")
        chart_group.setProperty("cssClass", "market-card")
        chart_layout = QVBoxLayout(chart_group)
        chart_layout.setContentsMargins(2, 2, 2, 2)

        if _HAS_PYQTGRAPH:
            pg.setConfigOptions(background=Colors.BG_DARK, foreground=Colors.TEXT)
            self._chart = pg.PlotWidget()
            self._chart.setMinimumHeight(180)
            self._chart.showGrid(x=True, y=True, alpha=0.15)
            self._chart.setLabel("left", "ISK")
            self._chart.setLabel("bottom", "Day")
            self._chart.addLegend(offset=(10, 10))
            chart_layout.addWidget(self._chart)
        else:
            self._chart = None
            chart_layout.addWidget(
                QLabel("pyqtgraph not installed \u2013 Price chart disabled."),
            )

        right_layout.addWidget(chart_group, 1)

        # ── Region comparison table ──
        cmp_group = QGroupBox("Region Comparison")
        cmp_group.setProperty("cssClass", "market-card")
        cmp_layout = QVBoxLayout(cmp_group)
        cmp_layout.setContentsMargins(2, 2, 2, 2)

        self._cmp_table = QTableWidget()
        self._cmp_table.setColumnCount(6)
        self._cmp_table.setHorizontalHeaderLabels([
            "Region", "Sell (min)", "Sell Vol", "Buy (max)", "Buy Vol", "Spread %",
        ])
        cmp_hdr = self._cmp_table.horizontalHeader()
        cmp_hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        cmp_hdr.setStretchLastSection(True)
        cmp_hdr.resizeSection(0, 180)
        cmp_hdr.resizeSection(1, 100)
        cmp_hdr.resizeSection(2, 80)
        cmp_hdr.resizeSection(3, 100)
        cmp_hdr.resizeSection(4, 80)
        self._cmp_table.setAlternatingRowColors(True)
        self._cmp_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._cmp_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        cmp_layout.addWidget(self._cmp_table)
        right_layout.addWidget(cmp_group)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    # ── helpers ──

    @staticmethod
    def _kpi_label(heading: str, value: str) -> QWidget:
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
    def _make_order_table(title: str) -> QTableWidget:
        t = QTableWidget()
        t.setColumnCount(3)
        t.setHorizontalHeaderLabels(["Price", "Volume", "Location"])
        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        hdr.resizeSection(0, 100)
        hdr.resizeSection(1, 80)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return t

    # ═══════════════════════════════════════════════════════════════
    #  Market group tree (lazy-loaded)
    # ═══════════════════════════════════════════════════════════════

    def _load_market_tree(self) -> None:
        """Load root market groups into the tree."""
        roots = self.sde.get_market_group_children(None)
        for grp in sorted(roots, key=lambda g: g.get("name_en", "")):
            item = QTreeWidgetItem([grp.get("name_en", "?")])
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "kind": "group",
                "id": grp.get("market_group_id"),
            })
            # Add dummy child so the expand arrow appears
            item.addChild(QTreeWidgetItem(["Loading\u2026"]))
            self._tree.addTopLevelItem(item)

    def _on_tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        """Lazy-load children when a market group is expanded."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("kind") != "group":
            return
        # Remove dummy if present
        if item.childCount() == 1 and item.child(0).text(0) == "Laden\u2026":
            item.removeChild(item.child(0))
        else:
            return  # already loaded

        gid = data["id"]

        # Sub-groups
        children = self.sde.get_market_group_children(gid)
        for child in sorted(children, key=lambda c: c.get("name_en", "")):
            ci = QTreeWidgetItem([child.get("name_en", "?")])
            ci.setData(0, Qt.ItemDataRole.UserRole, {
                "kind": "group",
                "id": child.get("market_group_id"),
            })
            ci.addChild(QTreeWidgetItem(["Loading\u2026"]))
            item.addChild(ci)

        # Items in this group (leaf)
        items = self._service.get_items_in_market_group(gid)
        for it in sorted(items, key=lambda i: i.get("name_en", "")):
            ii = QTreeWidgetItem([it.get("name_en", "?")])
            ii.setData(0, Qt.ItemDataRole.UserRole, {
                "kind": "type",
                "id": it.get("type_id"),
                "name": it.get("name_en"),
            })
            item.addChild(ii)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("kind") != "type":
            return
        self._select_type(data["id"], data.get("name", "?"))

    # ═══════════════════════════════════════════════════════════════
    #  Search
    # ═══════════════════════════════════════════════════════════════

    def _on_search_text(self, text: str) -> None:
        self._search_timer.start()

    def _do_search(self) -> None:
        query = self._search.text().strip()
        if len(query) < 2:
            self._load_market_tree_reset()
            return

        results = self._service.search_items(query, limit=80)
        self._tree.clear()
        for r in results:
            item = QTreeWidgetItem([r.get("name_en", "?")])
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "kind": "type",
                "id": r.get("type_id"),
                "name": r.get("name_en"),
            })
            self._tree.addTopLevelItem(item)

    def _load_market_tree_reset(self) -> None:
        self._tree.clear()
        self._load_market_tree()

    # ═══════════════════════════════════════════════════════════════
    #  Type selection → load prices
    # ═══════════════════════════════════════════════════════════════

    def _select_type(self, type_id: int, type_name: str) -> None:
        self._current_type_id = type_id
        self._item_header.setText(f"{type_name}  (ID {type_id})")
        self.type_selected.emit(type_id, type_name)
        self._load_market_data(type_id)

    def _on_region_changed(self, _idx: int) -> None:
        if self._current_type_id:
            self._load_market_data(self._current_type_id)

    def _load_market_data(self, type_id: int) -> None:
        import threading
        region_id = self._region_combo.currentData() or THE_FORGE
        self._item_header.setText(
            f"{self._item_header.text().split('  ⏳')[0]}  ⏳ Loading market data…"
        )

        def _worker() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._fetch_and_display(type_id, region_id))
            except Exception as e:
                logger.error("Market worker thread error: %s", e, exc_info=True)
                self._error_occurred.emit(f"Fehler beim Laden: {e}")
            finally:
                loop.close()

        threading.Thread(target=_worker, daemon=True, name="market-fetch").start()

    async def _fetch_and_display(self, type_id: int, region_id: int) -> None:
        """Fetch snapshot + orders + history + comparison, then update UI."""
        try:
            snap, history, comparison, orders = await asyncio.gather(
                self._service.get_item_snapshot(type_id, region_id),
                self._service.get_price_history(type_id, region_id, days=90),
                self._service.compare_regions(type_id),
                self._service.get_full_orders(type_id, region_id),
            )
            logger.info(
                "Market data loaded for %d: sell=%.2f buy=%.2f, %d orders, %d history days, %d regions",
                type_id, snap.sell_min, snap.buy_max, len(orders), len(history),
                len(comparison.snapshots),
            )
            # Emit signal for thread-safe UI update on main thread
            self._data_ready.emit(snap, history, comparison, orders)
        except Exception as e:
            logger.error("Market data fetch failed: %s", e, exc_info=True)
            self._error_occurred.emit(f"Error: {e}")

    # ═══════════════════════════════════════════════════════════════
    #  Signal slots (main thread)
    # ═══════════════════════════════════════════════════════════════

    def _on_data_ready(self, snap: Any, history: Any, comparison: Any, orders: Any) -> None:
        """Slot: called on main thread when market data arrives from worker."""
        self._update_ui(snap, history, comparison, orders)

    def _on_error(self, message: str) -> None:
        """Slot: called on main thread when an error occurs in worker."""
        self._item_header.setText(message)

    # ═══════════════════════════════════════════════════════════════
    #  UI Updates (main thread)
    # ═══════════════════════════════════════════════════════════════

    def _update_ui(
        self,
        snap: MarketSnapshot,
        history: list[PriceHistoryDay],
        comparison: RegionComparison,
        orders: list[dict[str, Any]] | None = None,
    ) -> None:
        # Update header to show loaded item (remove loading indicator)
        self._item_header.setText(f"{snap.type_name}  (ID {snap.type_id})")
        self._update_snapshot(snap)
        self._update_order_book(orders or [])
        self._update_chart(history)
        self._update_comparison(comparison)

    def _update_snapshot(self, snap: MarketSnapshot) -> None:
        """Update the KPI cards."""
        sell_w = self._lbl_sell.findChild(QLabel, "kpiValue")
        buy_w = self._lbl_buy.findChild(QLabel, "kpiValue")
        spr_w = self._lbl_spread.findChild(QLabel, "kpiValue")
        avg_w = self._lbl_avg.findChild(QLabel, "kpiValue")

        if sell_w:
            sell_w.setText(_fmt_isk(snap.sell_min) if snap.sell_min else "---")
            sell_w.setStyleSheet(f"color: {Colors.RED};")
        if buy_w:
            buy_w.setText(_fmt_isk(snap.buy_max) if snap.buy_max else "---")
            buy_w.setStyleSheet(f"color: {Colors.GREEN};")
        if spr_w:
            spr_w.setText(f"{snap.spread:.1f}%" if snap.spread else "---")
        if avg_w:
            avg_w.setText(_fmt_isk(snap.avg_price) if snap.avg_price else "---")

    def _update_order_book(self, orders: list[dict[str, Any]]) -> None:
        """Display individual sell/buy orders sorted by price."""
        sell_orders = sorted(
            [o for o in orders if not o.get("is_buy_order", False)],
            key=lambda o: o.get("price", 0),
        )
        buy_orders = sorted(
            [o for o in orders if o.get("is_buy_order", False)],
            key=lambda o: -o.get("price", 0),
        )

        # Show top 50 orders each
        max_rows = 50

        self._sell_table.setRowCount(min(len(sell_orders), max_rows))
        for r, o in enumerate(sell_orders[:max_rows]):
            price_item = QTableWidgetItem(_fmt_isk(o.get("price", 0)))
            price_item.setToolTip(f"{o.get('price', 0):,.2f} ISK")
            self._sell_table.setItem(r, 0, price_item)
            vol_item = QTableWidgetItem(_fmt_vol(o.get("volume_remain", 0)))
            vol_item.setToolTip(f"{o.get('volume_remain', 0):,}")
            self._sell_table.setItem(r, 1, vol_item)
            loc = self._resolve_location(o)
            loc_item = QTableWidgetItem(loc)
            loc_item.setToolTip(loc)
            self._sell_table.setItem(r, 2, loc_item)

        self._buy_table.setRowCount(min(len(buy_orders), max_rows))
        for r, o in enumerate(buy_orders[:max_rows]):
            price_item = QTableWidgetItem(_fmt_isk(o.get("price", 0)))
            price_item.setToolTip(f"{o.get('price', 0):,.2f} ISK")
            self._buy_table.setItem(r, 0, price_item)
            vol_item = QTableWidgetItem(_fmt_vol(o.get("volume_remain", 0)))
            vol_item.setToolTip(f"{o.get('volume_remain', 0):,}")
            self._buy_table.setItem(r, 1, vol_item)
            loc = self._resolve_location(o)
            loc_item = QTableWidgetItem(loc)
            loc_item.setToolTip(loc)
            self._buy_table.setItem(r, 2, loc_item)

    def _resolve_location(self, order: dict[str, Any]) -> str:
        """Resolve order location to a human-readable name."""
        loc_id = order.get("location_id", 0)
        # NPC station (ID < 1 trillion) — most specific name
        if loc_id and loc_id < 1_000_000_000_000:
            name = self.sde.get_station_name(loc_id)
            if name and "#" not in name:
                return name
        # Fallback to system name
        sys_id = order.get("system_id", 0)
        if sys_id:
            sys_name = self.sde.get_system_name(sys_id)
            if sys_name and "#" not in sys_name:
                # For player citadels (>1T), show system + hint
                if loc_id and loc_id >= 1_000_000_000_000:
                    return f"{sys_name} (Citadel)"
                return sys_name
        return f"Standort #{loc_id}" if loc_id else "?"

    def _update_chart(self, history: list[PriceHistoryDay]) -> None:
        if not self._chart or not history:
            return
        self._chart.clear()

        days_idx = list(range(len(history)))
        avg = [h.average for h in history]
        hi = [h.highest for h in history]
        lo = [h.lowest for h in history]

        pen_avg = pg.mkPen(color=Colors.ACCENT, width=2)
        pen_hi = pg.mkPen(color=Colors.RED, width=1, style=Qt.PenStyle.DashLine)
        pen_lo = pg.mkPen(color=Colors.GREEN, width=1, style=Qt.PenStyle.DashLine)

        self._chart.plot(days_idx, avg, pen=pen_avg, name="Avg Price")
        self._chart.plot(days_idx, hi, pen=pen_hi, name="High")
        self._chart.plot(days_idx, lo, pen=pen_lo, name="Low")

    def _update_comparison(self, comparison: RegionComparison) -> None:
        snaps = comparison.snapshots
        self._cmp_table.setRowCount(len(snaps))

        for r, s in enumerate(snaps):
            self._cmp_table.setItem(r, 0, QTableWidgetItem(s.region_name))

            sell_item = QTableWidgetItem(_fmt_isk(s.sell_min))
            sell_item.setForeground(
                Qt.GlobalColor.red if s.sell_min == comparison.best_sell_price
                else Qt.GlobalColor.white,
            )
            self._cmp_table.setItem(r, 1, sell_item)
            self._cmp_table.setItem(r, 2, QTableWidgetItem(_fmt_vol(s.sell_volume)))

            buy_item = QTableWidgetItem(_fmt_isk(s.buy_max))
            buy_item.setForeground(
                Qt.GlobalColor.green if s.buy_max == comparison.best_buy_price
                else Qt.GlobalColor.white,
            )
            self._cmp_table.setItem(r, 3, buy_item)
            self._cmp_table.setItem(r, 4, QTableWidgetItem(_fmt_vol(s.buy_volume)))
            self._cmp_table.setItem(r, 5, QTableWidgetItem(f"{s.spread:.1f}%"))
