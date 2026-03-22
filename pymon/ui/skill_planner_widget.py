"""Skill Planner UI widget.

Provides a skill browser (all SDE skills grouped), training time
calculator, plan management with persistence (save/load), and
import/export of plans as JSON files.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.core.database import Database
from pymon.sde.database import SDEDatabase
from pymon.services.skill_planner import (
    PlanEntry,
    SkillPlan,
    SkillPlanner,
    format_training_time,
)
from pymon.ui.attribute_optimizer_widget import AttributeOptimizerWidget
from pymon.ui.dark_theme import Colors
from pymon.ui.loadout_import_dialog import LoadoutImportDialog

logger = logging.getLogger(__name__)


class SkillPlannerWidget(QWidget):
    """Skill Planner tab widget."""

    def __init__(
        self,
        sde: SDEDatabase,
        db: Database | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.sde = sde
        self.db = db
        self.planner = SkillPlanner(sde)

        # Character state (set via set_character_data)
        self._attributes: dict[str, int] = {
            "intelligence": 17, "memory": 17,
            "perception": 17, "willpower": 17, "charisma": 17,
        }
        self._trained_skills: dict[int, int] = {}  # type_id → level
        self._character_id: int | None = None

        # Current plan
        self._plan = SkillPlan(name="New Plan")
        self._plan_dirty = False  # unsaved changes?

        self._setup_ui()

    def set_character_data(
        self,
        attributes: dict[str, int],
        trained_skills: dict[int, int],
        character_id: int | None = None,
    ) -> None:
        """Update character attributes and trained skills."""
        self._attributes = attributes
        self._trained_skills = trained_skills
        if character_id is not None:
            old_id = self._character_id
            self._character_id = character_id
            if old_id != character_id:
                self._refresh_plan_list()
        self._refresh_plan_times()
        self._update_skill_tree_icons()
        # Feed data to Attribute Optimizer
        self.attr_optimizer.set_character_data(attributes, trained_skills)
        self.attr_optimizer.set_plan(self._plan)

    # ──────────────────────────────────────────────────────────────
    #  UI Setup
    # ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Skill Browser ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Search
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search skill...")
        self.search_input.textChanged.connect(self._on_search)
        search_layout.addWidget(self.search_input)
        left_layout.addLayout(search_layout)

        # Skill tree
        self.skill_tree = QTreeWidget()
        self.skill_tree.setHeaderLabels(["Skill", "Rank", "Primary", "Secondary"])
        self.skill_tree.setAlternatingRowColors(True)
        self.skill_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.skill_tree.itemClicked.connect(self._on_skill_selected)
        self.skill_tree.itemDoubleClicked.connect(self._on_skill_add)
        left_layout.addWidget(self.skill_tree)

        splitter.addWidget(left)

        # ── Right: Plan + Details (in tabs) ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Skill details (always visible above tabs)
        self.detail_group = QGroupBox("Skill Details")
        detail_layout = QVBoxLayout(self.detail_group)
        self.detail_label = QLabel("Select a skill from the list on the left.")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.TextFormat.RichText)
        detail_layout.addWidget(self.detail_label)

        # Add-to-plan buttons
        btn_layout = QHBoxLayout()
        for level in range(1, 6):
            btn = QPushButton(f"Add Level {level} to plan")
            btn.clicked.connect(partial(self._add_to_plan, level))
            btn_layout.addWidget(btn)
        detail_layout.addLayout(btn_layout)
        right_layout.addWidget(self.detail_group)

        # Tab widget for Plan and Optimizer
        self.right_tabs = QTabWidget()

        # ── Tab 1: Plan ──
        plan_widget = QWidget()
        plan_group_layout = QVBoxLayout(plan_widget)
        plan_group_layout.setContentsMargins(4, 4, 4, 4)

        # Plan selector row
        plan_selector = QHBoxLayout()
        plan_selector.addWidget(QLabel("Plan:"))
        self.plan_combo = QComboBox()
        self.plan_combo.setMinimumWidth(180)
        self.plan_combo.setEditable(False)
        self.plan_combo.addItem("New Plan")
        self.plan_combo.currentTextChanged.connect(self._on_plan_selected)
        plan_selector.addWidget(self.plan_combo, stretch=1)

        self.new_plan_btn = QPushButton("➕ New")
        self.new_plan_btn.setToolTip("Create new plan")
        self.new_plan_btn.clicked.connect(self._new_plan)
        plan_selector.addWidget(self.new_plan_btn)

        self.save_plan_btn = QPushButton("💾 Save")
        self.save_plan_btn.setToolTip("Save plan to DB")
        self.save_plan_btn.clicked.connect(self._save_plan)
        plan_selector.addWidget(self.save_plan_btn)

        self.delete_plan_btn = QPushButton("🗑️ Delete")
        self.delete_plan_btn.setToolTip("Delete plan from DB")
        self.delete_plan_btn.clicked.connect(self._delete_plan)
        plan_selector.addWidget(self.delete_plan_btn)

        plan_group_layout.addLayout(plan_selector)

        # Plan name + total row
        plan_header = QHBoxLayout()
        plan_header.addWidget(QLabel("Name:"))
        self.plan_name_input = QLineEdit(self._plan.name)
        self.plan_name_input.textChanged.connect(self._on_plan_name_changed)
        plan_header.addWidget(self.plan_name_input)
        self.plan_total_label = QLabel("")
        self.plan_total_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        plan_header.addWidget(self.plan_total_label)
        plan_group_layout.addLayout(plan_header)

        # Plan tree
        self.plan_tree = QTreeWidget()
        self.plan_tree.setHeaderLabels([
            "Skill", "Level", "Training Time", "Cumulative", "Status"
        ])
        self.plan_tree.setAlternatingRowColors(True)
        self.plan_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        plan_group_layout.addWidget(self.plan_tree)

        # Plan buttons
        plan_btns = QHBoxLayout()
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_from_plan)
        plan_btns.addWidget(self.remove_btn)
        self.move_up_btn = QPushButton("↑")
        self.move_up_btn.clicked.connect(self._move_up)
        plan_btns.addWidget(self.move_up_btn)
        self.move_down_btn = QPushButton("↓")
        self.move_down_btn.clicked.connect(self._move_down)
        plan_btns.addWidget(self.move_down_btn)
        self.clear_btn = QPushButton("Clear plan")
        self.clear_btn.clicked.connect(self._clear_plan)
        plan_btns.addWidget(self.clear_btn)
        plan_btns.addStretch()
        self.export_btn = QPushButton("📤 Export")
        self.export_btn.setToolTip("Export plan as JSON")
        self.export_btn.clicked.connect(self._export_plan)
        plan_btns.addWidget(self.export_btn)
        self.import_btn = QPushButton("📥 Import")
        self.import_btn.setToolTip("Import plan from JSON")
        self.import_btn.clicked.connect(self._import_plan)
        plan_btns.addWidget(self.import_btn)
        self.eft_import_btn = QPushButton("🚀 EFT Import")
        self.eft_import_btn.setToolTip("Import fitting (EFT format) → required skills")
        self.eft_import_btn.clicked.connect(self._import_eft)
        plan_btns.addWidget(self.eft_import_btn)
        self.print_btn = QPushButton("🖨️ Print")
        self.print_btn.setToolTip("Print plan or save as PDF")
        self.print_btn.clicked.connect(self._print_plan)
        plan_btns.addWidget(self.print_btn)
        plan_group_layout.addLayout(plan_btns)

        self.right_tabs.addTab(plan_widget, "📋 Skill Plan")

        # ── Tab 2: Attribute Optimizer ──
        self.attr_optimizer = AttributeOptimizerWidget(self.planner)
        self.right_tabs.addTab(self.attr_optimizer, "🧠 Attribute Optimizer")

        right_layout.addWidget(self.right_tabs, stretch=1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        # Load skill tree
        self._populate_skill_tree()

    # ──────────────────────────────────────────────────────────────
    #  Skill Browser
    # ──────────────────────────────────────────────────────────────

    def _populate_skill_tree(self) -> None:
        """Populate the skill browser tree from SDE."""
        self.skill_tree.clear()
        groups = self.planner.get_skill_groups()

        for group_name in sorted(groups):
            group_item = QTreeWidgetItem([f"{group_name} ({len(groups[group_name])})", "", "", ""])
            group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)

            for skill in sorted(groups[group_name], key=lambda s: s.name):
                child = QTreeWidgetItem([
                    skill.name,
                    str(int(skill.rank)),
                    skill.primary_attr.title(),
                    skill.secondary_attr.title(),
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, skill.type_id)

                # Show trained level indicator
                level = self._trained_skills.get(skill.type_id, 0)
                if level > 0:
                    bars = "●" * level + "○" * (5 - level)
                    child.setText(0, f"{skill.name}  [{bars}]")

                group_item.addChild(child)

            self.skill_tree.addTopLevelItem(group_item)

    def _update_skill_tree_icons(self) -> None:
        """Update trained level indicators in skill tree."""
        for gi in range(self.skill_tree.topLevelItemCount()):
            group_item = self.skill_tree.topLevelItem(gi)
            if not group_item:
                continue
            for ci in range(group_item.childCount()):
                child = group_item.child(ci)
                if not child:
                    continue
                type_id = child.data(0, Qt.ItemDataRole.UserRole)
                info = self.planner.get_skill_info(type_id) if type_id else None
                if not info:
                    continue
                level = self._trained_skills.get(type_id, 0)
                if level > 0:
                    bars = "●" * level + "○" * (5 - level)
                    child.setText(0, f"{info.name}  [{bars}]")
                else:
                    child.setText(0, info.name)

    def _on_search(self, text: str) -> None:
        """Filter skill tree by search text."""
        search = text.lower().strip()
        for gi in range(self.skill_tree.topLevelItemCount()):
            group_item = self.skill_tree.topLevelItem(gi)
            if not group_item:
                continue
            visible_children = 0
            for ci in range(group_item.childCount()):
                child = group_item.child(ci)
                if not child:
                    continue
                match = not search or search in child.text(0).lower()
                child.setHidden(not match)
                if match:
                    visible_children += 1
            group_item.setHidden(visible_children == 0)
            if visible_children > 0 and search:
                group_item.setExpanded(True)

    def _on_skill_selected(self, item: QTreeWidgetItem, column: int) -> None:
        """Show skill details."""
        type_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not type_id:
            return
        info = self.planner.get_skill_info(type_id)
        if not info:
            return

        current_level = self._trained_skills.get(type_id, 0)
        bars = "●" * current_level + "○" * (5 - current_level)

        html = f"<h3>{info.name}</h3>"
        html += f"<p>Rank: {int(info.rank)} | Primary: {info.primary_attr.title()} | Secondary: {info.secondary_attr.title()}</p>"
        html += f"<p>Trained: <b>{bars}</b> (Level {current_level})</p>"

        if info.description:
            desc = info.description[:300]
            html += f"<p style='color:{Colors.TEXT_DIM}'>{desc}</p>"

        # Training times per level
        html += "<h4>Training Times</h4><table cellspacing='4'>"
        for lvl in range(1, 6):
            if lvl <= current_level:
                html += f"<tr><td>Level {lvl}:</td><td style='color:{Colors.ACCENT}'>✓ Trained</td></tr>"
            else:
                t = self.planner.calculate_training_time(
                    type_id, max(current_level, lvl - 1), lvl, self._attributes
                )
                html += f"<tr><td>Level {lvl}:</td><td>{format_training_time(t)}</td></tr>"
        html += "</table>"

        # Prerequisites
        prereqs = self.planner.get_prerequisites_tree(type_id)
        if prereqs:
            html += "<h4>Prerequisites</h4><ul>"
            for pid, pname, plevel in prereqs:
                trained = self._trained_skills.get(pid, 0)
                icon = "✓" if trained >= plevel else "✗"
                color = Colors.ACCENT if trained >= plevel else Colors.RED
                html += f"<li style='color:{color}'>{icon} {pname} Level {plevel}</li>"
            html += "</ul>"

        # Skill Explorer: What does this skill unlock?
        try:
            unlocked = self.sde.get_types_requiring_skill(type_id)
            if unlocked:
                # Group by category
                by_cat: dict[str, list] = {}
                for item_data in unlocked:
                    cat = item_data.get("category_name") or "Unknown"
                    by_cat.setdefault(cat, []).append(item_data)

                cat_icons = {
                    "Ship": "🚀", "Module": "⚙️", "Charge": "💥",
                    "Drone": "🐝", "Skill": "📚", "Implant": "💉",
                    "Blueprint": "📘", "Subsystem": "🔧", "Structure": "🏗️",
                    "Fighter": "✈️", "Deployable": "📡", "Celestial": "🌟",
                    "Starbase": "🛸",
                }

                html += f"<h4>🔓 Enables ({len(unlocked)} items)</h4>"
                for cat_name in sorted(by_cat):
                    items_in_cat = by_cat[cat_name]
                    icon = cat_icons.get(cat_name, "📦")
                    html += f"<p><b>{icon} {cat_name}</b> ({len(items_in_cat)})</p><ul>"
                    # Show first 15 per category, then "..."
                    for item_data in items_in_cat[:15]:
                        req_lvl = int(item_data.get("required_level") or 0)
                        lvl_roman = ["", "I", "II", "III", "IV", "V"][min(req_lvl, 5)] if req_lvl else ""
                        grp = item_data.get("group_name", "")
                        html += (
                            f"<li>{item_data.get('type_name', '?')}"
                            f" <span style='color:{Colors.TEXT_DIM}'>({grp})</span>"
                            f" <span style='color:{Colors.BLUE}'>Lvl {lvl_roman}</span></li>"
                        )
                    if len(items_in_cat) > 15:
                        html += f"<li style='color:{Colors.TEXT_DIM}'><i>...and {len(items_in_cat) - 15} more</i></li>"
                    html += "</ul>"
        except Exception:
            pass  # SDE Explorer is optional

        self.detail_label.setText(html)
        self._selected_type_id = type_id

    def _on_skill_add(self, item: QTreeWidgetItem, column: int) -> None:
        """Double-click: add skill to next unlearned level."""
        type_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not type_id:
            return
        current = self._trained_skills.get(type_id, 0)
        # Find max level already in plan
        max_planned = current
        for entry in self._plan.entries:
            if entry.type_id == type_id:
                max_planned = max(max_planned, entry.target_level)
        next_level = min(max_planned + 1, 5)
        if next_level <= 5:
            self._add_to_plan(next_level)

    # ──────────────────────────────────────────────────────────────
    #  Plan Management
    # ──────────────────────────────────────────────────────────────

    _selected_type_id: int | None = None

    def _add_to_plan(self, level: int) -> None:
        """Add the selected skill at given level to the plan."""
        if not self._selected_type_id:
            return
        info = self.planner.get_skill_info(self._selected_type_id)
        if not info:
            return

        # Check if already in plan at same or higher level
        for entry in self._plan.entries:
            if entry.type_id == self._selected_type_id and entry.target_level >= level:
                return

        # Remove lower level entry if exists
        self._plan.entries = [
            e for e in self._plan.entries
            if not (e.type_id == self._selected_type_id and e.target_level < level)
        ]

        # Auto-add prerequisites if missing
        prereqs = self.planner.get_prerequisites_tree(self._selected_type_id, level)
        for pid, pname, plevel in prereqs:
            trained = self._trained_skills.get(pid, 0)
            already_planned = any(
                e.type_id == pid and e.target_level >= plevel
                for e in self._plan.entries
            )
            if trained < plevel and not already_planned:
                entry = PlanEntry(
                    type_id=pid,
                    skill_name=pname,
                    target_level=plevel,
                )
                self._plan.entries.append(entry)

        entry = PlanEntry(
            type_id=self._selected_type_id,
            skill_name=info.name,
            target_level=level,
        )
        self._plan.entries.append(entry)

        self._plan_dirty = True
        self._refresh_plan_times()
        self._update_plan_tree()

    def _remove_from_plan(self) -> None:
        """Remove selected entry from plan."""
        item = self.plan_tree.currentItem()
        if not item:
            return
        idx = self.plan_tree.indexOfTopLevelItem(item)
        if 0 <= idx < len(self._plan.entries):
            self._plan.entries.pop(idx)
            self._plan_dirty = True
            self._refresh_plan_times()
            self._update_plan_tree()

    def _move_up(self) -> None:
        """Move selected plan entry up."""
        item = self.plan_tree.currentItem()
        if not item:
            return
        idx = self.plan_tree.indexOfTopLevelItem(item)
        if idx > 0:
            self._plan.entries[idx], self._plan.entries[idx - 1] = (
                self._plan.entries[idx - 1], self._plan.entries[idx]
            )
            self._update_plan_tree()
            self.plan_tree.setCurrentItem(self.plan_tree.topLevelItem(idx - 1))

    def _move_down(self) -> None:
        """Move selected plan entry down."""
        item = self.plan_tree.currentItem()
        if not item:
            return
        idx = self.plan_tree.indexOfTopLevelItem(item)
        if idx < len(self._plan.entries) - 1:
            self._plan.entries[idx], self._plan.entries[idx + 1] = (
                self._plan.entries[idx + 1], self._plan.entries[idx]
            )
            self._update_plan_tree()
            self.plan_tree.setCurrentItem(self.plan_tree.topLevelItem(idx + 1))

    def _clear_plan(self) -> None:
        """Clear the entire plan."""
        if self._plan.entries:
            reply = QMessageBox.question(
                self, "Clear plan",
                f"Remove all {len(self._plan.entries)} entries from the plan?"
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._plan.entries.clear()
        self._plan_dirty = True
        self._update_plan_tree()

    def _on_plan_name_changed(self, text: str) -> None:
        self._plan.name = text
        self._plan_dirty = True

    def _refresh_plan_times(self) -> None:
        """Recalculate all training times."""
        self.planner.calculate_plan_times(
            self._plan, self._attributes, self._trained_skills
        )

    def _update_plan_tree(self) -> None:
        """Refresh plan tree display."""
        self.plan_tree.clear()
        cumulative = 0.0

        for entry in self._plan.entries:
            cumulative += entry.training_time_seconds
            level_str = f"{'I' * entry.target_level}" if entry.target_level <= 3 else (
                "IV" if entry.target_level == 4 else "V"
            )

            status = ""
            if entry.current_level >= entry.target_level:
                status = "✓ Trained"
            elif entry.training_time_seconds <= 0:
                status = "✓ Done"

            item = QTreeWidgetItem([
                entry.skill_name,
                level_str,
                format_training_time(entry.training_time_seconds),
                format_training_time(cumulative),
                status,
            ])
            if entry.current_level >= entry.target_level:
                for col in range(5):
                    item.setForeground(col, Qt.GlobalColor.darkGreen)

            self.plan_tree.addTopLevelItem(item)

        # Update total
        total = self._plan.total_time_display
        self.plan_total_label.setText(f"Total: {total} ({len(self._plan.entries)} skills)")

        # Sync plan to Attribute Optimizer
        self.attr_optimizer.set_plan(self._plan)

    # ──────────────────────────────────────────────────────────────
    #  Plan Persistence (DB)
    # ──────────────────────────────────────────────────────────────

    def _refresh_plan_list(self) -> None:
        """Refresh the plan ComboBox from DB."""
        self.plan_combo.blockSignals(True)
        self.plan_combo.clear()
        self.plan_combo.addItem("New Plan")

        if self.db and self._character_id:
            plans = self.db.list_skill_plans(self._character_id)
            for p in plans:
                label = f"{p['name']} ({p['entry_count']} Skills)"
                self.plan_combo.addItem(label, userData=p["name"])

        self.plan_combo.blockSignals(False)

    def _on_plan_selected(self, text: str) -> None:
        """Handle plan selection from ComboBox."""
        if not text:
            return

        idx = self.plan_combo.currentIndex()
        if idx == 0:
            # "New Plan" selected
            return

        plan_name = self.plan_combo.currentData()
        if plan_name and self.db and self._character_id:
            self._load_plan_from_db(plan_name)

    def _load_plan_from_db(self, plan_name: str) -> None:
        """Load a plan from DB."""
        if not self.db or not self._character_id:
            return

        entries_data = self.db.load_skill_plan(self._character_id, plan_name)
        if entries_data is None:
            return

        self._plan = SkillPlan(name=plan_name)
        for e in entries_data:
            self._plan.entries.append(PlanEntry(
                type_id=e["type_id"],
                skill_name=e["skill_name"],
                target_level=e["target_level"],
                notes=e.get("notes", ""),
            ))

        self.plan_name_input.blockSignals(True)
        self.plan_name_input.setText(plan_name)
        self.plan_name_input.blockSignals(False)

        self._plan_dirty = False
        self._refresh_plan_times()
        self._update_plan_tree()
        logger.info("Loaded plan '%s' with %d entries",
                     plan_name, len(self._plan.entries))

    def _save_plan(self) -> None:
        """Save current plan to DB."""
        if not self.db or not self._character_id:
            QMessageBox.warning(
                self, "Save",
                "No character logged in. Please log in first.",
            )
            return

        name = self._plan.name.strip()
        if not name or name == "New Plan":
            name, ok = QInputDialog.getText(
                self, "Save Plan",
                "Name for the plan:",
                text=self._plan.name if self._plan.name != "New Plan" else "",
            )
            if not ok or not name.strip():
                return
            name = name.strip()
            self._plan.name = name
            self.plan_name_input.blockSignals(True)
            self.plan_name_input.setText(name)
            self.plan_name_input.blockSignals(False)

        entries = [
            {
                "type_id": e.type_id,
                "skill_name": e.skill_name,
                "target_level": e.target_level,
                "notes": e.notes,
            }
            for e in self._plan.entries
        ]

        self.db.save_skill_plan(self._character_id, name, entries)
        self._plan_dirty = False
        self._refresh_plan_list()

        # Select saved plan in combo
        for i in range(self.plan_combo.count()):
            if self.plan_combo.itemData(i) == name:
                self.plan_combo.blockSignals(True)
                self.plan_combo.setCurrentIndex(i)
                self.plan_combo.blockSignals(False)
                break

        QMessageBox.information(
            self, "Saved",
            f"Plan '{name}' with {len(entries)} skills saved.",
        )

    def _new_plan(self) -> None:
        """Create a new empty plan."""
        if self._plan.entries and self._plan_dirty:
            reply = QMessageBox.question(
                self, "New Plan",
                "Current plan has unsaved changes.\n"
                "Create new plan anyway?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._plan = SkillPlan(name="New Plan")
        self._plan_dirty = False
        self.plan_name_input.blockSignals(True)
        self.plan_name_input.setText("New Plan")
        self.plan_name_input.blockSignals(False)
        self.plan_combo.blockSignals(True)
        self.plan_combo.setCurrentIndex(0)
        self.plan_combo.blockSignals(False)
        self._update_plan_tree()

    def _delete_plan(self) -> None:
        """Delete the selected plan from DB."""
        if not self.db or not self._character_id:
            return

        idx = self.plan_combo.currentIndex()
        if idx <= 0:
            QMessageBox.information(
                self, "Delete",
                "No saved plan selected.",
            )
            return

        plan_name = self.plan_combo.currentData()
        if not plan_name:
            return

        reply = QMessageBox.question(
            self, "Delete Plan",
            f"Plan '{plan_name}' permanently delete?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.db.delete_skill_plan(self._character_id, plan_name)
        self._new_plan()
        self._refresh_plan_list()

    # ──────────────────────────────────────────────────────────────
    #  Plan Import / Export (JSON)
    # ──────────────────────────────────────────────────────────────

    def _export_plan(self) -> None:
        """Export current plan as JSON file."""
        if not self._plan.entries:
            QMessageBox.information(
                self, "Export", "The plan is empty."
            )
            return

        default_name = self._plan.name.replace(" ", "_") + ".json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plan", default_name,
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return

        data = {
            "pymon_skill_plan": True,
            "version": 1,
            "name": self._plan.name,
            "created": self._plan.created.isoformat(),
            "entries": [
                {
                    "type_id": e.type_id,
                    "skill_name": e.skill_name,
                    "target_level": e.target_level,
                    "notes": e.notes,
                }
                for e in self._plan.entries
            ],
        }

        try:
            Path(path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            QMessageBox.information(
                self, "Export",
                f"Plan '{self._plan.name}' mit {len(self._plan.entries)} "
                f"Skills exported to:\n{path}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Export Error", f"Error exporting:\n{exc}"
            )

    def _import_plan(self) -> None:
        """Import a plan from a JSON file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import plan", "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return

        try:
            text = Path(path).read_text(encoding="utf-8")
            data = json.loads(text)
        except Exception as exc:
            QMessageBox.critical(
                self, "Import Error", f"Could not read file:\n{exc}"
            )
            return

        # Validate format
        if not isinstance(data, dict) or "entries" not in data:
            QMessageBox.critical(
                self, "Import Error",
                "Invalid file format. Expected: PyMon Skill Plan JSON.",
            )
            return

        entries_data = data["entries"]
        if not isinstance(entries_data, list):
            QMessageBox.critical(
                self, "Import Error", "Invalid entries in plan."
            )
            return

        plan_name = data.get("name", Path(path).stem)

        # Ask if should replace or merge
        if self._plan.entries:
            reply = QMessageBox.question(
                self, "Import plan",
                f"Import plan '{plan_name}' with {len(entries_data)} skills?\n\n"
                "Current plan will be replaced.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._plan = SkillPlan(name=plan_name)
        for e in entries_data:
            if not isinstance(e, dict):
                continue
            type_id = e.get("type_id")
            skill_name = e.get("skill_name", f"Skill #{type_id}")
            target_level = e.get("target_level", 1)
            notes = e.get("notes", "")
            if type_id and isinstance(type_id, int) and 1 <= target_level <= 5:
                self._plan.entries.append(PlanEntry(
                    type_id=type_id,
                    skill_name=skill_name,
                    target_level=target_level,
                    notes=notes,
                ))

        self.plan_name_input.blockSignals(True)
        self.plan_name_input.setText(plan_name)
        self.plan_name_input.blockSignals(False)

        self._plan_dirty = True
        self._refresh_plan_times()
        self._update_plan_tree()

        QMessageBox.information(
            self, "Import",
            f"Plan '{plan_name}' with {len(self._plan.entries)} skills imported.",
        )

    def _print_plan(self) -> None:
        """Print current skill plan or save as PDF."""
        if not self._plan.entries:
            QMessageBox.information(self, "Print", "The plan is empty.")
            return

        from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageOrientation(QPrinter.Orientation.Portrait)

        dialog = QPrintPreviewDialog(printer, self)
        dialog.setWindowTitle(f"Print plan: {self._plan.name}")
        dialog.paintRequested.connect(lambda p: self._render_plan_html(p))
        dialog.exec()

    def _render_plan_html(self, printer) -> None:
        """Render plan as HTML document for printing."""
        from PySide6.QtGui import QTextDocument

        # Compute times
        computed = self.planner.compute_plan_times(
            self._plan.entries, self._attributes, self._trained_skills,
        )

        html = (
            "<html><head><style>"
            "body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; }"
            "h1 { color: #1a73e8; margin-bottom: 4px; }"
            "h3 { color: #555; margin-top: 2px; }"
            "table { border-collapse: collapse; width: 100%; margin-top: 12px; }"
            "th { background-color: #f0f0f0; text-align: left; padding: 6px 8px; "
            "border-bottom: 2px solid #333; font-weight: bold; }"
            "td { padding: 4px 8px; border-bottom: 1px solid #ddd; }"
            "tr:nth-child(even) { background-color: #f9f9f9; }"
            ".trained { color: #2e7d32; }"
            ".needed { color: #c62828; }"
            ".footer { margin-top: 16px; color: #777; font-size: 9pt; }"
            "</style></head><body>"
        )

        html += f"<h1>Skill Plan: {self._plan.name}</h1>"
        html += f"<h3>{len(self._plan.entries)} Skills | Total: {self._plan.total_display}</h3>"

        html += f"<p style='color:#777'>Created: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC</p>"

        html += (
            "<table>"
            "<tr><th>#</th><th>Skill</th><th>Level</th>"
            "<th>Training time</th><th>Cumulative</th><th>Status</th></tr>"
        )

        cumulative = 0
        for i, entry in enumerate(computed, 1):
            cumulative += entry.training_time_seconds
            time_str = format_training_time(entry.training_time_seconds)
            cum_str = format_training_time(cumulative)

            current = self._trained_skills.get(entry.type_id, 0)
            if current >= entry.target_level:
                status = "<span class='trained'>✓ Trained</span>"
            else:
                status = f"<span class='needed'>L{current} → L{entry.target_level}</span>"

            html += (
                f"<tr><td>{i}</td><td>{entry.skill_name}</td>"
                f"<td>Level {entry.target_level}</td>"
                f"<td>{time_str}</td><td>{cum_str}</td>"
                f"<td>{status}</td></tr>"
            )

        html += "</table>"
        html += "<p class='footer'>PyMon – EVE Online Character Monitor</p>"
        html += "</body></html>"

        doc = QTextDocument()
        doc.setHtml(html)
        doc.print_(printer)

    def _import_eft(self) -> None:
        """Import an EFT fitting and extract required skills into the plan."""
        dlg = LoadoutImportDialog(
            self.sde, self.planner, self._trained_skills, parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        entries = dlg.get_plan_entries()
        if not entries:
            return

        added = 0
        for entry in entries:
            # Skip if already trained
            if self._trained_skills.get(entry.type_id, 0) >= entry.target_level:
                continue
            # Skip if already in plan at same or higher level
            already = any(
                e.type_id == entry.type_id and e.target_level >= entry.target_level
                for e in self._plan.entries
            )
            if already:
                continue
            # Remove lower level entry if exists
            self._plan.entries = [
                e for e in self._plan.entries
                if not (e.type_id == entry.type_id and e.target_level < entry.target_level)
            ]
            self._plan.entries.append(entry)
            added += 1

        if added:
            self._plan_dirty = True
            self._refresh_plan_times()
            self._update_plan_tree()
            QMessageBox.information(
                self, "EFT Import",
                f"{added} missing skills added to plan.",
            )
        else:
            QMessageBox.information(
                self, "EFT Import",
                "All required skills are already trained or in the plan.",
            )
