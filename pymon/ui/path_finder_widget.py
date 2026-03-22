"""Path Finder widget – shortest route between solar systems.

Uses SDE stargate data to build a graph of New Eden and runs
Dijkstra (BFS with uniform weights) to find shortest jump routes.
Displays route with jump count, security status, and region info.
"""

from __future__ import annotations

import heapq
import logging
from collections import defaultdict
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCompleter,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.sde.database import SDEDatabase
from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)


def _sec_color(sec: float) -> str:
    """CSS hex color for security status."""
    if sec >= 1.0:
        return Colors.ACCENT
    elif sec >= 0.9:
        return Colors.ACCENT
    elif sec >= 0.7:
        return "#3dbc76"
    elif sec >= 0.5:
        return "#7cca4e"
    elif sec >= 0.3:
        return Colors.ORANGE
    elif sec >= 0.1:
        return "#e07c3e"
    else:
        return Colors.RED


def _sec_tag(sec: float) -> str:
    """Format security status as colored string."""
    rounded = max(-1.0, min(1.0, round(sec, 1)))
    return f"<span style='color:{_sec_color(sec)}'>{rounded:.1f}</span>"


class PathFinderWidget(QWidget):
    """Path Finder – route planner for EVE Online solar systems."""

    def __init__(self, sde: SDEDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sde = sde

        # Graph: system_id → set of connected system_ids
        self._graph: dict[int, set[int]] = defaultdict(set)
        # System name → id lookup
        self._name_to_id: dict[str, int] = {}
        # System id → info cache
        self._system_cache: dict[int, dict[str, Any]] = {}

        self._build_graph()
        self._setup_ui()

    # ── Graph building ─────────────────────────────────────────

    def _build_graph(self) -> None:
        """Build jump graph from SDE stargate data."""
        try:
            rows = self.sde.conn.execute(
                "SELECT solar_system_id, dest_system_id FROM map_stargates"
            ).fetchall()
            for row in rows:
                src = row["solar_system_id"]
                dst = row["dest_system_id"]
                self._graph[src].add(dst)
                self._graph[dst].add(src)

            # Build name lookup
            systems = self.sde.conn.execute(
                "SELECT system_id, name_en, security_status, constellation_id, region_id "
                "FROM map_solar_systems"
            ).fetchall()
            for sys in systems:
                sid = sys["system_id"]
                name = sys["name_en"]
                self._name_to_id[name] = sid
                self._system_cache[sid] = dict(sys)

            logger.info(
                "Path Finder graph: %d systems, %d connections",
                len(self._graph),
                sum(len(v) for v in self._graph.values()) // 2,
            )
        except Exception:
            logger.error("Failed to build jump graph", exc_info=True)

    # ── Pathfinding ────────────────────────────────────────────

    def find_shortest_path(
        self,
        start_id: int,
        end_id: int,
        *,
        avoid_lowsec: bool = False,
        avoid_nullsec: bool = False,
    ) -> list[int] | None:
        """Find shortest path (BFS/Dijkstra with uniform weights).

        Returns list of system IDs from start to end, or None.
        """
        if start_id == end_id:
            return [start_id]
        if start_id not in self._graph or end_id not in self._graph:
            return None

        # BFS with optional security filtering
        # Priority queue: (distance, system_id)
        visited: set[int] = set()
        prev: dict[int, int] = {}
        queue: list[tuple[int, int]] = [(0, start_id)]

        while queue:
            dist, current = heapq.heappop(queue)
            if current in visited:
                continue
            visited.add(current)

            if current == end_id:
                # Reconstruct path
                path = [end_id]
                while path[-1] != start_id:
                    path.append(prev[path[-1]])
                return list(reversed(path))

            for neighbor in self._graph.get(current, set()):
                if neighbor in visited:
                    continue

                # Security filter (don't filter start/end)
                if neighbor != end_id:
                    info = self._system_cache.get(neighbor, {})
                    sec = info.get("security_status", 0.0)
                    if avoid_lowsec and 0.0 < sec < 0.5:
                        continue
                    if avoid_nullsec and sec <= 0.0:
                        continue

                prev[neighbor] = current
                heapq.heappush(queue, (dist + 1, neighbor))

        return None  # No path found

    # ── UI ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Title
        title = QLabel("<h3>🗺️ Path Finder – Route Planning</h3>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        system_names = sorted(self._name_to_id.keys())
        completer_from = QCompleter(system_names)
        completer_from.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer_from.setFilterMode(Qt.MatchFlag.MatchContains)
        completer_to = QCompleter(system_names)
        completer_to.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer_to.setFilterMode(Qt.MatchFlag.MatchContains)

        # Input row
        input_group = QGroupBox("Route")
        input_layout = QHBoxLayout(input_group)

        input_layout.addWidget(QLabel("From:"))
        self.from_input = QLineEdit()
        self.from_input.setPlaceholderText("System Name (e.g. Jita)")
        self.from_input.setCompleter(completer_from)
        self.from_input.returnPressed.connect(self._on_find)
        input_layout.addWidget(self.from_input, stretch=1)

        input_layout.addWidget(QLabel("To:"))
        self.to_input = QLineEdit()
        self.to_input.setPlaceholderText("System Name (e.g. Amarr)")
        self.to_input.setCompleter(completer_to)
        self.to_input.returnPressed.connect(self._on_find)
        input_layout.addWidget(self.to_input, stretch=1)

        self.find_btn = QPushButton("🔍 Find Route")
        self.find_btn.clicked.connect(self._on_find)
        input_layout.addWidget(self.find_btn)

        layout.addWidget(input_group)

        # Security filter
        sec_layout = QHBoxLayout()
        sec_layout.addWidget(QLabel("Preference:"))
        self.radio_shortest = QRadioButton("Shortest Route")
        self.radio_shortest.setChecked(True)
        sec_layout.addWidget(self.radio_shortest)
        self.radio_highsec = QRadioButton("Prefer Highsec (≥ 0.5)")
        sec_layout.addWidget(self.radio_highsec)
        self.radio_safe = QRadioButton("Highsec Only")
        sec_layout.addWidget(self.radio_safe)
        sec_layout.addStretch()
        layout.addLayout(sec_layout)

        # Results
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Summary
        self.summary_label = QLabel(
            "<p style='color:{Colors.TEXT_DIM}'>Enter start and destination system to calculate a route.</p>"
        )
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        splitter.addWidget(self.summary_label)

        # Route table
        self.route_table = QTableWidget()
        self.route_table.setColumnCount(6)
        self.route_table.setHorizontalHeaderLabels([
            "#", "System", "Security", "Region", "Constellation", "Jumps Left"
        ])
        self.route_table.setAlternatingRowColors(True)
        self.route_table.verticalHeader().setVisible(False)
        self.route_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.route_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.route_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        splitter.addWidget(self.route_table)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

    # ── Actions ────────────────────────────────────────────────

    def _on_find(self) -> None:
        """Find and display route."""
        from_name = self.from_input.text().strip()
        to_name = self.to_input.text().strip()

        if not from_name or not to_name:
            self.summary_label.setText(
                "<p style='color:{Colors.ORANGE}'>Please enter start and destination system.</p>"
            )
            return

        start_id = self._name_to_id.get(from_name)
        end_id = self._name_to_id.get(to_name)

        if start_id is None:
            # Try case-insensitive lookup
            for name, sid in self._name_to_id.items():
                if name.lower() == from_name.lower():
                    start_id = sid
                    from_name = name
                    self.from_input.setText(name)
                    break
        if end_id is None:
            for name, sid in self._name_to_id.items():
                if name.lower() == to_name.lower():
                    end_id = sid
                    to_name = name
                    self.to_input.setText(name)
                    break

        if start_id is None:
            self.summary_label.setText(
                f"<p style='color:{Colors.RED}'>System '{from_name}' not found.</p>"
            )
            return
        if end_id is None:
            self.summary_label.setText(
                f"<p style='color:{Colors.RED}'>System '{to_name}' not found.</p>"
            )
            return

        # Determine security filter
        avoid_low = self.radio_safe.isChecked()
        avoid_null = self.radio_highsec.isChecked() or self.radio_safe.isChecked()

        path = self.find_shortest_path(
            start_id, end_id,
            avoid_lowsec=avoid_low,
            avoid_nullsec=avoid_null,
        )

        if path is None:
            fallback = ""
            if avoid_low or avoid_null:
                fallback = "<br><i>Try 'Shortest Route' — there might be no safe path.</i>"
            self.summary_label.setText(
                f"<p style='color:{Colors.RED}'>No route from {from_name} to {to_name} found.{fallback}</p>"
            )
            self.route_table.setRowCount(0)
            return

        jumps = len(path) - 1

        # Analyze route security
        secs = [self._system_cache.get(sid, {}).get("security_status", 0.0) for sid in path]
        highsec = sum(1 for s in secs if s >= 0.5)
        lowsec = sum(1 for s in secs if 0.0 < s < 0.5)
        nullsec = sum(1 for s in secs if s <= 0.0)

        sec_summary = []
        if highsec:
            sec_summary.append(f"<span style='color:{Colors.ACCENT}'>{highsec} Highsec</span>")
        if lowsec:
            sec_summary.append(f"<span style='color:{Colors.ORANGE}'>{lowsec} Lowsec</span>")
        if nullsec:
            sec_summary.append(f"<span style='color:{Colors.RED}'>{nullsec} Nullsec</span>")

        self.summary_label.setText(
            f"<h4>Route: {from_name} → {to_name} — "
            f"<span style='color:{Colors.BLUE}'>{jumps} Jumps</span></h4>"
            f"<p>{' | '.join(sec_summary)}</p>"
        )

        # Populate table
        self.route_table.setRowCount(len(path))
        for i, sys_id in enumerate(path):
            info = self._system_cache.get(sys_id, {})
            name = info.get("name_en", f"#{sys_id}")
            sec = info.get("security_status", 0.0)
            region_id = info.get("region_id")
            const_id = info.get("constellation_id")

            region_name = self.sde.get_region_name(region_id) if region_id else "?"
            const_name = self.sde.get_constellation_name(const_id) if const_id else "?"

            remaining = jumps - i

            # Row items
            items = [
                str(i),
                name,
                f"{round(sec, 1):.1f}",
                region_name,
                const_name,
                str(remaining) if i < jumps else "—",
            ]
            for col, val in enumerate(items):
                item = QTableWidgetItem(val)

                # Color security column
                if col == 2:
                    from PySide6.QtGui import QColor
                    item.setForeground(QColor(_sec_color(sec)))

                # Highlight start/end
                if i == 0 or i == len(path) - 1:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)

                self.route_table.setItem(i, col, item)
