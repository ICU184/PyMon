"""Market Service – market search, price comparison, trade tracking & recommendations.

Combines ESI market APIs with SDE static data to provide:
- Item search with market-group browsing
- Region price comparison (buy/sell spread, volume)
- Price history with trend analysis
- Trade profit tracking (buy→sell matching)
- Mining/industry sell recommendations with ISK/h calculations
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pymon.api.esi_client import ESIClient
from pymon.api.market import MarketAPI
from pymon.sde.database import SDEDatabase

logger = logging.getLogger(__name__)

# ── The Forge = Jita region ──
THE_FORGE = 10000002
DOMAIN = 10000043      # Amarr
SINQ_LAISON = 10000032  # Dodixie
METROPOLIS = 10000042   # Hek/Rens
HEIMATAR = 10000030     # Rens

TRADE_HUBS: dict[int, str] = {
    THE_FORGE: "Jita (The Forge)",
    DOMAIN: "Amarr (Domain)",
    SINQ_LAISON: "Dodixie (Sinq Laison)",
    METROPOLIS: "Hek (Metropolis)",
    HEIMATAR: "Rens (Heimatar)",
}

DEFAULT_REGIONS = [THE_FORGE, DOMAIN, SINQ_LAISON, METROPOLIS, HEIMATAR]


# ═══════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class MarketSnapshot:
    """Current buy/sell snapshot for an item in a region."""
    type_id: int
    type_name: str
    region_id: int
    region_name: str
    sell_min: float = 0.0         # cheapest sell order
    sell_volume: int = 0          # total sell volume
    sell_order_count: int = 0
    buy_max: float = 0.0          # highest buy order
    buy_volume: int = 0           # total buy volume
    buy_order_count: int = 0
    spread: float = 0.0           # (sell_min - buy_max) / sell_min * 100
    avg_price: float = 0.0        # ESI global average
    adjusted_price: float = 0.0   # ESI adjusted price


@dataclass
class PriceHistoryDay:
    """One day of price history."""
    date: str
    average: float = 0.0
    highest: float = 0.0
    lowest: float = 0.0
    volume: int = 0
    order_count: int = 0


@dataclass
class RegionComparison:
    """Price comparison of one item across multiple regions."""
    type_id: int
    type_name: str
    snapshots: list[MarketSnapshot] = field(default_factory=list)
    best_sell_region: str = ""
    best_sell_price: float = 0.0
    best_buy_region: str = ""
    best_buy_price: float = 0.0


@dataclass
class TradeRecommendation:
    """Buy/sell recommendation for a mined or manufactured item."""
    type_id: int
    type_name: str
    category: str = ""           # "ore", "mineral", "manufactured", "pi"
    quantity_available: int = 0  # how much the player has
    sell_price: float = 0.0      # best sell price (Jita)
    buy_price: float = 0.0       # best buy order price
    total_value_sell: float = 0.0
    total_value_buy: float = 0.0
    recommendation: str = ""     # "Sell Order", "Sell Sofort (Buy Order)", "Verarbeiten", "Halten"
    isk_per_unit: float = 0.0
    daily_volume: int = 0        # average daily traded volume
    margin_pct: float = 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Market Service
# ═══════════════════════════════════════════════════════════════════════

class MarketService:
    """High-level market analysis service."""

    def __init__(self, esi: ESIClient, sde: SDEDatabase) -> None:
        self._api = MarketAPI(esi)
        self._sde = sde
        self._price_cache: dict[int, dict[str, float]] = {}  # type_id → {avg, adj}
        self._price_cache_time: datetime | None = None

    # ── Item search ──────────────────────────────────────────────

    def search_items(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        """Search SDE for market-tradeable items."""
        results = self._sde.search_types(query, published_only=True, limit=limit)
        # Filter to items that have a market_group_id (tradeable)
        return [r for r in results if r.get("market_group_id")]

    def get_market_group_tree(self, parent_id: int | None = None) -> list[dict[str, Any]]:
        """Get market group children. None=root groups."""
        return self._sde.get_market_group_children(parent_id)

    def get_items_in_market_group(self, market_group_id: int) -> list[dict[str, Any]]:
        """Get all items in a specific market group."""
        return self._sde.get_types_by_market_group(market_group_id)

    # ── Price lookups ────────────────────────────────────────────

    async def get_global_prices(self) -> dict[int, dict[str, float]]:
        """Fetch ESI global average/adjusted prices (cached 1h)."""
        now = datetime.now(UTC)
        if self._price_cache and self._price_cache_time:
            age = (now - self._price_cache_time).total_seconds()
            if age < 3600:
                return self._price_cache

        try:
            raw = await self._api.get_market_prices()
            self._price_cache = {
                p["type_id"]: {
                    "average_price": p.get("average_price", 0.0),
                    "adjusted_price": p.get("adjusted_price", 0.0),
                }
                for p in raw
            }
            self._price_cache_time = now
            logger.info("Global prices cached: %d types", len(self._price_cache))
        except Exception as e:
            logger.warning("Failed to fetch global prices: %s", e)

        return self._price_cache

    async def get_item_snapshot(
        self, type_id: int, region_id: int = THE_FORGE,
    ) -> MarketSnapshot:
        """Get current buy/sell snapshot for an item in a region."""
        type_name = self._sde.get_type_name(type_id)
        region_name = TRADE_HUBS.get(region_id, self._sde.get_region_name(region_id))

        snap = MarketSnapshot(
            type_id=type_id, type_name=type_name,
            region_id=region_id, region_name=region_name,
        )

        try:
            orders = await self._api.get_region_orders(region_id, type_id=type_id)
        except Exception as e:
            logger.warning("Failed to fetch orders for %d in %d: %s", type_id, region_id, e)
            return snap

        sell_orders = [o for o in orders if not o.get("is_buy_order", False)]
        buy_orders = [o for o in orders if o.get("is_buy_order", False)]

        if sell_orders:
            snap.sell_min = min(o["price"] for o in sell_orders)
            snap.sell_volume = sum(o["volume_remain"] for o in sell_orders)
            snap.sell_order_count = len(sell_orders)

        if buy_orders:
            snap.buy_max = max(o["price"] for o in buy_orders)
            snap.buy_volume = sum(o["volume_remain"] for o in buy_orders)
            snap.buy_order_count = len(buy_orders)

        if snap.sell_min > 0 and snap.buy_max > 0:
            snap.spread = (snap.sell_min - snap.buy_max) / snap.sell_min * 100

        # Global averages
        prices = await self.get_global_prices()
        if type_id in prices:
            snap.avg_price = prices[type_id].get("average_price", 0.0)
            snap.adjusted_price = prices[type_id].get("adjusted_price", 0.0)

        return snap

    async def get_full_orders(
        self, type_id: int, region_id: int = THE_FORGE,
    ) -> list[dict[str, Any]]:
        """Get the full order list for an item in a region (all pages)."""
        try:
            return await self._api.get_region_orders(region_id, type_id=type_id)
        except Exception as e:
            logger.warning("Failed to fetch full orders for %d in %d: %s", type_id, region_id, e)
            return []

    async def compare_regions(
        self, type_id: int, region_ids: list[int] | None = None,
    ) -> RegionComparison:
        """Compare prices across multiple regions."""
        if region_ids is None:
            region_ids = DEFAULT_REGIONS

        type_name = self._sde.get_type_name(type_id)
        comparison = RegionComparison(type_id=type_id, type_name=type_name)

        # Fetch all regions in parallel
        tasks = [self.get_item_snapshot(type_id, rid) for rid in region_ids]
        snapshots = await asyncio.gather(*tasks, return_exceptions=True)

        for snap in snapshots:
            if isinstance(snap, Exception):
                continue
            comparison.snapshots.append(snap)

        # Find best prices
        sells = [(s.sell_min, s.region_name) for s in comparison.snapshots if s.sell_min > 0]
        buys = [(s.buy_max, s.region_name) for s in comparison.snapshots if s.buy_max > 0]

        if sells:
            best = min(sells, key=lambda x: x[0])
            comparison.best_sell_price = best[0]
            comparison.best_sell_region = best[1]
        if buys:
            best = max(buys, key=lambda x: x[0])
            comparison.best_buy_price = best[0]
            comparison.best_buy_region = best[1]

        return comparison

    async def get_price_history(
        self, type_id: int, region_id: int = THE_FORGE, days: int = 90,
    ) -> list[PriceHistoryDay]:
        """Get price history for an item."""
        try:
            raw = await self._api.get_market_history(region_id, type_id)
        except Exception as e:
            logger.warning("Failed to fetch history for %d: %s", type_id, e)
            return []

        # Filter to recent days
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        history = []
        for day in raw:
            if day.get("date", "") >= cutoff:
                history.append(PriceHistoryDay(
                    date=day["date"],
                    average=day.get("average", 0.0),
                    highest=day.get("highest", 0.0),
                    lowest=day.get("lowest", 0.0),
                    volume=day.get("volume", 0),
                    order_count=day.get("order_count", 0),
                ))

        return sorted(history, key=lambda h: h.date)

    # ── Trade recommendations ────────────────────────────────────

    async def get_mining_recommendations(
        self,
        mining_ledger: list[dict[str, Any]],
        region_id: int = THE_FORGE,
    ) -> list[TradeRecommendation]:
        """Analyse mined ores and recommend sell/reprocess."""
        # Aggregate quantities by type
        totals: dict[int, int] = {}
        for entry in mining_ledger:
            tid = entry.get("type_id", 0)
            qty = entry.get("quantity", 0)
            if tid and qty:
                totals[tid] = totals.get(tid, 0) + qty

        if not totals:
            return []

        recs: list[TradeRecommendation] = []
        prices = await self.get_global_prices()

        for type_id, quantity in sorted(totals.items(), key=lambda x: -x[1]):
            type_name = self._sde.get_type_name(type_id)

            rec = TradeRecommendation(
                type_id=type_id,
                type_name=type_name,
                category="ore",
                quantity_available=quantity,
            )

            # Get market snapshot
            try:
                snap = await self.get_item_snapshot(type_id, region_id)
                rec.sell_price = snap.sell_min
                rec.buy_price = snap.buy_max
                rec.total_value_sell = snap.sell_min * quantity
                rec.total_value_buy = snap.buy_max * quantity
                rec.isk_per_unit = snap.sell_min
                if snap.sell_min > 0 and snap.buy_max > 0:
                    rec.margin_pct = snap.spread
            except Exception:
                if type_id in prices:
                    rec.sell_price = prices[type_id].get("average_price", 0.0)
                    rec.total_value_sell = rec.sell_price * quantity
                    rec.isk_per_unit = rec.sell_price

            # Get reprocessed value
            reprocessed_value = 0.0
            materials = self._sde.get_type_materials(type_id)
            for mat in materials:
                mat_id = mat.get("material_type_id", 0)
                mat_qty = mat.get("quantity", 0)
                if mat_id in prices:
                    reprocessed_value += prices[mat_id].get("average_price", 0.0) * mat_qty

            # Recommendation logic
            if reprocessed_value > rec.total_value_sell and reprocessed_value > 0:
                rec.recommendation = "Verarbeiten (Reprocessing)"
            elif rec.sell_price > 0 and rec.buy_price > 0:
                if rec.margin_pct < 3:
                    rec.recommendation = "Sofort verkaufen (Buy Order)"
                else:
                    rec.recommendation = "Sell Order aufgeben"
            elif rec.sell_price > 0:
                rec.recommendation = "Sell Order aufgeben"
            else:
                rec.recommendation = "Hold (no market)"

            # Daily volume from history
            try:
                history = await self.get_price_history(type_id, region_id, days=7)
                if history:
                    rec.daily_volume = sum(h.volume for h in history) // max(len(history), 1)
            except Exception:
                pass

            recs.append(rec)

        # Sort by total value descending
        recs.sort(key=lambda r: -r.total_value_sell)
        return recs

    async def get_industry_recommendations(
        self,
        industry_products: list[dict[str, Any]],
        region_id: int = THE_FORGE,
    ) -> list[TradeRecommendation]:
        """Analyse manufactured products and recommend sell strategies."""
        recs: list[TradeRecommendation] = []
        prices = await self.get_global_prices()

        for product in industry_products:
            type_id = product.get("product_type_id", 0) or product.get("type_id", 0)
            quantity = product.get("runs", 1)
            if not type_id:
                continue

            type_name = self._sde.get_type_name(type_id)
            rec = TradeRecommendation(
                type_id=type_id,
                type_name=type_name,
                category="manufactured",
                quantity_available=quantity,
            )

            try:
                snap = await self.get_item_snapshot(type_id, region_id)
                rec.sell_price = snap.sell_min
                rec.buy_price = snap.buy_max
                rec.total_value_sell = snap.sell_min * quantity
                rec.total_value_buy = snap.buy_max * quantity
                rec.isk_per_unit = snap.sell_min
                if snap.sell_min > 0 and snap.buy_max > 0:
                    rec.margin_pct = snap.spread
            except Exception:
                if type_id in prices:
                    rec.sell_price = prices[type_id].get("average_price", 0.0)
                    rec.total_value_sell = rec.sell_price * quantity

            # Calculate manufacturing cost
            bp = self._sde.get_blueprint_for_product(type_id)
            material_cost = 0.0
            if bp:
                mats = self._sde.get_blueprint_materials(bp["blueprint_type_id"])
                for mat in mats:
                    mid = mat.get("type_id", 0)
                    mq = mat.get("quantity", 0)
                    if mid in prices:
                        material_cost += prices[mid].get("average_price", 0.0) * mq

            if material_cost > 0 and rec.sell_price > 0:
                margin = (rec.sell_price - material_cost) / rec.sell_price * 100
                rec.margin_pct = margin
                if margin > 15:
                    rec.recommendation = "Sell Order aufgeben (gute Marge)"
                elif margin > 5:
                    rec.recommendation = "Sell Order aufgeben"
                elif margin > 0:
                    rec.recommendation = "Sofort verkaufen (Buy Order)"
                else:
                    rec.recommendation = "⚠️ Verlustgeschäft – nicht verkaufen"
            else:
                rec.recommendation = "Sell Order aufgeben"

            recs.append(rec)

        recs.sort(key=lambda r: -r.total_value_sell)
        return recs

    async def get_trade_profit_analysis(
        self,
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Analyse wallet transactions for profit/loss tracking."""
        buys: dict[int, list[dict]] = {}   # type_id → [transactions]
        sells: dict[int, list[dict]] = {}

        for tx in transactions:
            tid = tx.get("type_id", 0)
            if tx.get("is_buy"):
                buys.setdefault(tid, []).append(tx)
            else:
                sells.setdefault(tid, []).append(tx)

        total_bought = 0.0
        total_sold = 0.0
        total_profit = 0.0
        items: list[dict[str, Any]] = []

        all_type_ids = set(buys.keys()) | set(sells.keys())
        for tid in all_type_ids:
            type_name = self._sde.get_type_name(tid)
            buy_txs = buys.get(tid, [])
            sell_txs = sells.get(tid, [])

            bought_total = sum(t["unit_price"] * t["quantity"] for t in buy_txs)
            bought_qty = sum(t["quantity"] for t in buy_txs)
            sold_total = sum(t["unit_price"] * t["quantity"] for t in sell_txs)
            sold_qty = sum(t["quantity"] for t in sell_txs)

            avg_buy = bought_total / bought_qty if bought_qty else 0
            avg_sell = sold_total / sold_qty if sold_qty else 0
            profit = sold_total - bought_total

            total_bought += bought_total
            total_sold += sold_total
            total_profit += profit

            items.append({
                "type_id": tid,
                "type_name": type_name,
                "bought_qty": bought_qty,
                "bought_total": bought_total,
                "avg_buy_price": avg_buy,
                "sold_qty": sold_qty,
                "sold_total": sold_total,
                "avg_sell_price": avg_sell,
                "profit": profit,
                "margin_pct": ((avg_sell - avg_buy) / avg_buy * 100) if avg_buy > 0 else 0,
            })

        items.sort(key=lambda x: -abs(x["profit"]))

        return {
            "total_bought": total_bought,
            "total_sold": total_sold,
            "total_profit": total_profit,
            "items": items,
        }
