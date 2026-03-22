"""Industry domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class IndustryJob:
    """An industry job (manufacturing, research, etc.)."""

    job_id: int
    installer_id: int = 0
    installer_name: str = ""
    facility_id: int = 0
    station_id: int = 0
    activity_id: int = 0  # 1=manufacturing, 3=TE, 4=ME, 5=copying, 8=invention, 9=reactions
    activity_name: str = ""
    blueprint_id: int = 0
    blueprint_type_id: int = 0
    blueprint_type_name: str = ""
    product_type_id: int = 0
    product_type_name: str = ""
    status: str = ""  # active, paused, ready, delivered, cancelled, reverted
    runs: int = 0
    licensed_runs: int = 0
    cost: float = 0.0
    start_date: datetime | None = None
    end_date: datetime | None = None
    completed_date: datetime | None = None
    pause_date: datetime | None = None
    probability: float = 0.0
    successful_runs: int | None = None

    @property
    def activity_display_name(self) -> str:
        """Human-readable activity name."""
        names = {
            1: "Manufacturing",
            3: "Time Efficiency Research",
            4: "Material Efficiency Research",
            5: "Copying",
            8: "Invention",
            9: "Reaction",
            11: "Reverse Engineering",
        }
        return names.get(self.activity_id, f"Activity {self.activity_id}")


@dataclass
class MiningEntry:
    """A mining ledger entry."""

    date: str = ""
    solar_system_id: int = 0
    solar_system_name: str = ""
    type_id: int = 0
    type_name: str = ""
    quantity: int = 0
