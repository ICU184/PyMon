"""Calendar export – ICS file generation for skill queue events.

Generates an .ics (iCalendar) file with VEVENT entries for each
skill in the training queue. Compatible with Google Calendar,
Outlook, Apple Calendar, etc.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# iCalendar format helpers
_ICS_DATE_FMT = "%Y%m%dT%H%M%SZ"


def _ics_escape(text: str) -> str:
    """Escape special chars for iCalendar text fields."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def generate_ics(
    character_name: str,
    skill_queue: list[dict[str, Any]],
    type_names: dict[int, str] | None = None,
) -> str:
    """Generate an ICS calendar string from the skill queue.

    Parameters
    ----------
    character_name:
        Name of the character (used in calendar name).
    skill_queue:
        List of dicts with keys: skill_id, finished_level,
        start_date (ISO str), finish_date (ISO str).
    type_names:
        Optional mapping of type_id -> skill name.

    Returns
    -------
    str – Complete ICS file content.
    """
    if type_names is None:
        type_names = {}

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PyMon//Skill Queue//EN",
        f"X-WR-CALNAME:{_ics_escape(character_name)} – Skill Queue",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    now_str = datetime.now(UTC).strftime(_ICS_DATE_FMT)

    for entry in skill_queue:
        start_str = entry.get("start_date") or entry.get("training_start_sp")
        finish_str = entry.get("finish_date")
        if not start_str or not finish_str:
            continue

        skill_id = entry.get("skill_id") or entry.get("type_id", 0)
        level = entry.get("finished_level", 0)
        skill_name = type_names.get(skill_id, f"Skill #{skill_id}")

        # Parse ISO dates
        try:
            dt_start = _parse_iso(start_str)
            dt_end = _parse_iso(finish_str)
        except (ValueError, TypeError):
            continue

        # UID based on character + skill + level
        uid_raw = f"pymon-{character_name}-{skill_id}-{level}"
        uid = hashlib.md5(uid_raw.encode()).hexdigest()

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}@pymon",
            f"DTSTAMP:{now_str}",
            f"DTSTART:{dt_start.strftime(_ICS_DATE_FMT)}",
            f"DTEND:{dt_end.strftime(_ICS_DATE_FMT)}",
            f"SUMMARY:{_ics_escape(skill_name)} Level {level}",
            f"DESCRIPTION:{_ics_escape(character_name)} trainiert {skill_name} auf Level {level}",
            "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "TRIGGER:-PT15M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_escape(skill_name)} Level {level} fast fertig",
            "END:VALARM",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def export_ics_file(
    path: str | Path,
    character_name: str,
    skill_queue: list[dict[str, Any]],
    type_names: dict[int, str] | None = None,
) -> tuple[bool, str]:
    """Export skill queue to an .ics file.

    Returns (success, message).
    """
    try:
        content = generate_ics(character_name, skill_queue, type_names)
        p = Path(path)
        p.write_text(content, encoding="utf-8")
        return True, f"Calendar exported to:\n{p}"
    except Exception as e:
        logger.error("ICS export failed", exc_info=True)
        return False, f"Export fehlgeschlagen:\n{e}"


def _parse_iso(s: str) -> datetime:
    """Parse ISO 8601 datetime string to UTC datetime."""
    s = s.rstrip("Z").replace("+00:00", "")
    # Try with fractional seconds first
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s}")
