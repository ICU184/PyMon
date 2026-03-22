"""Implant Calculator widget for PyMon.

Shows active implants with their attribute bonuses and calculates
the effect on skill training time.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.sde.database import SDEDatabase
from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)

# EVE attribute IDs (dogma) → display name mapping
ATTRIBUTE_MAP: dict[int, str] = {
    175: "Intelligence",
    176: "Charisma",
    177: "Memory",
    178: "Perception",
    179: "Willpower",
}

# Reverse: name → attribute ID
ATTR_NAME_TO_ID: dict[str, int] = {v.lower(): k for k, v in ATTRIBUTE_MAP.items()}

# Implant slot attribute ID
IMPLANT_SLOT_ATTR = 331  # implantness

# Attribute modifier dogma attribute IDs
ATTR_BONUS_IDS: dict[int, str] = {
    175: "intelligence",
    176: "charisma",
    177: "memory",
    178: "perception",
    179: "willpower",
}

# Bonus attribute IDs that modify character attributes
# These are the dogma attribute IDs for implant bonuses
BONUS_ATTR_IDS: dict[str, int] = {
    "intelligence": 209,  # intelligenceBonus
    "memory": 210,        # memoryBonus
    "charisma": 211,      # charismaBonus
    "willpower": 212,     # willpowerBonus
    "perception": 213,    # perceptionBonus
}

ATTR_COLORS: dict[str, str] = {
    "intelligence": Colors.BLUE,
    "memory": Colors.ACCENT,
    "perception": Colors.ORANGE,
    "willpower": Colors.RED,
    "charisma": "#c084fc",
}


class ImplantCalculatorWidget(QWidget):
    """Implant Calculator showing attribute bonuses and training time impact."""

    def __init__(self, sde: SDEDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sde = sde
        self._implant_ids: list[int] = []
        self._base_attributes: dict[str, int] = {
            "intelligence": 17,
            "memory": 17,
            "perception": 17,
            "willpower": 17,
            "charisma": 17,
        }
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Splitter: left = implant list, right = detail
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Implant tree ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("💉 Active Implants")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setProperty("cssClass", "widget-title")
        left_layout.addWidget(title)

        self.implant_tree = QTreeWidget()
        self.implant_tree.setHeaderLabels(["Slot", "Implant", "Bonus"])
        self.implant_tree.setColumnWidth(0, 50)
        self.implant_tree.setColumnWidth(1, 280)
        self.implant_tree.setAlternatingRowColors(True)
        self.implant_tree.setFont(QFont("Segoe UI", 10))
        self.implant_tree.header().setStretchLastSection(True)
        left_layout.addWidget(self.implant_tree)
        splitter.addWidget(left)

        # ── Right: Attribute summary & training impact ──
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        self.detail_label = QLabel("Loading implants...")
        self.detail_label.setTextFormat(Qt.TextFormat.RichText)
        self.detail_label.setWordWrap(True)
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.detail_label.setContentsMargins(12, 12, 12, 12)
        self.detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        right_scroll.setWidget(self.detail_label)
        splitter.addWidget(right_scroll)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    # ══════════════════════════════════════════════════════════
    #  DATA UPDATE
    # ══════════════════════════════════════════════════════════

    def set_data(
        self,
        implant_ids: list[int] | None = None,
        base_attributes: dict[str, int] | None = None,
    ) -> None:
        """Update implant data and redraw."""
        if implant_ids is not None:
            self._implant_ids = implant_ids
        if base_attributes is not None:
            self._base_attributes = base_attributes
        self._refresh()

    def _refresh(self) -> None:
        """Rebuild the implant tree and attribute summary."""
        self.implant_tree.clear()

        if not self._implant_ids:
            self.detail_label.setText(
                "<h3>💉 Implant Calculator</h3>"
                "<p style='color:{Colors.TEXT_DIM}'>No active implants.</p>"
            )
            return

        # Analyze each implant
        implant_data: list[dict[str, Any]] = []
        total_bonuses: dict[str, float] = {
            "intelligence": 0, "memory": 0, "perception": 0,
            "willpower": 0, "charisma": 0,
        }

        for type_id in self._implant_ids:
            name = self.sde.get_type_name(type_id)
            dogma_attrs = self.sde.get_type_dogma_attributes(type_id)

            slot = 0
            bonuses: dict[str, float] = {}

            for da in dogma_attrs:
                attr_id = da["attribute_id"]
                value = da.get("value", 0) or 0

                # Check for slot number
                if attr_id == IMPLANT_SLOT_ATTR:
                    slot = int(value)

                # Check for attribute bonuses
                for attr_name, bonus_id in BONUS_ATTR_IDS.items():
                    if attr_id == bonus_id and value != 0:
                        bonuses[attr_name] = float(value)
                        total_bonuses[attr_name] += float(value)

            implant_data.append({
                "type_id": type_id,
                "name": name,
                "slot": slot,
                "bonuses": bonuses,
            })

        # Sort by slot
        implant_data.sort(key=lambda x: x["slot"])

        # ── Fill tree ──
        for imp in implant_data:
            bonus_text = ""
            if imp["bonuses"]:
                parts = []
                for attr_name, val in imp["bonuses"].items():
                    parts.append(f"+{val:.0f} {attr_name[:3].upper()}")
                bonus_text = ", ".join(parts)
            else:
                bonus_text = "—"

            item = QTreeWidgetItem([
                str(imp["slot"]) if imp["slot"] else "?",
                imp["name"],
                bonus_text,
            ])

            # Color bonus column
            if imp["bonuses"]:
                item.setForeground(2, QColor(Colors.ACCENT))
            else:
                item.setForeground(2, QColor(Colors.TEXT_DIM))

            self.implant_tree.addTopLevelItem(item)

        # ── Build detail HTML ──
        self._build_detail_html(implant_data, total_bonuses)

    def _build_detail_html(
        self,
        implant_data: list[dict[str, Any]],
        total_bonuses: dict[str, float],
    ) -> None:
        """Build the attribute summary and training impact HTML."""
        html = "<h3>🧮 Attribute Summary</h3>"

        # Attribute comparison table
        html += (
            "<table cellspacing='6' style='margin:8px 0'>"
            "<tr><th style='text-align:left'>Attribute</th>"
            "<th>Base</th><th>Bonus</th><th>Total</th></tr>"
        )

        effective: dict[str, float] = {}
        for attr_name in ["perception", "memory", "willpower", "intelligence", "charisma"]:
            base = self._base_attributes.get(attr_name, 17)
            bonus = total_bonuses.get(attr_name, 0)
            total = base + bonus
            effective[attr_name] = total
            color = ATTR_COLORS.get(attr_name, Colors.TEXT_HEADING)
            bonus_color = Colors.ACCENT if bonus > 0 else Colors.TEXT_DIM

            html += (
                f"<tr>"
                f"<td style='color:{color}'><b>{attr_name.capitalize()}</b></td>"
                f"<td style='text-align:center'>{base}</td>"
                f"<td style='text-align:center;color:{bonus_color}'>"
                f"{'+' + str(int(bonus)) if bonus > 0 else '—'}</td>"
                f"<td style='text-align:center;color:{color}'><b>{total:.0f}</b></td>"
                f"</tr>"
            )

        html += "</table>"

        # Training speed comparison
        html += "<h3>⏱️ Training Speed</h3>"

        # SP/min formula: primary_attr + secondary_attr/2
        # We show SP/hour for common attribute combinations
        attr_combos = [
            ("Intelligence", "Memory", "intelligence", "memory"),
            ("Perception", "Willpower", "perception", "willpower"),
            ("Charisma", "Willpower", "charisma", "willpower"),
            ("Memory", "Intelligence", "memory", "intelligence"),
            ("Willpower", "Perception", "willpower", "perception"),
            ("Memory", "Charisma", "memory", "charisma"),
        ]

        html += (
            "<table cellspacing='6' style='margin:8px 0'>"
            "<tr><th style='text-align:left'>Primary / Secondary</th>"
            "<th>Base SP/h</th><th>With Implants SP/h</th><th>Gain</th></tr>"
        )

        for prim_name, sec_name, prim_key, sec_key in attr_combos:
            base_prim = self._base_attributes.get(prim_key, 17)
            base_sec = self._base_attributes.get(sec_key, 17)
            eff_prim = effective.get(prim_key, 17)
            eff_sec = effective.get(sec_key, 17)

            base_spm = base_prim + base_sec / 2
            eff_spm = eff_prim + eff_sec / 2
            base_sph = base_spm * 60
            eff_sph = eff_spm * 60
            gain = eff_sph - base_sph
            gain_pct = (gain / base_sph * 100) if base_sph > 0 else 0

            prim_color = ATTR_COLORS.get(prim_key, Colors.TEXT_HEADING)
            sec_color = ATTR_COLORS.get(sec_key, Colors.TEXT_HEADING)
            gain_color = Colors.ACCENT if gain > 0 else Colors.TEXT_DIM

            html += (
                f"<tr>"
                f"<td><span style='color:{prim_color}'>{prim_name}</span> / "
                f"<span style='color:{sec_color}'>{sec_name}</span></td>"
                f"<td style='text-align:center'>{base_sph:,.0f}</td>"
                f"<td style='text-align:center;color:{Colors.ACCENT}'><b>{eff_sph:,.0f}</b></td>"
                f"<td style='text-align:center;color:{gain_color}'>"
                f"+{gain:,.0f} ({gain_pct:+.1f}%)</td>"
                f"</tr>"
            )

        html += "</table>"

        # Training time comparison for example skills
        html += "<h3>📊 Example Training Times</h3>"
        html += "<p style='color:{Colors.TEXT_DIM}'>Comparison: Base Attributes vs. With Implants</p>"

        # SP requirements by skill level
        sp_per_level = {1: 250, 2: 1415, 3: 8000, 4: 45255, 5: 256000}
        rank_examples = [1, 2, 3, 5, 8, 12]

        html += (
            "<table cellspacing='6' style='margin:8px 0'>"
            "<tr><th>Skill (INT/MEM)</th><th>Base</th><th>With Implants</th><th>Saved</th></tr>"
        )

        base_prim = self._base_attributes.get("intelligence", 17)
        base_sec = self._base_attributes.get("memory", 17)
        eff_prim = effective.get("intelligence", 17)
        eff_sec = effective.get("memory", 17)

        for rank in rank_examples:
            for level in [4, 5]:
                sp = sp_per_level.get(level, 0) * rank
                base_spm = base_prim + base_sec / 2
                eff_spm = eff_prim + eff_sec / 2
                base_mins = sp / base_spm if base_spm > 0 else 999999
                eff_mins = sp / eff_spm if eff_spm > 0 else 999999
                saved = base_mins - eff_mins

                html += (
                    f"<tr>"
                    f"<td>Rank {rank} → Lv{level} ({sp:,} SP)</td>"
                    f"<td>{_format_time(base_mins)}</td>"
                    f"<td style='color:{Colors.ACCENT}'>{_format_time(eff_mins)}</td>"
                    f"<td style='color:{Colors.ACCENT}'>-{_format_time(saved)}</td>"
                    f"</tr>"
                )

        html += "</table>"

        # Implant details
        attr_implants = [i for i in implant_data if i["bonuses"]]
        hw_implants = [i for i in implant_data if not i["bonuses"]]

        if attr_implants:
            html += "<h3>💉 Attribute Implants</h3>"
            for imp in attr_implants:
                bonuses_str = ", ".join(
                    f"<span style='color:{ATTR_COLORS.get(k, '#c9d1d9')}'>"
                    f"+{v:.0f} {k.capitalize()}</span>"
                    for k, v in imp["bonuses"].items()
                )
                html += (
                    f"<div style='margin:4px 0;padding:8px;background:#161b22;"
                    f"border-radius:4px;border-left:3px solid #4ecca3'>"
                    f"<b>Slot {imp['slot']}</b> — {imp['name']}<br>"
                    f"{bonuses_str}</div>"
                )

        if hw_implants:
            html += "<h3>⚡ Hardwiring Implants</h3>"
            for imp in hw_implants:
                html += (
                    f"<div style='margin:4px 0;padding:8px;background:#161b22;"
                    f"border-radius:4px;border-left:3px solid #f0ad4e'>"
                    f"<b>Slot {imp['slot']}</b> — {imp['name']}</div>"
                )

        self.detail_label.setText(html)


def _format_time(minutes: float) -> str:
    """Format minutes to a human-readable time string."""
    if minutes <= 0:
        return "—"
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    if days < 1:
        return f"{hours:.1f}h"
    remaining_hours = hours % 24
    return f"{days:.0f}d {remaining_hours:.0f}h"
