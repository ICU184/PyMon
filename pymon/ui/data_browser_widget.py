"""EVE Data Browser widget.

Browse SDE data: items, ships, blueprints, etc.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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


class DataBrowserWidget(QWidget):
    """SDE Data Browser tab widget."""

    def __init__(self, sde: SDEDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sde = sde
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: search + tree ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Category filter
        filter_layout = QHBoxLayout()
        self.category_combo = QComboBox()
        self.category_combo.addItem("All Categories", 0)
        self._load_categories()
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        filter_layout.addWidget(self.category_combo)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name...")
        self.search_input.returnPressed.connect(self._on_search)
        filter_layout.addWidget(self.search_input)
        left_layout.addLayout(filter_layout)

        # Results tree
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(["Name", "Type-ID", "Group"])
        self.result_tree.setAlternatingRowColors(True)
        self.result_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.result_tree.itemClicked.connect(self._on_item_selected)
        left_layout.addWidget(self.result_tree)

        splitter.addWidget(left)

        # ── Right: details ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.detail_tabs = QTabWidget()

        # Info tab
        self.info_label = QLabel("Select an item from the list.")
        self.info_label.setWordWrap(True)
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.info_label.setContentsMargins(8, 8, 8, 8)
        self.detail_tabs.addTab(self.info_label, "Info")

        # Dogma tab
        self.dogma_label = QLabel("")
        self.dogma_label.setWordWrap(True)
        self.dogma_label.setTextFormat(Qt.TextFormat.RichText)
        self.dogma_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.dogma_label.setContentsMargins(8, 8, 8, 8)
        self.detail_tabs.addTab(self.dogma_label, "Attributes")

        # Blueprint tab
        self.bp_label = QLabel("")
        self.bp_label.setWordWrap(True)
        self.bp_label.setTextFormat(Qt.TextFormat.RichText)
        self.bp_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.bp_label.setContentsMargins(8, 8, 8, 8)
        self.detail_tabs.addTab(self.bp_label, "Blueprint")

        # Reprocessing tab
        self.repro_label = QLabel("")
        self.repro_label.setWordWrap(True)
        self.repro_label.setTextFormat(Qt.TextFormat.RichText)
        self.repro_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.repro_label.setContentsMargins(8, 8, 8, 8)
        self.detail_tabs.addTab(self.repro_label, "Reprocessing")

        right_layout.addWidget(self.detail_tabs)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        # Initial load: show published categories
        self._on_category_changed(0)

    def _load_categories(self) -> None:
        """Load categories into combo box."""
        rows = self.sde._get_rows(
            "SELECT category_id, name_en FROM categories WHERE published=1 ORDER BY name_en"
        )
        for row in rows:
            self.category_combo.addItem(row["name_en"], row["category_id"])

    def _on_category_changed(self, index: int) -> None:
        """Load groups/items for selected category."""
        cat_id = self.category_combo.currentData()
        self.result_tree.clear()

        if not cat_id:
            # All categories - show top groups
            rows = self.sde._get_rows(
                """SELECT g.group_id, g.name_en, c.name_en as cat_name, COUNT(*) as cnt
                   FROM groups g
                   JOIN categories c ON c.category_id = g.category_id
                   JOIN types t ON t.group_id = g.group_id
                   WHERE g.published = 1 AND t.published = 1
                   GROUP BY g.group_id
                   ORDER BY c.name_en, g.name_en
                   LIMIT 200"""
            )
        else:
            rows = self.sde._get_rows(
                """SELECT g.group_id, g.name_en, c.name_en as cat_name, COUNT(*) as cnt
                   FROM groups g
                   JOIN categories c ON c.category_id = g.category_id
                   JOIN types t ON t.group_id = g.group_id
                   WHERE g.category_id = ? AND g.published = 1 AND t.published = 1
                   GROUP BY g.group_id
                   ORDER BY g.name_en""",
                (cat_id,),
            )

        for row in rows:
            group_item = QTreeWidgetItem([
                f"{row['name_en']} ({row['cnt']})",
                "", row.get("cat_name", ""),
            ])
            group_item.setData(0, Qt.ItemDataRole.UserRole, ("group", row["group_id"]))
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)

            # Load items in this group
            items = self.sde._get_rows(
                """SELECT type_id, name_en FROM types
                   WHERE group_id = ? AND published = 1
                   ORDER BY name_en LIMIT 500""",
                (row["group_id"],),
            )
            for item in items:
                child = QTreeWidgetItem([
                    item["name_en"] or f"Type #{item['type_id']}",
                    str(item["type_id"]),
                    row["name_en"],
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, ("type", item["type_id"]))
                group_item.addChild(child)

            self.result_tree.addTopLevelItem(group_item)

    def _on_search(self) -> None:
        """Search for items by name."""
        query = self.search_input.text().strip()
        if len(query) < 2:
            return

        self.result_tree.clear()
        results = self.sde.search_types(query, limit=200)

        for row in results:
            item = QTreeWidgetItem([
                row["name_en"] or f"Type #{row['type_id']}",
                str(row["type_id"]),
                "",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, ("type", row["type_id"]))
            self.result_tree.addTopLevelItem(item)

        if not results:
            self.result_tree.addTopLevelItem(QTreeWidgetItem(["No results", "", ""]))

    def _on_item_selected(self, item: QTreeWidgetItem, column: int) -> None:
        """Show item details."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "type":
            return

        type_id = data[1]
        self._show_type_info(type_id)
        self._show_dogma(type_id)
        self._show_blueprint(type_id)
        self._show_reprocessing(type_id)

    def _show_type_info(self, type_id: int) -> None:
        """Show basic type info."""
        t = self.sde.get_type(type_id)
        if not t:
            self.info_label.setText(f"<p>Type #{type_id} not found.</p>")
            return

        group = self.sde.get_group(t.get("group_id", 0))
        group_name = group["name_en"] if group else "?"
        cat_name = self.sde.get_category_name(group["category_id"]) if group else "?"
        meta = self.sde.get_meta_group(t.get("meta_group_id")) if t.get("meta_group_id") else None

        html = f"<h2>{t.get('name_en', '?')}</h2>"
        html += "<table cellspacing='4'>"
        html += f"<tr><td><b>Type-ID:</b></td><td>{type_id}</td></tr>"
        html += f"<tr><td><b>Group:</b></td><td>{group_name}</td></tr>"
        html += f"<tr><td><b>Category:</b></td><td>{cat_name}</td></tr>"

        if t.get("mass"):
            html += f"<tr><td><b>Mass:</b></td><td>{t['mass']:,.0f} kg</td></tr>"
        if t.get("volume"):
            html += f"<tr><td><b>Volume:</b></td><td>{t['volume']:,.2f} m³</td></tr>"
        if t.get("base_price"):
            html += f"<tr><td><b>Base Price:</b></td><td>{t['base_price']:,.2f} ISK</td></tr>"
        if t.get("portion_size", 1) > 1:
            html += f"<tr><td><b>Portion Size:</b></td><td>{t['portion_size']}</td></tr>"
        if meta:
            html += f"<tr><td><b>Meta Group:</b></td><td>{meta.get('name_en', '?')}</td></tr>"

        market_group = self.sde.get_market_group(t.get("market_group_id", 0))
        if market_group:
            html += f"<tr><td><b>Market Group:</b></td><td>{market_group.get('name_en', '?')}</td></tr>"

        html += "</table>"

        desc = t.get("description_en", "")
        if desc:
            html += f"<h3>Beschreibung</h3><p style='color:{Colors.TEXT_DIM}'>{desc[:500]}</p>"

        # Traits (role/type bonuses)
        role_bonuses = self.sde.get_type_role_bonuses(type_id)
        trait_bonuses = self.sde.get_type_trait_bonuses(type_id)
        if role_bonuses or trait_bonuses:
            html += "<h3>Bonuses</h3>"
            if role_bonuses:
                html += "<h4>Role Bonuses</h4><ul>"
                for b in role_bonuses:
                    html += f"<li>{b.get('bonus_text_en', '?')}</li>"
                html += "</ul>"
            if trait_bonuses:
                html += "<h4>Skill Bonuses</h4><ul>"
                for b in trait_bonuses:
                    html += f"<li>{b.get('bonus_text_en', '?')}</li>"
                html += "</ul>"

        self.info_label.setText(html)

    def _show_dogma(self, type_id: int) -> None:
        """Show dogma attributes for a type."""
        attrs = self.sde.get_type_dogma_attributes(type_id)
        effects = self.sde.get_type_dogma_effects(type_id)

        if not attrs and not effects:
            self.dogma_label.setText("<p>No Dogma attributes.</p>")
            return

        html = f"<h3>Dogma Attributes ({len(attrs)})</h3>"
        html += "<table cellspacing='2'>"
        html += "<tr><th>Attribute</th><th>Value</th></tr>"
        for a in sorted(attrs, key=lambda x: x.get("name", "")):
            attr_name = a.get("name", f"#{a['attribute_id']}")
            display = self.sde.get_dogma_attribute(a["attribute_id"])
            if display and display.get("display_name_en"):
                attr_name = display["display_name_en"]
            unit = ""
            if display and display.get("unit_id"):
                unit_info = self.sde.get_dogma_unit(display["unit_id"])
                if unit_info:
                    unit = f" {unit_info.get('display_name', unit_info.get('name', ''))}"
            html += f"<tr><td>{attr_name}</td><td>{a['value']:g}{unit}</td></tr>"
        html += "</table>"

        if effects:
            html += f"<h3>Dogma Effects ({len(effects)})</h3><ul>"
            for e in effects:
                eff = self.sde.get_dogma_effect(e["effect_id"])
                eff_name = eff.get("display_name_en", eff.get("name", f"#{e['effect_id']}")) if eff else f"#{e['effect_id']}"
                html += f"<li>{eff_name}</li>"
            html += "</ul>"

        self.dogma_label.setText(html)

    def _show_blueprint(self, type_id: int) -> None:
        """Show blueprint info."""
        # Check if this IS a blueprint
        bp = self.sde.get_blueprint(type_id)
        if not bp:
            # Check if a blueprint exists that PRODUCES this item
            bp_info = self.sde.get_blueprint_for_product(type_id)
            if bp_info:
                bp = self.sde.get_blueprint(bp_info["type_id"])
                if bp:
                    type_id = bp_info["type_id"]

        if not bp:
            self.bp_label.setText("<p>No associated Blueprint.</p>")
            return

        bp_name = self.sde.get_type_name(type_id) or f"Blueprint #{type_id}"
        html = f"<h3>{bp_name}</h3><table cellspacing='4'>"
        html += f"<tr><td><b>Max Runs:</b></td><td>{bp.get('max_production_limit', '?')}</td></tr>"

        for key, label in [("manufacturing_time", "Manufacturing Time"),
                           ("research_material_time", "ME Research Time"),
                           ("research_time_time", "TE Research Time"),
                           ("copying_time", "Copying Time"),
                           ("invention_time", "Invention Time")]:
            val = bp.get(key)
            if val:
                minutes = val // 60
                html += f"<tr><td><b>{label}:</b></td><td>{minutes:,} min</td></tr>"
        html += "</table>"

        # Materials
        materials = self.sde.get_blueprint_materials(type_id)
        if materials:
            html += "<h4>Materials</h4><table>"
            html += "<tr><th>Material</th><th>Quantity</th></tr>"
            for m in materials:
                mat_name = self.sde.get_type_name(m["material_type_id"]) or f"#{m['material_type_id']}"
                html += f"<tr><td>{mat_name}</td><td>{m['quantity']:,}</td></tr>"
            html += "</table>"

        # Products
        products = self.sde.get_blueprint_products(type_id)
        if products:
            html += "<h4>Products</h4><table>"
            html += "<tr><th>Product</th><th>Quantity</th></tr>"
            for p in products:
                prod_name = self.sde.get_type_name(p["product_type_id"]) or f"#{p['product_type_id']}"
                html += f"<tr><td>{prod_name}</td><td>{p['quantity']:,}</td></tr>"
            html += "</table>"

        # Invention
        inv = self.sde.get_blueprint_invention_products(type_id)
        if inv:
            html += "<h4>Invention</h4><table>"
            html += "<tr><th>Blueprint</th><th>Quantity</th><th>Chance</th></tr>"
            for i in inv:
                inv_name = self.sde.get_type_name(i["product_type_id"]) or f"#{i['product_type_id']}"
                chance = i.get("probability", 0) * 100
                html += f"<tr><td>{inv_name}</td><td>{i['quantity']}</td><td>{chance:.0f}%</td></tr>"
            html += "</table>"

        self.bp_label.setText(html)

    def _show_reprocessing(self, type_id: int) -> None:
        """Show reprocessing materials."""
        materials = self.sde.get_type_materials(type_id)
        if not materials:
            self.repro_label.setText("<p>Not reprocessable.</p>")
            return

        html = "<h3>Reprocessing</h3><table>"
        html += "<tr><th>Material</th><th>Quantity</th></tr>"
        for m in materials:
            mat_name = self.sde.get_type_name(m["material_type_id"]) or f"#{m['material_type_id']}"
            html += f"<tr><td>{mat_name}</td><td>{m['quantity']:,}</td></tr>"
        html += "</table>"

        self.repro_label.setText(html)
