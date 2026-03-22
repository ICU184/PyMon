"""Resolve EVE entity IDs to names via ESI /universe/names/ with local caching.

This service is used across all tabs to convert numeric IDs
(characters, corporations, alliances, factions, types, systems, etc.)
into human-readable names.  Results are cached in-memory and persisted
in SQLite so subsequent lookups are instant.
"""

from __future__ import annotations

import logging

from pymon.api.esi_client import ESIClient
from pymon.core.database import Database
from pymon.sde.database import SDEDatabase

logger = logging.getLogger(__name__)

# ESI /universe/names/ accepts at most 1000 IDs per request
_BATCH_SIZE = 1000

# ESI category → table column mapping
_CATEGORY_MAP = {
    "character": "character",
    "corporation": "corporation",
    "alliance": "alliance",
    "faction": "faction",
    "solar_system": "solar_system",
    "station": "station",
    "constellation": "constellation",
    "region": "region",
    "inventory_type": "type",
}


class NameResolver:
    """Resolve EVE entity IDs to names with multi-layer caching.

    Layer 1: In-memory dict (fastest)
    Layer 2: SQLite ``resolved_names`` table
    Layer 3: SDE lookups (types, systems, stations, factions, etc.)
    Layer 4: ESI ``POST /universe/names/`` (last resort)
    """

    def __init__(self, esi: ESIClient, db: Database, sde: SDEDatabase) -> None:
        self.esi = esi
        self.db = db
        self.sde = sde
        self._cache: dict[int, str] = {}
        self._ensure_table()
        self._cleanup_stale_placeholders()

    # ── public API ──────────────────────────────────────────────────

    async def resolve(self, entity_id: int) -> str:
        """Resolve a single ID to a name."""
        names = await self.resolve_many([entity_id])
        return names.get(entity_id, f"#{entity_id}")

    async def resolve_many(self, ids: list[int]) -> dict[int, str]:
        """Resolve multiple IDs to names, using cache layers.

        Returns:
            Mapping of id → name.  Unknown IDs are mapped to ``#<id>``.
        """
        if not ids:
            return {}

        result: dict[int, str] = {}
        remaining: list[int] = []

        # ── Layer 1: in-memory cache ───────────────────────────────
        for eid in ids:
            if eid in self._cache:
                result[eid] = self._cache[eid]
            else:
                remaining.append(eid)

        if not remaining:
            return result

        # ── Layer 2: SQLite cache ──────────────────────────────────
        db_found = self._lookup_db(remaining)
        for eid, name in db_found.items():
            result[eid] = name
            self._cache[eid] = name
        remaining = [eid for eid in remaining if eid not in db_found]

        if not remaining:
            return result

        # ── Layer 3: SDE lookups ───────────────────────────────────
        sde_found = self._lookup_sde(remaining)
        for eid, name in sde_found.items():
            result[eid] = name
            self._cache[eid] = name
            self._store_db(eid, name, "sde")
        remaining = [eid for eid in remaining if eid not in sde_found]

        if not remaining:
            return result

        # ── Layer 4: ESI /universe/names/ ──────────────────────────
        esi_found = await self._lookup_esi(remaining)
        for eid, (name, cat) in esi_found.items():
            result[eid] = name
            self._cache[eid] = name
            self._store_db(eid, name, cat)
        remaining = [eid for eid in remaining if eid not in esi_found]

        # Anything still unresolved gets a placeholder
        for eid in remaining:
            placeholder = f"#{eid}"
            result[eid] = placeholder
            self._cache[eid] = placeholder

        return result

    def get_cached(self, entity_id: int) -> str | None:
        """Return a name from cache only (no ESI call). Returns None if unknown."""
        return self._cache.get(entity_id)

    def warm_cache(self, mapping: dict[int, str]) -> None:
        """Pre-populate cache with known id→name mappings."""
        self._cache.update(mapping)

    # ── Layer 2: SQLite ────────────────────────────────────────────

    def _ensure_table(self) -> None:
        self.db.conn.execute("""
            CREATE TABLE IF NOT EXISTS resolved_names (
                entity_id   INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                category    TEXT DEFAULT ''
            )
        """)
        self.db.conn.commit()

    def _cleanup_stale_placeholders(self) -> None:
        """Remove cached placeholder names (e.g. '#123', 'Unknown Type #456')
        so they get re-resolved via ESI on next access."""
        try:
            deleted = self.db.conn.execute(
                "DELETE FROM resolved_names WHERE name LIKE '%#%' "
                "AND (name LIKE '#%' OR name LIKE 'Unknown %#%' "
                "OR name LIKE 'Station #%' OR name LIKE 'Location #%')"
            ).rowcount
            if deleted:
                self.db.conn.commit()
                logger.info("Cleaned up %d stale placeholder names from cache", deleted)
        except Exception:
            logger.debug("Could not clean up stale placeholders", exc_info=True)

    def _lookup_db(self, ids: list[int]) -> dict[int, str]:
        found: dict[int, str] = {}
        for batch_start in range(0, len(ids), 500):
            batch = ids[batch_start : batch_start + 500]
            placeholders = ",".join("?" * len(batch))
            rows = self.db.conn.execute(
                f"SELECT entity_id, name FROM resolved_names WHERE entity_id IN ({placeholders})",
                batch,
            ).fetchall()
            for row in rows:
                found[row["entity_id"]] = row["name"]
        return found

    def _store_db(self, entity_id: int, name: str, category: str) -> None:
        self.db.conn.execute(
            "INSERT OR REPLACE INTO resolved_names (entity_id, name, category) VALUES (?,?,?)",
            (entity_id, name, category),
        )
        self.db.conn.commit()

    # ── Layer 3: SDE ───────────────────────────────────────────────

    @staticmethod
    def _is_sde_fallback(name: str) -> bool:
        """Check if a name is an SDE fallback placeholder (e.g. 'Unknown Type #123')."""
        if not name:
            return True
        # All SDE fallback patterns: "Unknown Foo #123", "Foo #123", "Station #123"
        if "#" in name:
            parts = name.rsplit("#", 1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                return True
        return False

    def _lookup_sde(self, ids: list[int]) -> dict[int, str]:
        """Try resolving IDs via SDE (types, systems, factions, NPC corps, etc.)."""
        found: dict[int, str] = {}
        for eid in ids:
            # Type names (most common – items, ships, skills)
            name = self.sde.get_type_name(eid)
            if not self._is_sde_fallback(name):
                found[eid] = name
                continue
            # Solar system
            name = self.sde.get_system_name(eid)
            if not self._is_sde_fallback(name):
                found[eid] = name
                continue
            # Station
            stn = self.sde.get_station_name(eid)
            if not self._is_sde_fallback(stn):
                found[eid] = stn
                continue
            # Faction
            fname = self.sde.get_faction_name(eid)
            if not self._is_sde_fallback(fname):
                found[eid] = fname
                continue
            # NPC Corporation
            cname = self.sde.get_npc_corporation_name(eid)
            if not self._is_sde_fallback(cname):
                found[eid] = cname
                continue
            # NPC Character (agents)
            nname = self.sde.get_npc_character_name(eid)
            if not self._is_sde_fallback(nname):
                found[eid] = nname
                continue
            # Region
            rname = self.sde.get_region_name(eid)
            if not self._is_sde_fallback(rname):
                found[eid] = rname
                continue
            # Constellation
            con = self.sde.get_constellation_name(eid)
            if not self._is_sde_fallback(con):
                found[eid] = con
                continue
        return found

    # ── Layer 4: ESI ───────────────────────────────────────────────

    async def _lookup_esi(self, ids: list[int]) -> dict[int, tuple[str, str]]:
        """Resolve IDs via ESI POST /universe/names/.

        Returns dict of id → (name, category).
        """
        found: dict[int, tuple[str, str]] = {}
        # Deduplicate and filter invalid IDs
        unique_ids = sorted(set(eid for eid in ids if eid > 0))
        if not unique_ids:
            return found

        for batch_start in range(0, len(unique_ids), _BATCH_SIZE):
            batch = unique_ids[batch_start : batch_start + _BATCH_SIZE]
            try:
                results = await self.esi.post("/universe/names/", json_data=batch)
                if isinstance(results, list):
                    for entry in results:
                        eid = entry.get("id", 0)
                        name = entry.get("name", "")
                        cat = entry.get("category", "")
                        if eid and name:
                            found[eid] = (name, _CATEGORY_MAP.get(cat, cat))
            except Exception:
                logger.warning("ESI /universe/names/ failed for batch starting at %d", batch_start, exc_info=True)
        return found
