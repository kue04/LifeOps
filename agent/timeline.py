"""时间线拼装与计划校验：把候选点位组织成带时间顺序的行程并做合法性检查。

从 agent/nodes.py 整组搬迁，闭包自洽，不依赖其他 Agent 节点。
"""

from __future__ import annotations

from typing import Any

from agent.intent import (
    _todo_time_blocks,
)
from agent.scoring import (
    _is_iconic_place,
)
from agent.state import AgentState
from agent.text_utils import (
    _time_label,
)


def _timeline_from_errands(items: list[dict[str, Any]], places: list[dict[str, Any]], legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = 9 * 60
    timeline = []
    for index, item in enumerate(items):
        travel = legs[index].get("minutes", 15) if index < len(legs) else 15
        current += int(travel)
        start = _time_label(current)
        current += int(item.get("duration_minutes") or 35)
        place = places[index] if index < len(places) else {}
        timeline.append({
            "time": f"{start}-{_time_label(current)}",
            "place": place.get("name") or item["title"],
            "area": place.get("area"),
            "address": place.get("address") or item.get("location_status"),
            "map_url": place.get("map_url"),
            "play_points": [item.get("success_criteria", "完成该事项")],
            "reason": "顺路执行，外部动作先等待确认",
            "cost": place.get("estimated_cost", 0),
            "cost_known": place.get("cost_known", False),
            "cost_note": place.get("cost_note", "费用待确认"),
        })
    return timeline


def _timeline_from_meals(places: list[dict[str, Any]], legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = 11 * 60 + 30
    timeline = []
    for index, place in enumerate(places):
        if index:
            current += int(legs[index].get("minutes", 15) if index < len(legs) else 15)
        start = _time_label(current)
        current += int(place.get("duration_minutes") or 75)
        timeline.append({
            "time": f"{start}-{_time_label(current)}",
            "place": place.get("name"),
            "area": place.get("area"),
            "address": place.get("address"),
            "map_url": place.get("map_url"),
            "play_points": place.get("play_points") or ["按预算、口味和距离作为餐饮候选"],
            "reason": place.get("reason"),
            "cost": place.get("estimated_cost", 0),
            "cost_known": place.get("cost_known", False),
            "cost_note": place.get("cost_note", "价格待确认"),
        })
    return timeline


def _timeline_from_todos(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "time": block["time"],
            "place": block["title"],
            "address": "无需地点",
            "play_points": [tasks[index].get("success_criteria", "完成该任务")],
            "cost": 0,
            "cost_known": True,
            "cost_note": "无地点/交通费用",
        }
        for index, block in enumerate(_todo_time_blocks(tasks))
    ]


def _annotate_places_for_goal(places: list[dict], state: AgentState) -> list[dict]:
    preferences = set(state.constraints.get("preferences") or [])
    goal_text = f"{state.goal or ''} {state.user_input}"
    active_requested = bool(preferences.intersection({"爬山", "徒步", "登山", "运动"})) or any(
        word in goal_text for word in ["爬山", "徒步", "登山", "运动量", "多走路"]
    )
    for place in places:
        tags = set(place.get("tags", []))
        score = 0
        if preferences.intersection(tags):
            score += min(14, len(preferences.intersection(tags)) * 7)
        if active_requested and tags.intersection({"爬山", "徒步", "登山", "运动"}):
            score += 10
        if _is_iconic_place(place):
            score += 6
        if place.get("event_score"):
            score += 4
        place["goal_match_score"] = score
    return places
