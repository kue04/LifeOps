"""意图与信号判定：规则式判断文本是否含某类意图，供约束抽取与反思复用。

从 agent/nodes.py 抽出的叶子工具函数，不依赖 Agent 流程状态，
可被约束抽取、规划、评分、反思等节点共用。
"""

from __future__ import annotations

from typing import Any

from agent.constants import (
    NEGATION_WORDS,
    RECENT_ACTIVITY_WORDS,
)
from agent.state import AgentState


def _activity_intent(text: str) -> str | None:
    for word in ["爬山", "徒步", "看展", "展览", "散步", "夜景", "咖啡", "美食"]:
        if word in text:
            return word
    if "爬" in text:
        return "爬山"
    return None


def _allowed_dynamic_tools() -> set[str]:
    return {"todo_decompose", "weather", "place_search", "search", "meal_pick", "errand_parse", "route", "budget", "confirm_action"}


def _coverage_issue(state: AgentState) -> str | None:
    if state.constraints.get("task_type") in {"errand", "meal", "todo"}:
        return None
    requested = set(state.constraints.get("preferences", []))
    if not requested or not state.final_plan:
        return None
    covered = set()
    for item in state.final_plan.get("itinerary", []):
        covered.update(item.get("tags", []))
    missing = requested - covered
    if missing:
        return "计划未覆盖偏好：" + "、".join(sorted(missing))
    return None


def _covered_preferences(selected: list[dict], preferences: list[str]) -> set[str]:
    covered = set()
    requested = set(preferences)
    for place in selected:
        covered.update(requested.intersection(place.get("tags", [])))
    return covered


def _dynamic_city(state: AgentState) -> str | None:
    destination = state.constraints.get("destination") or {}
    return state.constraints.get("destination_city") or destination.get("city") or state.constraints.get("city") or state.constraints.get("default_city")


def _is_mixed_intent(state: AgentState) -> bool:
    return len({item.get("type") for item in (state.intent_contract or {}).get("sub_tasks", [])}) > 1


def _is_mountain_or_hiking_trip(
    text: str,
    destination: dict[str, Any],
    preferences: set[str],
    activity_intent: str | None,
) -> bool:
    destination_text = f"{destination.get('name', '')} {destination.get('raw', '')}"
    return (
        bool({"爬山", "登山", "徒步"}.intersection(preferences))
        or activity_intent in {"爬山", "登山", "徒步"}
        or any(word in text for word in ["爬山", "登山", "徒步", "索道"])
        or any(word in destination_text for word in ["华山", "黄山", "泰山", "衡山", "山风景", "风景区"])
    )


def _is_negated(text: str, word: str) -> bool:
    index = text.find(word)
    if index < 0:
        return False
    prefix = text[max(0, index - 4):index]
    return any(negation in prefix for negation in NEGATION_WORDS)


def _is_travel_guide_plan(plan: dict[str, Any]) -> bool:
    return plan.get("task_type") in {"travel", "mixed"} and bool(plan.get("itinerary") or plan.get("meal_candidates"))


def _issue_requires_replan(issue: str) -> bool:
    return any(word in issue for word in [
        "intent_missing_subtask",
        "intent_output_mismatch",
        "intent_hard_constraint_conflict",
        "目的地与用户目标不符",
        "缺少从出发地到目的地",
        "没有安排该目的地",
    ])


def _legacy_tool_name(tool: Any) -> str:
    return {
        "todo_decompose": "todo_decomposer",
        "weather": "weather_tool",
        "place_search": "place_search_tool",
        "search": "web_search_tool",
        "meal_pick": "meal_candidate_scorer",
        "errand_parse": "errand_candidate_scorer",
        "route": "route_tool",
        "budget": "budget_tool",
        "confirm_action": "confirm_action_builder",
    }.get(str(tool or ""), str(tool or "unknown_tool"))


def _plan_has_enough_city_items(plan: dict[str, Any], state: AgentState) -> bool:
    destination = state.constraints.get("destination") or {}
    if state.constraints.get("route_scope") != "city_trip" and destination.get("type") != "city":
        return True
    if state.constraints.get("preferences"):
        return True
    return len(plan.get("itinerary") or []) >= 3


def _plan_has_executable_items(plan: dict[str, Any]) -> bool:
    return bool(plan.get("itinerary") or plan.get("todo_items") or plan.get("meal_candidates") or plan.get("errand_items"))


def _plan_uses_candidate_places(plan: dict[str, Any], selected: list[dict]) -> bool:
    allowed = {place["name"] for place in selected}
    return bool(allowed) and all(item.get("place") in allowed for item in plan.get("itinerary", []))


def _reflection_is_final(reflection: dict[str, Any] | None) -> bool:
    if not reflection:
        return True
    return reflection.get("passed") is True and reflection.get("next_action") == "final"


def _reflection_issues(reflection: dict[str, Any] | None) -> list[str]:
    if not reflection:
        return []
    issues = reflection.get("issues") or []
    if isinstance(issues, str):
        return [issues]
    return [str(issue) for issue in issues if issue]


def _remove_avoided_preferences(preferences: list[str], avoid: list[str]) -> list[str]:
    avoid_set = set(avoid)
    return [item for item in preferences if item not in avoid_set]


def _required_outputs_for_subtasks(sub_tasks: list[dict[str, Any]]) -> list[str]:
    outputs = {"summary", "budget", "risks", "confirm_actions"}
    task_types = {item.get("type") for item in sub_tasks}
    if task_types.intersection({"travel", "errand", "meal"}):
        outputs.update({"itinerary", "route"})
    if "errand" in task_types:
        outputs.add("errand_items")
    if "meal" in task_types:
        outputs.add("meal_candidates")
    if "todo" in task_types:
        outputs.update({"todo_items", "time_blocks", "acceptance_criteria"})
    return sorted(outputs)


def _target_place_count(constraints: dict, replan_context: dict[str, Any]) -> int:
    explicit_preferences = constraints.get("preferences") or []
    preference_count = len(set(explicit_preferences))
    trip_days = constraints.get("trip_days")
    if isinstance(trip_days, int) and trip_days >= 2:
        return max(4, min(6, trip_days * 2 + 1, max(4, preference_count + 2)))
    issues = " ".join(
        str(replan_context.get(key, ""))
        for key in ["review", "issues", "next_action"]
    )
    if any(word in issues for word in ["一天", "一日", "第二天", "覆盖不足", "过短", "太少"]):
        return max(5, preference_count)
    return max(3, preference_count)


def _text_has_attraction_or_guide_signal(text: str) -> bool:
    return any(word in text for word in ["景点", "攻略", "游玩", "路线", "门票", "开放时间", "预约", "必去", "打卡"])


def _text_has_recent_activity_signal(text: str) -> bool:
    return any(word in text for word in RECENT_ACTIVITY_WORDS)


def _text_has_travel_content_signal(text: str) -> bool:
    return any(word in text for word in [
        "景点", "旅游", "攻略", "游玩", "一日游", "两日游", "三日游", "必去", "必打卡", "路线",
        "门票", "开放时间", "预约", "交通", "美食", "住宿", "打卡", "榜单", "推荐",
    ])


def _uniquely_covers_preference(item: dict, selected: list[dict], requested: set[str]) -> bool:
    item_matches = requested.intersection(item.get("tags", []))
    if not item_matches:
        return False
    for preference in item_matches:
        other_matches = [
            other for other in selected
            if other is not item and preference in other.get("tags", [])
        ]
        if not other_matches:
            return True
    return False


def _uses_fallback_places(plan: dict[str, Any]) -> bool:
    for place in (plan.get("local_route") or {}).get("ordered_places") or []:
        if place.get("provider") in {"city_seed", "city_fallback"}:
            return True
    for item in plan.get("itinerary") or []:
        if item.get("provider") in {"city_seed", "city_fallback"}:
            return True
    return False
