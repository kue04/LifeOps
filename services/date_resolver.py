from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


WEEKDAY_BY_TEXT = {
    "周一": 0,
    "星期一": 0,
    "周二": 1,
    "星期二": 1,
    "周三": 2,
    "星期三": 2,
    "周四": 3,
    "星期四": 3,
    "周五": 4,
    "星期五": 4,
    "周六": 5,
    "星期六": 5,
    "周日": 6,
    "星期日": 6,
    "周天": 6,
    "星期天": 6,
}

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def today_in_timezone(tz_name: str = "Asia/Shanghai") -> date:
    return datetime.now(ZoneInfo(tz_name)).date()


def resolve_date_text(text: str | None, today: date | None = None) -> dict:
    if not text:
        return {"date_iso": None, "date_weekday": None, "date_resolved_from": None}
    base = today or today_in_timezone()
    raw = text.strip()

    if raw in {"今天", "今日"}:
        target = base
    elif raw == "明天":
        target = base + timedelta(days=1)
    elif raw == "后天":
        target = base + timedelta(days=2)
    else:
        target = _resolve_weekday(raw, base)

    if target is None:
        return {"date_iso": None, "date_weekday": None, "date_resolved_from": raw}
    return {
        "date_iso": target.isoformat(),
        "date_weekday": WEEKDAY_CN[target.weekday()],
        "date_resolved_from": raw,
    }


def _resolve_weekday(raw: str, base: date) -> date | None:
    weekday = next((value for key, value in WEEKDAY_BY_TEXT.items() if key in raw), None)
    if weekday is None:
        return None
    delta = (weekday - base.weekday()) % 7
    if "下" in raw:
        delta += 7
    return base + timedelta(days=delta)
