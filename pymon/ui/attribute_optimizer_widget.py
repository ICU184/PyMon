"""Attribute Optimizer / Remap Calculator widget.

Shows current vs optimal attribute distribution for a skill plan,
calculates SP/h improvement and next remap date.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pymon.services.skill_planner import SkillPlan, SkillPlanner, format_training_time
from pymon.ui.dark_theme import Colors

logger = logging.getLogger(__name__)

# Total attribute points available for remap (17 base + 14 distributable = 31 max per attr)
_BASE_POINTS = 17
_DISTRIBUTABLE = 14
_MAX_PER_ATTR = 27  # max any single attribute can be (17 base + 10 bonus)
_MIN_PER_ATTR = 17  # minimum per attribute
_TOTAL_POINTS = _BASE_POINTS * 5 + _DISTRIBUTABLE  # 85 + 14 = 99

_ATTR_NAMES = ["perception", "memory", "willpower", "intelligence", "charisma"]
_ATTR_LABELS = {
    "perception": "Perception",
    "memory": "Memory",
    "willpower": "Willpower",
    "intelligence": "Intelligence",
    "charisma": "Charisma",
}


class AttributeOptimizerWidget(QWidget):
    """Attribute Remap Calculator."""

    def __init__(
        self,
        planner: SkillPlanner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.planner = planner
        self._attributes: dict[str, int] = {a: _BASE_POINTS for a in _ATTR_NAMES}
        self._trained_skills: dict[int, int] = {}
        self._plan: SkillPlan | None = None
        self._optimal: dict[str, int] | None = None
        self._setup_ui()

    def set_character_data(
        self,
        attributes: dict[str, int],
        trained_skills: dict[int, int],
    ) -> None:
        self._attributes = attributes
        self._trained_skills = trained_skills
        self._update_current_display()

    def set_plan(self, plan: SkillPlan) -> None:
        self._plan = plan
        self._calculate_optimal()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Current Attributes ──
        current_group = QGroupBox("Current Attributes")
        current_layout = QVBoxLayout(current_group)

        self._current_bars: dict[str, tuple[QLabel, QProgressBar, QLabel]] = {}
        for attr in _ATTR_NAMES:
            row = QHBoxLayout()
            name_label = QLabel(_ATTR_LABELS[attr])
            name_label.setMinimumWidth(100)
            bar = QProgressBar()
            bar.setRange(0, _MAX_PER_ATTR)
            bar.setValue(_BASE_POINTS)
            bar.setFormat("%v")
            bar.setMaximumHeight(20)
            val_label = QLabel(str(_BASE_POINTS))
            val_label.setMinimumWidth(30)
            val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(name_label)
            row.addWidget(bar, stretch=1)
            row.addWidget(val_label)
            current_layout.addLayout(row)
            self._current_bars[attr] = (name_label, bar, val_label)

        self._sp_per_hour_label = QLabel("SP/Stunde: —")
        self._sp_per_hour_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        current_layout.addWidget(self._sp_per_hour_label)
        layout.addWidget(current_group)

        # ── Optimal Attributes ──
        optimal_group = QGroupBox("Optimal Attributes (for current plan)")
        optimal_layout = QVBoxLayout(optimal_group)

        self._optimal_bars: dict[str, tuple[QLabel, QProgressBar, QLabel]] = {}
        for attr in _ATTR_NAMES:
            row = QHBoxLayout()
            name_label = QLabel(_ATTR_LABELS[attr])
            name_label.setMinimumWidth(100)
            bar = QProgressBar()
            bar.setRange(0, _MAX_PER_ATTR)
            bar.setValue(0)
            bar.setFormat("%v")
            bar.setMaximumHeight(20)
            bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {Colors.ACCENT}; }}")
            val_label = QLabel("—")
            val_label.setMinimumWidth(30)
            val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(name_label)
            row.addWidget(bar, stretch=1)
            row.addWidget(val_label)
            optimal_layout.addLayout(row)
            self._optimal_bars[attr] = (name_label, bar, val_label)

        self._optimal_sp_label = QLabel("SP/Hour (optimal): —")
        self._optimal_sp_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        optimal_layout.addWidget(self._optimal_sp_label)

        self._improvement_label = QLabel("")
        self._improvement_label.setWordWrap(True)
        self._improvement_label.setTextFormat(Qt.TextFormat.RichText)
        optimal_layout.addWidget(self._improvement_label)

        layout.addWidget(optimal_group)

        # ── Remap Summary ──
        summary_group = QGroupBox("Remap Summary")
        summary_layout = QVBoxLayout(summary_group)
        self._summary_label = QLabel(
            "<p>Add skills to the plan to calculate the optimal attribute distribution.</p>"
            "<p style='color:{Colors.TEXT_DIM}'>A Neural Remap can be performed once per year. "
            "Additionally, up to 2 bonus remaps can be stored.</p>"
        )
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextFormat(Qt.TextFormat.RichText)
        summary_layout.addWidget(self._summary_label)

        # Calculate button
        calc_btn = QPushButton("🔄 Calculate Optimal")
        calc_btn.clicked.connect(self._calculate_optimal)
        summary_layout.addWidget(calc_btn)

        layout.addWidget(summary_group)
        layout.addStretch(1)

    def _update_current_display(self) -> None:
        """Update the current attribute bars."""
        for attr in _ATTR_NAMES:
            val = self._attributes.get(attr, _BASE_POINTS)
            _, bar, val_label = self._current_bars[attr]
            bar.setValue(val)
            val_label.setText(str(val))

        # Calculate current SP/hour for the plan
        if self._plan and self._plan.entries:
            sp_h = self._calc_plan_sp_per_hour(self._attributes)
            self._sp_per_hour_label.setText(f"SP/Hour: {sp_h:,.0f}")
        else:
            self._sp_per_hour_label.setText("SP/Hour: —")

    def _calculate_optimal(self) -> None:
        """Calculate optimal attribute distribution for the current plan."""
        if not self._plan or not self._plan.entries:
            self._improvement_label.setText(
                "<p style='color:{Colors.TEXT_DIM}'>No plan available – add skills to plan.</p>"
            )
            return

        # Collect weighted attribute usage from plan
        attr_weight: dict[str, float] = {a: 0.0 for a in _ATTR_NAMES}

        for entry in self._plan.entries:
            info = self.planner.get_skill_info(entry.type_id)
            if not info:
                continue
            current = self._trained_skills.get(entry.type_id, 0)
            if current >= entry.target_level:
                continue

            # Weight by SP needed for this entry
            from pymon.services.skill_planner import _SP_FOR_LEVEL
            sp_needed = 0
            for lvl in range(current + 1, entry.target_level + 1):
                sp_needed += (_SP_FOR_LEVEL[lvl] - _SP_FOR_LEVEL[lvl - 1]) * info.rank

            # Primary attribute gets full weight, secondary gets half
            attr_weight[info.primary_attr] += sp_needed
            attr_weight[info.secondary_attr] += sp_needed * 0.5

        # Greedy allocation: distribute points to highest-weight attributes
        optimal = {a: _BASE_POINTS for a in _ATTR_NAMES}
        remaining = _DISTRIBUTABLE

        # Sort by weight descending
        sorted_attrs = sorted(attr_weight.keys(), key=lambda a: attr_weight[a], reverse=True)

        for attr in sorted_attrs:
            if remaining <= 0:
                break
            add = min(remaining, _MAX_PER_ATTR - _BASE_POINTS)
            if attr_weight[attr] > 0 and add > 0:
                optimal[attr] += add
                remaining -= add

        # Distribute any remaining points to top attrs
        if remaining > 0:
            for attr in sorted_attrs:
                if remaining <= 0:
                    break
                space = _MAX_PER_ATTR - optimal[attr]
                add = min(remaining, space)
                optimal[attr] += add
                remaining -= add

        self._optimal = optimal

        # Update optimal bars
        for attr in _ATTR_NAMES:
            val = optimal[attr]
            _, bar, val_label = self._optimal_bars[attr]
            bar.setValue(val)
            val_label.setText(str(val))

            # Color: green if better, red if worse
            diff = val - self._attributes.get(attr, _BASE_POINTS)
            if diff > 0:
                bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {Colors.ACCENT}; }}")
            elif diff < 0:
                bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {Colors.RED}; }}")
            else:
                bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {Colors.BLUE}; }}")

        # Calculate improvement
        current_sp_h = self._calc_plan_sp_per_hour(self._attributes)
        optimal_sp_h = self._calc_plan_sp_per_hour(optimal)

        self._optimal_sp_label.setText(f"SP/Hour (optimal): {optimal_sp_h:,.0f}")

        if current_sp_h > 0:
            improvement = ((optimal_sp_h - current_sp_h) / current_sp_h) * 100
            time_current = sum(e.training_time_seconds for e in self._plan.entries)

            # Recalculate plan with optimal attributes
            from pymon.services.skill_planner import SkillPlan
            temp_plan = SkillPlan(name="temp", entries=list(self._plan.entries))
            self.planner.calculate_plan_times(temp_plan, optimal, self._trained_skills)
            time_optimal = sum(e.training_time_seconds for e in temp_plan.entries)
            time_saved = time_current - time_optimal

            color = Colors.ACCENT if improvement > 0 else Colors.RED
            html = (
                f"<p>Improvement: <b style='color:{color}'>{improvement:+.1f}%</b></p>"
                f"<p>Current Plan Time: {format_training_time(time_current)}</p>"
                f"<p>Optimal Plan Time: {format_training_time(time_optimal)}</p>"
            )
            if time_saved > 0:
                html += f"<p style='color:{Colors.ACCENT}'><b>Time Saved: {format_training_time(time_saved)}</b></p>"
            self._improvement_label.setText(html)

            # Update summary
            changes = []
            for attr in _ATTR_NAMES:
                diff = optimal[attr] - self._attributes.get(attr, _BASE_POINTS)
                if diff != 0:
                    direction = "↑" if diff > 0 else "↓"
                    changes.append(f"{_ATTR_LABELS[attr]}: {self._attributes.get(attr, _BASE_POINTS)} → {optimal[attr]} ({direction}{abs(diff)})")

            if changes:
                summary = "<p><b>Recommended Changes:</b></p><ul>"
                for c in changes:
                    summary += f"<li>{c}</li>"
                summary += "</ul>"
            else:
                summary = "<p style='color:{Colors.ACCENT}'>✓ Your current attributes are already optimal for this plan!</p>"
            self._summary_label.setText(summary)
        else:
            self._improvement_label.setText("")

    def _calc_plan_sp_per_hour(self, attributes: dict[str, int]) -> float:
        """Calculate average SP/hour for the current plan with given attributes."""
        if not self._plan or not self._plan.entries:
            return 0.0

        total_sp = 0
        total_seconds = 0.0

        for entry in self._plan.entries:
            info = self.planner.get_skill_info(entry.type_id)
            if not info:
                continue
            current = self._trained_skills.get(entry.type_id, 0)
            if current >= entry.target_level:
                continue

            t = self.planner.calculate_training_time(
                entry.type_id, current, entry.target_level, attributes
            )
            total_seconds += t

            from pymon.services.skill_planner import _SP_FOR_LEVEL
            for lvl in range(current + 1, entry.target_level + 1):
                total_sp += int((_SP_FOR_LEVEL[lvl] - _SP_FOR_LEVEL[lvl - 1]) * info.rank)

        if total_seconds <= 0:
            return 0.0
        return (total_sp / total_seconds) * 3600
