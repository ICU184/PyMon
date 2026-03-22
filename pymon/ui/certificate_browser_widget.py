"""Certificate & Mastery Browser widget for PyMon.

Shows EVE Online certificates grouped by category, with skill requirements
mapped against the character's trained skills. Also shows ship mastery levels.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
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

# Mastery level names & colors (EVE uses 5 levels: 0-4)
MASTERY_LEVELS = ["Basic", "Standard", "Improved", "Advanced", "Elite"]
MASTERY_COLORS = [Colors.TEXT_DIM, Colors.ACCENT, Colors.BLUE, Colors.GOLD, Colors.RED]
MASTERY_ICONS = ["◇", "◈", "◆", "★", "✦"]


class CertificateBrowserWidget(QWidget):
    """Certificate & Mastery Browser with dual-pane layout."""

    def __init__(self, sde: SDEDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sde = sde
        self._trained_skills: dict[int, int] = {}  # type_id -> level
        self._character_id: int | None = None

        self._setup_ui()

    # ══════════════════════════════════════════════════════════
    #  UI SETUP
    # ══════════════════════════════════════════════════════════

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Sub-tabs: Certificates | Ship Masteries ──
        self.sub_tabs = QTabWidget()

        # --- Tab 1: Certificates ---
        cert_widget = QWidget()
        cert_layout = QVBoxLayout(cert_widget)
        cert_layout.setContentsMargins(4, 4, 4, 4)

        # Filter bar
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Group:"))
        self.group_combo = QComboBox()
        self.group_combo.setMinimumWidth(200)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        filter_bar.addWidget(self.group_combo)

        filter_bar.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search certificate...")
        self.search_edit.textChanged.connect(self._on_search_changed)
        filter_bar.addWidget(self.search_edit)
        filter_bar.addStretch()
        cert_layout.addLayout(filter_bar)

        # Splitter: left = cert list, right = cert detail
        cert_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: certificate tree
        self.cert_tree = QTreeWidget()
        self.cert_tree.setHeaderLabels(["Certificate", "Status"])
        self.cert_tree.setColumnWidth(0, 300)
        self.cert_tree.setAlternatingRowColors(True)
        self.cert_tree.setFont(QFont("Segoe UI", 10))
        self.cert_tree.currentItemChanged.connect(self._on_cert_selected)
        cert_splitter.addWidget(self.cert_tree)

        # Right: certificate detail
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        self.cert_detail_label = QLabel("Select a certificate from the list.")
        self.cert_detail_label.setTextFormat(Qt.TextFormat.RichText)
        self.cert_detail_label.setWordWrap(True)
        self.cert_detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cert_detail_label.setContentsMargins(12, 12, 12, 12)
        self.cert_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_scroll.setWidget(self.cert_detail_label)
        cert_splitter.addWidget(detail_scroll)

        cert_splitter.setStretchFactor(0, 1)
        cert_splitter.setStretchFactor(1, 2)
        cert_layout.addWidget(cert_splitter)

        self.sub_tabs.addTab(cert_widget, "📜 Certificates")

        # --- Tab 2: Ship Masteries ---
        mastery_widget = QWidget()
        mastery_layout = QVBoxLayout(mastery_widget)
        mastery_layout.setContentsMargins(4, 4, 4, 4)

        # Filter bar for masteries
        m_filter_bar = QHBoxLayout()
        m_filter_bar.addWidget(QLabel("Search:"))
        self.ship_search_edit = QLineEdit()
        self.ship_search_edit.setPlaceholderText("Search ship...")
        self.ship_search_edit.textChanged.connect(self._on_ship_search_changed)
        m_filter_bar.addWidget(self.ship_search_edit)
        m_filter_bar.addStretch()
        mastery_layout.addLayout(m_filter_bar)

        # Splitter: left = ship list, right = mastery detail
        mastery_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.ship_tree = QTreeWidget()
        self.ship_tree.setHeaderLabels(["Ship", "Mastery"])
        self.ship_tree.setColumnWidth(0, 300)
        self.ship_tree.setAlternatingRowColors(True)
        self.ship_tree.setFont(QFont("Segoe UI", 10))
        self.ship_tree.currentItemChanged.connect(self._on_ship_selected)
        mastery_splitter.addWidget(self.ship_tree)

        m_detail_scroll = QScrollArea()
        m_detail_scroll.setWidgetResizable(True)
        self.mastery_detail_label = QLabel("Select a ship from the list.")
        self.mastery_detail_label.setTextFormat(Qt.TextFormat.RichText)
        self.mastery_detail_label.setWordWrap(True)
        self.mastery_detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.mastery_detail_label.setContentsMargins(12, 12, 12, 12)
        self.mastery_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        m_detail_scroll.setWidget(self.mastery_detail_label)
        mastery_splitter.addWidget(m_detail_scroll)

        mastery_splitter.setStretchFactor(0, 1)
        mastery_splitter.setStretchFactor(1, 2)
        mastery_layout.addWidget(mastery_splitter)

        self.sub_tabs.addTab(mastery_widget, "🚀 Ship Masteries")

        layout.addWidget(self.sub_tabs)

    # ══════════════════════════════════════════════════════════
    #  DATA UPDATE
    # ══════════════════════════════════════════════════════════

    def set_character_data(
        self,
        trained_skills: dict[int, int] | None = None,
        character_id: int | None = None,
    ) -> None:
        """Update character skill data and refresh the browser."""
        if trained_skills is not None:
            self._trained_skills = trained_skills
        self._character_id = character_id
        self._load_certificate_groups()
        self._load_ship_masteries()

    # ══════════════════════════════════════════════════════════
    #  CERTIFICATES TAB
    # ══════════════════════════════════════════════════════════

    def _load_certificate_groups(self) -> None:
        """Load certificate groups into the combo box."""
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("── All Groups ──", 0)

        try:
            groups = self.sde.get_certificate_groups()
            for g in groups:
                name = g.get("group_name") or f"Group #{g['group_id']}"
                self.group_combo.addItem(name, g["group_id"])
        except Exception:
            logger.debug("Could not load certificate groups", exc_info=True)

        self.group_combo.blockSignals(False)
        self._refresh_cert_tree()

    def _on_group_changed(self, _index: int) -> None:
        self._refresh_cert_tree()

    def _on_search_changed(self, _text: str) -> None:
        self._refresh_cert_tree()

    def _refresh_cert_tree(self) -> None:
        """Reload the certificate tree based on current filters."""
        self.cert_tree.clear()
        group_id = self.group_combo.currentData()
        search_text = self.search_edit.text().strip().lower()

        try:
            if group_id and group_id != 0:
                certs = self.sde.get_certificates_by_group(group_id)
            else:
                certs = self.sde.get_all_certificates()
        except Exception:
            logger.debug("Could not load certificates", exc_info=True)
            return

        for cert in certs:
            name = cert.get("name_en", "")
            if search_text and search_text not in name.lower():
                continue

            cert_id = cert["certificate_id"]
            status = self._get_cert_mastery_status(cert_id)
            item = QTreeWidgetItem([name, status])
            item.setData(0, Qt.ItemDataRole.UserRole, cert_id)

            # Color the status column
            if "Elite" in status:
                item.setForeground(1, QColor(MASTERY_COLORS[4]))
            elif "Advanced" in status:
                item.setForeground(1, QColor(MASTERY_COLORS[3]))
            elif "Improved" in status:
                item.setForeground(1, QColor(MASTERY_COLORS[2]))
            elif "Standard" in status:
                item.setForeground(1, QColor(MASTERY_COLORS[1]))
            elif "Basic" in status:
                item.setForeground(1, QColor(MASTERY_COLORS[0]))

            self.cert_tree.addTopLevelItem(item)

    def _get_cert_mastery_status(self, cert_id: int) -> str:
        """Determine the highest mastery level the character qualifies for."""
        if not self._trained_skills:
            return "—"

        try:
            skills = self.sde.get_certificate_skills(cert_id)
        except Exception:
            return "?"

        if not skills:
            return "—"

        # Check each level from highest (elite=4) to lowest (basic=0)
        level_keys = ["basic", "standard", "improved", "advanced", "elite"]
        highest_met = -1

        for lvl_idx, lvl_name in enumerate(level_keys):
            all_met = True
            for sk in skills:
                required = sk.get(lvl_name, 0) or 0
                if required <= 0:
                    continue
                trained = self._trained_skills.get(sk["skill_type_id"], 0)
                if trained < required:
                    all_met = False
                    break
            if all_met:
                highest_met = lvl_idx

        if highest_met < 0:
            return "Not met"
        return f"{MASTERY_ICONS[highest_met]} {MASTERY_LEVELS[highest_met]}"

    def _on_cert_selected(self, current: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        cert_id = current.data(0, Qt.ItemDataRole.UserRole)
        if cert_id is None:
            return
        self._show_cert_detail(cert_id)

    def _show_cert_detail(self, cert_id: int) -> None:
        """Display full certificate detail with skill requirements."""
        cert = self.sde.get_certificate(cert_id)
        if not cert:
            self.cert_detail_label.setText("<p>Certificate not found.</p>")
            return

        name = cert.get("name_en", "Unknown")
        desc = cert.get("description_en", "") or ""

        html = (
            f"<h2>📜 {name}</h2>"
            f"<p style='color:{Colors.TEXT_DIM}'>{desc}</p>"
        )

        # Skill requirements table
        skills = self.sde.get_certificate_skills(cert_id)
        if skills:
            html += (
                "<h3>Skill Requirements</h3>"
                "<table cellspacing='4' style='margin-top:4px'>"
                "<tr><th style='text-align:left'>Skill</th>"
                "<th>Basic</th><th>Standard</th><th>Improved</th>"
                "<th>Advanced</th><th>Elite</th><th>Trained</th></tr>"
            )
            for sk in skills:
                skill_name = sk.get("skill_name", f"Skill #{sk['skill_type_id']}")
                trained = self._trained_skills.get(sk["skill_type_id"], 0)
                trained_color = Colors.ACCENT if trained > 0 else Colors.TEXT_DIM

                html += f"<tr><td><b>{skill_name}</b></td>"
                for lvl_name in ["basic", "standard", "improved", "advanced", "elite"]:
                    req = sk.get(lvl_name, 0) or 0
                    if req <= 0:
                        html += "<td style='text-align:center;color:{Colors.BORDER}'>—</td>"
                    elif trained >= req:
                        html += f"<td style='text-align:center;color:{Colors.ACCENT}'>✓ {req}</td>"
                    else:
                        html += f"<td style='text-align:center;color:{Colors.RED}'>✗ {req}</td>"
                html += f"<td style='text-align:center;color:{trained_color}'><b>{trained}</b></td></tr>"
            html += "</table>"

        # Recommended ships
        rec_types = self.sde.get_certificate_recommended_types(cert_id)
        if rec_types:
            html += "<h3>Recommended Ships</h3><p>"
            ship_names = [r.get("type_name", f"Type #{r['type_id']}") for r in rec_types]
            html += ", ".join(f"<span style='color:{Colors.BLUE}'>{s}</span>" for s in ship_names)
            html += "</p>"

        self.cert_detail_label.setText(html)

    # ══════════════════════════════════════════════════════════
    #  SHIP MASTERIES TAB
    # ══════════════════════════════════════════════════════════

    def _load_ship_masteries(self) -> None:
        """Load ships with masteries into the ship tree."""
        self.ship_tree.clear()
        try:
            ships = self.sde.get_ships_with_masteries()
        except Exception:
            logger.debug("Could not load ship masteries", exc_info=True)
            return

        # Group by ship group
        groups: dict[str, list[dict[str, Any]]] = {}
        for ship in ships:
            gname = ship.get("group_name") or "Unknown"
            groups.setdefault(gname, []).append(ship)

        for gname in sorted(groups.keys()):
            group_item = QTreeWidgetItem([gname, ""])
            group_item.setFont(0, QFont("Segoe UI", 10, QFont.Weight.Bold))
            group_item.setForeground(0, QColor(Colors.TEXT_DIM))

            for ship in groups[gname]:
                type_id = ship["type_id"]
                ship_name = ship.get("type_name") or f"Type #{type_id}"
                mastery_lvl = self._get_ship_mastery_level(type_id)
                child = QTreeWidgetItem([ship_name, mastery_lvl])
                child.setData(0, Qt.ItemDataRole.UserRole, type_id)

                # Color mastery level
                for i, lvl_name in enumerate(MASTERY_LEVELS):
                    if lvl_name in mastery_lvl:
                        child.setForeground(1, QColor(MASTERY_COLORS[i]))
                        break

                group_item.addChild(child)

            self.ship_tree.addTopLevelItem(group_item)

    def _on_ship_search_changed(self, text: str) -> None:
        """Filter ship tree based on search text."""
        search_text = text.strip().lower()
        for i in range(self.ship_tree.topLevelItemCount()):
            group_item = self.ship_tree.topLevelItem(i)
            if group_item is None:
                continue
            any_visible = False
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                if child is None:
                    continue
                visible = not search_text or search_text in child.text(0).lower()
                child.setHidden(not visible)
                if visible:
                    any_visible = True
            group_item.setHidden(not any_visible)
            if any_visible and search_text:
                group_item.setExpanded(True)

    def _get_ship_mastery_level(self, type_id: int) -> str:
        """Determine highest mastery level for a ship."""
        if not self._trained_skills:
            return "—"

        try:
            masteries = self.sde.get_ship_masteries(type_id)
        except Exception:
            return "?"

        if not masteries:
            return "—"

        # Group certificates by mastery level
        level_certs: dict[int, list[int]] = {}
        for m in masteries:
            lvl = m["mastery_level"]
            level_certs.setdefault(lvl, []).append(m["certificate_id"])

        highest_met = -1
        for lvl in range(5):
            cert_ids = level_certs.get(lvl, [])
            if not cert_ids:
                continue
            all_met = True
            for cert_id in cert_ids:
                if not self._check_certificate_met(cert_id, lvl):
                    all_met = False
                    break
            if all_met:
                highest_met = lvl
            else:
                break  # Can't skip levels

        if highest_met < 0:
            return "None"
        return f"{MASTERY_ICONS[highest_met]} {MASTERY_LEVELS[highest_met]}"

    def _check_certificate_met(self, cert_id: int, mastery_level: int) -> bool:
        """Check if character meets certificate requirements for a mastery level."""
        level_keys = ["basic", "standard", "improved", "advanced", "elite"]
        if mastery_level < 0 or mastery_level >= len(level_keys):
            return False

        lvl_name = level_keys[mastery_level]
        try:
            skills = self.sde.get_certificate_skills(cert_id)
        except Exception:
            return False

        for sk in skills:
            required = sk.get(lvl_name, 0) or 0
            if required <= 0:
                continue
            trained = self._trained_skills.get(sk["skill_type_id"], 0)
            if trained < required:
                return False
        return True

    def _on_ship_selected(self, current: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        type_id = current.data(0, Qt.ItemDataRole.UserRole)
        if type_id is None:
            return
        self._show_ship_mastery_detail(type_id)

    def _show_ship_mastery_detail(self, type_id: int) -> None:
        """Display mastery detail for a ship."""
        ship_name = self.sde.get_type_name(type_id)
        masteries = self.sde.get_ship_masteries(type_id)

        if not masteries:
            self.mastery_detail_label.setText(
                f"<h2>{ship_name}</h2><p>No mastery data available.</p>"
            )
            return

        html = f"<h2>🚀 {ship_name}</h2>"

        # Group by mastery level
        level_certs: dict[int, list[dict[str, Any]]] = {}
        for m in masteries:
            lvl = m["mastery_level"]
            level_certs.setdefault(lvl, []).append(m)

        for lvl in range(5):
            certs = level_certs.get(lvl, [])
            if not certs:
                continue

            color = MASTERY_COLORS[lvl]
            icon = MASTERY_ICONS[lvl]
            level_name = MASTERY_LEVELS[lvl]
            level_met = all(
                self._check_certificate_met(c["certificate_id"], lvl) for c in certs
            )
            status_icon = "✓" if level_met else "✗"
            status_color = Colors.ACCENT if level_met else Colors.RED

            html += (
                f"<h3 style='color:{color}'>{icon} {level_name} "
                f"<span style='color:{status_color}'>[{status_icon}]</span></h3>"
            )

            for cert_entry in certs:
                cert_id = cert_entry["certificate_id"]
                cert_name = cert_entry.get("cert_name") or f"Cert #{cert_id}"
                cert_met = self._check_certificate_met(cert_id, lvl)
                cert_color = Colors.ACCENT if cert_met else Colors.RED
                cert_icon = "✓" if cert_met else "✗"

                html += (
                    f"<div style='margin:4px 0 4px 16px;padding:6px 10px;"
                    f"background:#161b22;border-radius:4px;"
                    f"border-left:3px solid {cert_color}'>"
                    f"<b style='color:{cert_color}'>{cert_icon}</b> {cert_name}"
                )

                # Show required skills for this cert at this mastery level
                try:
                    skills = self.sde.get_certificate_skills(cert_id)
                except Exception:
                    skills = []

                level_keys = ["basic", "standard", "improved", "advanced", "elite"]
                lvl_key = level_keys[lvl]

                if skills:
                    html += "<div style='margin-top:4px;padding-left:8px'>"
                    for sk in skills:
                        req = sk.get(lvl_key, 0) or 0
                        if req <= 0:
                            continue
                        sk_name = sk.get("skill_name", f"Skill #{sk['skill_type_id']}")
                        trained = self._trained_skills.get(sk["skill_type_id"], 0)
                        if trained >= req:
                            sk_color = Colors.ACCENT
                            sk_icon = "✓"
                        else:
                            sk_color = Colors.RED
                            sk_icon = "✗"
                        html += (
                            f"<span style='color:{sk_color}'>{sk_icon}</span> "
                            f"{sk_name} "
                            f"<span style='color:{Colors.TEXT_DIM}'>Lv{req}</span> "
                            f"(trained: <span style='color:{sk_color}'>{trained}</span>)&nbsp;&nbsp;"
                        )
                    html += "</div>"

                html += "</div>"

        self.mastery_detail_label.setText(html)
