"""Ship Browser Widget – browse EVE ships by class with traits & bonuses."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.sde.database import SDEDatabase
from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)

_SHIP_CATEGORY_ID = 6

# Dogma attribute IDs for ship skill requirements
_REQ_SKILL_IDS = [182, 183, 184, 1285, 1289, 1290]
_REQ_LEVEL_IDS = [277, 278, 279, 1286, 1287, 1288]

# Styles are inherited from the global dark theme (see dark_theme.py)


class ShipBrowserWidget(QWidget):
    """Browse EVE Online ships grouped by class, with trait & bonus details."""

    def __init__(self, sde: SDEDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sde = sde
        self._trained_skills: dict[int, int] = {}
        self._setup_ui()
        self._load_ships()

    def set_trained_skills(self, trained: dict[int, int]) -> None:
        """Set trained skills dict for requirement checks."""
        self._trained_skills = trained

    # ──────────────────────────────────────────────────────────────
    #  UI Setup
    # ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("🚀 Ship Browser")
        title.setProperty("cssClass", "widget-title")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: search + ship tree ──
        left = QWidget()
        left.setMinimumWidth(280)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 0, 4, 4)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Search ship…")
        self._search.textChanged.connect(self._on_filter)
        left_layout.addWidget(self._search)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Ship", "Type-ID"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.setColumnWidth(1, 60)
        self._tree.itemClicked.connect(self._on_ship_selected)
        left_layout.addWidget(self._tree)

        self._count_label = QLabel("")
        left_layout.addWidget(self._count_label)

        splitter.addWidget(left)

        # ── Right: detail tabs ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 4, 4)

        self._detail_tabs = QTabWidget()

        # Overview tab
        self._overview_scroll = QScrollArea()
        self._overview_scroll.setWidgetResizable(True)
        self._overview_label = QLabel("Select a ship from the list.")
        self._overview_label.setWordWrap(True)
        self._overview_label.setTextFormat(Qt.TextFormat.RichText)
        self._overview_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._overview_label.setContentsMargins(10, 10, 10, 10)
        self._overview_scroll.setWidget(self._overview_label)
        self._detail_tabs.addTab(self._overview_scroll, "Overview")

        # Bonuses tab
        self._bonus_scroll = QScrollArea()
        self._bonus_scroll.setWidgetResizable(True)
        self._bonus_label = QLabel("")
        self._bonus_label.setWordWrap(True)
        self._bonus_label.setTextFormat(Qt.TextFormat.RichText)
        self._bonus_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._bonus_label.setContentsMargins(10, 10, 10, 10)
        self._bonus_scroll.setWidget(self._bonus_label)
        self._detail_tabs.addTab(self._bonus_scroll, "Bonuses & Traits")

        # Requirements tab
        self._req_scroll = QScrollArea()
        self._req_scroll.setWidgetResizable(True)
        self._req_label = QLabel("")
        self._req_label.setWordWrap(True)
        self._req_label.setTextFormat(Qt.TextFormat.RichText)
        self._req_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._req_label.setContentsMargins(10, 10, 10, 10)
        self._req_scroll.setWidget(self._req_label)
        self._detail_tabs.addTab(self._req_scroll, "Requirements")

        # Attributes tab
        self._attr_scroll = QScrollArea()
        self._attr_scroll.setWidgetResizable(True)
        self._attr_label = QLabel("")
        self._attr_label.setWordWrap(True)
        self._attr_label.setTextFormat(Qt.TextFormat.RichText)
        self._attr_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._attr_label.setContentsMargins(10, 10, 10, 10)
        self._attr_scroll.setWidget(self._attr_label)
        self._detail_tabs.addTab(self._attr_scroll, "Attributes")

        right_layout.addWidget(self._detail_tabs)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    # ──────────────────────────────────────────────────────────────
    #  Data loading
    # ──────────────────────────────────────────────────────────────

    def _load_ships(self) -> None:
        """Load all ships from SDE, grouped by ship class (group)."""
        # Query groups within Ship category
        groups = self.sde._get_rows(
            """SELECT g.group_id, g.name_en, COUNT(*) as cnt
               FROM groups g
               JOIN types t ON t.group_id = g.group_id
               WHERE g.category_id = ? AND g.published = 1 AND t.published = 1
               GROUP BY g.group_id
               ORDER BY g.name_en""",
            (_SHIP_CATEGORY_ID,),
        )

        total = 0
        for grp in groups:
            group_item = QTreeWidgetItem([
                f"{grp['name_en']} ({grp['cnt']})", "",
            ])
            group_item.setData(0, Qt.ItemDataRole.UserRole, ("group", grp["group_id"]))
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)

            ships = self.sde._get_rows(
                """SELECT type_id, name_en FROM types
                   WHERE group_id = ? AND published = 1
                   ORDER BY name_en""",
                (grp["group_id"],),
            )
            for ship in ships:
                child = QTreeWidgetItem([
                    ship["name_en"] or f"Ship #{ship['type_id']}",
                    str(ship["type_id"]),
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, ("type", ship["type_id"]))
                group_item.addChild(child)
                total += 1

            self._tree.addTopLevelItem(group_item)

        self._count_label.setText(f"{total} Ships in {len(groups)} Classes")

    def _on_filter(self, text: str) -> None:
        """Filter ships by name."""
        query = text.lower().strip()
        for i in range(self._tree.topLevelItemCount()):
            group_item = self._tree.topLevelItem(i)
            if not group_item:
                continue
            visible_children = 0
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                if not child:
                    continue
                match = not query or query in child.text(0).lower()
                child.setHidden(not match)
                if match:
                    visible_children += 1
            group_item.setHidden(visible_children == 0)
            if query and visible_children > 0:
                group_item.setExpanded(True)

    # ──────────────────────────────────────────────────────────────
    #  Detail panels
    # ──────────────────────────────────────────────────────────────

    def _on_ship_selected(self, item: QTreeWidgetItem, _col: int) -> None:
        """Show details for the selected ship."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "type":
            return
        type_id = data[1]
        self._show_overview(type_id)
        self._show_bonuses(type_id)
        self._show_requirements(type_id)
        self._show_attributes(type_id)

    def _show_overview(self, type_id: int) -> None:
        """Show ship overview: basic info and description."""
        t = self.sde.get_type(type_id)
        if not t:
            self._overview_label.setText(f"<p>Ship #{type_id} not found.</p>")
            return

        group = self.sde.get_group(t.get("group_id", 0))
        group_name = group["name_en"] if group else "?"

        html = f"<h2 style='color:{Colors.ACCENT}'>{t.get('name_en', '?')}</h2>"
        html += "<table cellspacing='6' style='font-size:13px'>"
        html += f"<tr><td><b>Type-ID:</b></td><td>{type_id}</td></tr>"
        html += f"<tr><td><b>Class:</b></td><td>{group_name}</td></tr>"

        if t.get("mass"):
            html += f"<tr><td><b>Mass:</b></td><td>{t['mass']:,.0f} kg</td></tr>"
        if t.get("volume"):
            html += f"<tr><td><b>Volume:</b></td><td>{t['volume']:,.2f} m³</td></tr>"
        if t.get("base_price"):
            html += f"<tr><td><b>Base Price:</b></td><td>{t['base_price']:,.2f} ISK</td></tr>"

        meta = self.sde.get_meta_group(t.get("meta_group_id")) if t.get("meta_group_id") else None
        if meta:
            html += f"<tr><td><b>Meta Group:</b></td><td>{meta.get('name_en', '?')}</td></tr>"

        market_group = self.sde.get_market_group(t.get("market_group_id", 0))
        if market_group:
            html += f"<tr><td><b>Market Group:</b></td><td>{market_group.get('name_en', '?')}</td></tr>"

        html += "</table>"

        desc = t.get("description_en", "")
        if desc:
            html += f"<h3 style='color:{Colors.GOLD}'>Description</h3>"
            html += f"<p style='color:{Colors.TEXT_DIM}; line-height:1.5'>{desc}</p>"

        self._overview_label.setText(html)

    def _show_bonuses(self, type_id: int) -> None:
        """Show role bonuses and skill-based trait bonuses."""
        role_bonuses = self.sde.get_type_role_bonuses(type_id)
        trait_bonuses = self.sde.get_type_trait_bonuses(type_id)

        if not role_bonuses and not trait_bonuses:
            self._bonus_label.setText(
                "<p style='color:#888'>No bonuses registered for this ship.</p>"
            )
            return

        t = self.sde.get_type(type_id)
        name = t.get("name_en", "?") if t else "?"
        html = f"<h2 style='color:{Colors.ACCENT}'>{name} – Bonuses</h2>"

        if role_bonuses:
            html += "<h3 style='color:{Colors.GOLD}'>⚙ Role Bonuses</h3>"
            html += "<ul style='line-height:1.8'>"
            for b in role_bonuses:
                bonus_text = b.get("bonus_text_en", "?")
                bonus_val = b.get("bonus") or b.get("bonus_amount")
                if bonus_val is not None:
                    html += f"<li><b>{bonus_val:+g}</b> {bonus_text}</li>"
                else:
                    html += f"<li>{bonus_text}</li>"
            html += "</ul>"

        if trait_bonuses:
            # Group by skill
            by_skill: dict[str, list[dict[str, Any]]] = {}
            for b in trait_bonuses:
                skill_name = b.get("skill_name", "Unknown Skill")
                by_skill.setdefault(skill_name, []).append(b)

            html += "<h3 style='color:{Colors.GOLD}'>📚 Skill-based Bonuses</h3>"
            for skill_name, bonuses in by_skill.items():
                html += f"<h4 style='color:{Colors.ACCENT}'>{skill_name}:</h4>"
                html += "<ul style='line-height:1.8'>"
                for b in bonuses:
                    bonus_text = b.get("bonus_text_en", "?")
                    bonus_val = b.get("bonus") or b.get("bonus_amount")
                    if bonus_val is not None:
                        html += f"<li><b>{bonus_val:+g}</b> {bonus_text}</li>"
                    else:
                        html += f"<li>{bonus_text}</li>"
                html += "</ul>"

        self._bonus_label.setText(html)

    def _show_requirements(self, type_id: int) -> None:
        """Show skill requirements to fly this ship."""
        attrs = self.sde.get_type_dogma_attributes(type_id)
        attr_map = {a["attribute_id"]: a["value"] for a in attrs}

        required: list[tuple[int, str, int]] = []
        for skill_attr, level_attr in zip(_REQ_SKILL_IDS, _REQ_LEVEL_IDS):
            skill_type_id = attr_map.get(skill_attr)
            req_level = attr_map.get(level_attr)
            if skill_type_id and req_level:
                sid = int(skill_type_id)
                lvl = int(req_level)
                type_info = self.sde.get_type(sid)
                name = type_info["name_en"] if type_info else f"Unknown ({sid})"
                required.append((sid, name, lvl))

        t = self.sde.get_type(type_id)
        name = t.get("name_en", "?") if t else "?"

        html = f"<h2 style='color:{Colors.ACCENT}'>{name} – Requirements</h2>"

        if not required:
            html += "<p style='color:#888'>No skill requirements.</p>"
            self._req_label.setText(html)
            return

        html += "<table cellspacing='4' style='font-size:13px'>"
        html += "<tr><th align='left'>Skill</th><th>Level</th><th>Status</th></tr>"

        level_roman = ["", "I", "II", "III", "IV", "V"]

        for sid, sname, slvl in required:
            trained = self._trained_skills.get(sid, 0)
            if trained >= slvl:
                status = "✓ Trained"
                color = Colors.ACCENT
            elif trained > 0:
                status = f"Lvl {trained} / {slvl}"
                color = Colors.GOLD
            else:
                status = "✗ Not trained"
                color = Colors.RED

            lvl_str = level_roman[min(slvl, 5)] if slvl <= 5 else str(slvl)
            html += (
                f"<tr>"
                f"<td>{sname}</td>"
                f"<td align='center'>{lvl_str}</td>"
                f"<td style='color:{color}'>{status}</td>"
                f"</tr>"
            )

        html += "</table>"

        # Summary
        all_met = all(
            self._trained_skills.get(sid, 0) >= slvl
            for sid, _, slvl in required
        )
        if all_met:
            html += "<p style='color:{Colors.ACCENT}; font-weight:bold; margin-top:12px'>✓ All requirements met - you can fly this ship!</p>"
        else:
            missing = sum(
                1 for sid, _, slvl in required
                if self._trained_skills.get(sid, 0) < slvl
            )
            html += f"<p style='color:{Colors.RED}; margin-top:12px'>✗ {missing} of {len(required)} skills missing or too low.</p>"

        self._req_label.setText(html)

    def _show_attributes(self, type_id: int) -> None:
        """Show key dogma attributes for the ship."""
        attrs = self.sde.get_type_dogma_attributes(type_id)
        if not attrs:
            self._attr_label.setText("<p style='color:#888'>No Dogma Attributes.</p>")
            return

        # Key ship attributes to highlight
        _KEY_ATTRS = {
            9: "Structure HP",
            263: "Shield HP",
            265: "Armor HP",
            48: "CPU Capacity",
            11: "Powergrid Capacity",
            283: "Drone Bandwidth",
            552: "Sensor Strength",
            14: "Max Velocity",
            70: "Inertia",
            37: "Max Targets",
            76: "Max Target Range",
            4: "Mass",
            161: "Volume",
            38: "Capacity",
            1137: "Drone Capacity",
            1271: "Specialization Hold",
        }

        t = self.sde.get_type(type_id)
        name = t.get("name_en", "?") if t else "?"

        html = f"<h2 style='color:{Colors.ACCENT}'>{name} – Attributes</h2>"

        # Key attributes first
        html += "<h3 style='color:{Colors.GOLD}'>Key Values</h3>"
        html += "<table cellspacing='4' style='font-size:13px'>"
        for a in attrs:
            if a["attribute_id"] in _KEY_ATTRS:
                label = _KEY_ATTRS[a["attribute_id"]]
                val = a["value"]
                if isinstance(val, float) and val == int(val):
                    val = int(val)
                html += f"<tr><td><b>{label}:</b></td><td>{val:,}</td></tr>"
        html += "</table>"

        # All attributes
        html += f"<h3 style='color:{Colors.GOLD}'>All Attributes ({len(attrs)})</h3>"
        html += "<table cellspacing='2' style='font-size:12px'>"
        html += "<tr><th align='left'>Attribute</th><th align='right'>Value</th></tr>"
        for a in sorted(attrs, key=lambda x: x.get("display_name_en") or x.get("name", "")):
            attr_name = a.get("display_name_en") or a.get("name", f"#{a['attribute_id']}")
            val = a["value"]
            html += f"<tr><td>{attr_name}</td><td align='right'>{val:g}</td></tr>"
        html += "</table>"

        self._attr_label.setText(html)
