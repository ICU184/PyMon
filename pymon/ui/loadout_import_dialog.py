"""Loadout Import – EFT format parser + required-skills extractor."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pymon.sde.database import SDEDatabase
from pymon.services.skill_planner import PlanEntry, SkillPlanner

logger = logging.getLogger(__name__)

# Dogma attribute IDs for skill requirements
_REQ_SKILL_IDS = [182, 183, 184, 1285, 1289, 1290]
_REQ_LEVEL_IDS = [277, 278, 279, 1286, 1287, 1288]


@dataclass
class ParsedFitting:
    """Parsed EFT fitting."""

    ship_name: str = ""
    fitting_name: str = ""
    module_names: list[str] = field(default_factory=list)


def parse_eft(text: str) -> ParsedFitting | None:
    """Parse EFT (EVE Fitting Tool) format text.

    EFT format example:
        [Vexor Navy Issue, My Fit]
        Drone Damage Amplifier II
        Drone Damage Amplifier II
        Energized Adaptive Nano Membrane II

        50MN Cold-Gas Enduring Microwarpdrive
        Large Shield Extender II

        Heavy Pulse Laser II, Scorch M
        [Empty High slot]

        Medium Auxiliary Nano Pump I
        Medium Auxiliary Nano Pump I

        Hammerhead II x5
        Hobgoblin II x5
    """
    lines = text.strip().splitlines()
    if not lines:
        return None

    # First line must be [Ship, Name]
    header = lines[0].strip()
    m = re.match(r"^\[(.+?),\s*(.+?)\]$", header)
    if not m:
        return None

    fitting = ParsedFitting(ship_name=m.group(1).strip(), fitting_name=m.group(2).strip())

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        # Skip [Empty ...] slots
        if re.match(r"^\[Empty .+\]$", line):
            continue
        # Remove ammo/charge after comma: "Heavy Pulse Laser II, Scorch M" → "Heavy Pulse Laser II"
        if "," in line:
            line = line.split(",")[0].strip()
        # Remove quantity suffix: "Hammerhead II x5" → "Hammerhead II"
        line = re.sub(r"\s+x\d+\s*$", "", line)
        if line:
            fitting.module_names.append(line)

    return fitting


def _resolve_type_id(sde: SDEDatabase, name: str) -> int | None:
    """Resolve a type name to its type_id via SDE."""
    results = sde.search_types(name, published_only=True, limit=5)
    for r in results:
        if r.get("name_en", "").lower() == name.lower():
            return r["type_id"]
    # Fallback: first result
    if results:
        return results[0]["type_id"]
    return None


def _get_required_skills(sde: SDEDatabase, type_id: int) -> list[tuple[int, str, int]]:
    """Extract required skills for a type from dogma attributes.

    Returns list of (skill_type_id, skill_name, required_level).
    """
    attrs = sde.get_type_dogma_attributes(type_id)
    attr_map = {a["attribute_id"]: a["value"] for a in attrs}

    skills: list[tuple[int, str, int]] = []
    for skill_attr, level_attr in zip(_REQ_SKILL_IDS, _REQ_LEVEL_IDS):
        skill_type_id = attr_map.get(skill_attr)
        req_level = attr_map.get(level_attr)
        if skill_type_id and req_level:
            sid = int(skill_type_id)
            lvl = int(req_level)
            type_info = sde.get_type(sid)
            name = type_info["name_en"] if type_info else f"Unknown Skill ({sid})"
            skills.append((sid, name, lvl))

    return skills


class LoadoutImportDialog(QDialog):
    """Dialog for importing EFT fittings and extracting required skills."""

    def __init__(
        self,
        sde: SDEDatabase,
        planner: SkillPlanner,
        trained_skills: dict[int, int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.sde = sde
        self.planner = planner
        self._trained = trained_skills or {}
        self._plan_entries: list[PlanEntry] = []

        self.setWindowTitle("Loadout Import (EFT)")
        self.setMinimumSize(700, 600)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("📋 EFT Loadout importieren")
        title.setProperty("cssClass", "widget-title")
        layout.addWidget(title)

        layout.addWidget(QLabel("EFT-Text einfügen (Strg+V):"))
        self._input = QPlainTextEdit()
        self._input.setPlaceholderText(
            "[Ship Name, Fitting Name]\n"
            "Module I\n"
            "Module II\n"
            "...\n\n"
            "Aus dem Spiel: Fitting → Copy to Clipboard (EFT)"
        )
        self._input.setMaximumHeight(200)
        layout.addWidget(self._input)

        btn_row = QHBoxLayout()
        parse_btn = QPushButton("🔍 Analysieren")
        parse_btn.clicked.connect(self._on_parse)
        btn_row.addWidget(parse_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._info_label = QLabel("")
        layout.addWidget(self._info_label)

        # Results tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Skill / Modul", "Level", "Status"])
        self._tree.setColumnWidth(0, 300)
        self._tree.setColumnWidth(1, 60)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        layout.addWidget(self._tree, stretch=1)

        # Bottom buttons
        bottom = QHBoxLayout()
        self._add_btn = QPushButton("✚ Zum Skill-Plan hinzufügen")
        self._add_btn.clicked.connect(self._on_add_to_plan)
        self._add_btn.setEnabled(False)
        bottom.addWidget(self._add_btn)
        bottom.addStretch()
        cancel_btn = QPushButton("Close")
        cancel_btn.setObjectName("cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)
        layout.addLayout(bottom)

    def _on_parse(self) -> None:
        """Parse the EFT text and show required skills."""
        text = self._input.toPlainText().strip()
        if not text:
            self._info_label.setText("⚠ Please paste EFT text")
            return

        fitting = parse_eft(text)
        if not fitting:
            self._info_label.setText("⚠ Ungültiges EFT-Format. Erste Zeile muss [Ship, Name] sein.")
            return

        self._tree.clear()
        self._plan_entries.clear()

        # Collect all unique type names (ship + modules)
        all_names = [fitting.ship_name, *fitting.module_names]
        unique_names = list(dict.fromkeys(all_names))  # preserve order, deduplicate

        total_skills = 0
        missing_skills = 0

        for item_name in unique_names:
            type_id = _resolve_type_id(self.sde, item_name)
            if not type_id:
                # Unresolved item
                node = QTreeWidgetItem(self._tree, [f"❓ {item_name}", "", "Nicht gefunden"])
                node.setForeground(2, Qt.GlobalColor.red)
                continue

            required = _get_required_skills(self.sde, type_id)
            if not required:
                continue

            # Parent node for this module/ship
            node = QTreeWidgetItem(self._tree, [item_name, "", ""])
            node.setExpanded(True)

            for skill_id, skill_name, req_level in required:
                total_skills += 1
                trained_level = self._trained.get(skill_id, 0)
                level_roman = ["", "I", "II", "III", "IV", "V"][min(req_level, 5)]

                if trained_level >= req_level:
                    status = "✓ Trainiert"
                    color = Qt.GlobalColor.darkGreen
                else:
                    missing_skills += 1
                    status = f"✗ Lvl {trained_level} → {req_level}"
                    color = Qt.GlobalColor.red

                    # Add to plan entries (only missing ones)
                    already = any(
                        e.type_id == skill_id and e.target_level >= req_level
                        for e in self._plan_entries
                    )
                    if not already:
                        self._plan_entries.append(
                            PlanEntry(
                                type_id=skill_id,
                                skill_name=skill_name,
                                target_level=req_level,
                                current_level=trained_level,
                                notes=f"Für: {item_name}",
                            )
                        )

                child = QTreeWidgetItem(node, [skill_name, level_roman, status])
                child.setForeground(2, color)

                # Recursively add prerequisite skills
                self._add_prerequisites(skill_id, req_level, node)

        self._info_label.setText(
            f"\U0001f680 {fitting.ship_name} \u2013 \u201e{fitting.fitting_name}\u201c\n"
            f"   {len(unique_names)} Module/Ship | {total_skills} ben\u00f6tigte Skills | "
            f"{missing_skills} fehlend | {len(self._plan_entries)} zum Plan"
        )
        self._add_btn.setEnabled(len(self._plan_entries) > 0)

    def _add_prerequisites(
        self, skill_type_id: int, level: int, parent_node: QTreeWidgetItem
    ) -> None:
        """Recursively add prerequisite skills that are not yet trained."""
        prereqs = self.planner.get_prerequisites_tree(skill_type_id, level)
        for pid, pname, plevel in prereqs:
            trained = self._trained.get(pid, 0)
            if trained >= plevel:
                continue  # already trained

            already = any(
                e.type_id == pid and e.target_level >= plevel
                for e in self._plan_entries
            )
            if not already:
                self._plan_entries.append(
                    PlanEntry(
                        type_id=pid,
                        skill_name=pname,
                        target_level=plevel,
                        current_level=trained,
                        notes="Prerequisite",
                    )
                )

    def _on_add_to_plan(self) -> None:
        """Signal acceptance with plan entries ready."""
        if self._plan_entries:
            self.accept()

    def get_plan_entries(self) -> list[PlanEntry]:
        """Return the plan entries for the caller to integrate."""
        return list(self._plan_entries)
