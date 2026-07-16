from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def build_ics(final_plan: dict) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LifeOps//Agent MVP//CN",
    ]
    plan_date = _plan_date(final_plan)
    for index, item in enumerate(final_plan.get("itinerary", []), start=1):
        time_range = str(item.get("time") or "")
        if "-" not in time_range:
            continue
        start, end = [part.strip() for part in time_range.split("-", 1)]
        uid = f"{index}-{final_plan.get('title', 'lifeops')}@lifeops"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{_ics_text(uid)}",
                f"DTSTAMP:{_stamp()}",
                f"SUMMARY:{_ics_text(item.get('place') or final_plan.get('title') or 'LifeOps plan')}",
                f"DESCRIPTION:{_ics_text(item.get('reason') or '')}",
                f"LOCATION:{_ics_text(item.get('address') or item.get('area') or '')}",
                f"DTSTART:{_floating_time(plan_date, start)}",
                f"DTEND:{_floating_time(plan_date, end)}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def save_ics(final_plan: dict, output_dir: str | Path = "exports") -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    file_path = path / "lifeops_plan.ics"
    file_path.write_text(build_ics(final_plan), encoding="utf-8")
    return file_path


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _plan_date(final_plan: dict[str, Any]) -> str:
    raw = str(final_plan.get("date") or "")
    try:
        return datetime.fromisoformat(raw[:10]).strftime("%Y%m%d")
    except ValueError:
        return datetime.now().strftime("%Y%m%d")


def _floating_time(date_text: str, label: str) -> str:
    hour, minute = label.split(":", 1)
    return f"{date_text}T{hour.zfill(2)}{minute[:2].zfill(2)}00"


def _ics_text(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )
