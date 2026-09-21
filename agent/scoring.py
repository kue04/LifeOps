"""候选评分、风险检查与反思修正：决定去哪些点、拦什么风险、是否重规划。

从 agent/nodes.py 整组搬迁，闭包自洽，不依赖其他 Agent 节点。
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.constants import (
    NATIONAL_CHAIN_MEAL_WORDS,
    POPULAR_PLACE_KEYWORDS_BY_CITY,
)
from agent.guide_messages import (
    _is_national_chain_meal,
)
from agent.intent import (
    _has_hard_reflection_issue,
)
from agent.intent_signals import (
    _coverage_issue,
    _issue_requires_replan,
    _plan_has_executable_items,
    _reflection_issues,
    _uses_fallback_places,
)
from agent.place_utils import (
    _all_popular_keywords,
    _is_city_name,
    _meal_local_score,
    _meal_text,
    _normalize_task_place,
)
from agent.prompts import REFLECTION_PROMPT
from agent.state import AgentState
from agent.text_utils import (
    _intent_contract_issues,
    _llm_enabled,
    _llm_model_name,
    _log,
)
from services.llm_client import llm_client
from services.risk_checker import check_risks
from services.scorer import score_candidates


def score_candidates_node(state: AgentState) -> AgentState:
    if state.constraints.get("task_type") == "todo":
        state.candidates = []
        _log(state, "candidate_scorer", "todo 场景无需地点候选评分", {"task_type": "todo"})
        return state
    state.candidates = sorted(score_candidates(
        state._places,  # type: ignore[attr-defined]
        state.constraints.get("preferences", []),
        state.constraints.get("budget"),
        state.constraints.get("pace"),
        state._weather,  # type: ignore[attr-defined]
    ), key=_travel_priority, reverse=True)
    _log(state, "candidate_scorer", "对候选地点进行排序", {
        "top_candidates": [item["name"] for item in state.candidates[:5]]
    })
    return state


def travel_candidate_scorer(state: AgentState) -> AgentState:
    return score_candidates_node(state)


def errand_candidate_scorer(state: AgentState) -> AgentState:
    state.candidates = list(getattr(state, "_places", []))
    _log(state, "errand_candidate_scorer", "跑腿场景保留地点候选用于顺路安排", {"candidates_count": len(state.candidates)})
    return state


def meal_candidate_scorer(state: AgentState) -> AgentState:
    foods = (getattr(state, "_lifestyle_places", {}) or {}).get("foods", [])
    state.candidates = _meal_candidates(foods or getattr(state, "_places", []), state.constraints)
    _log(state, "meal_candidate_scorer", "餐饮场景整理餐厅候选", {"candidates_count": len(state.candidates)})
    return state


def check_risks_node(state: AgentState) -> AgentState:
    result = check_risks(state.final_plan or {}, state.constraints, getattr(state, "_weather", {}))
    coverage_issue = _coverage_issue(state)
    if coverage_issue:
        result["risks"].append(coverage_issue)
    destination_issue = _destination_issue(state)
    if destination_issue:
        result["risks"].append(destination_issue)
    for issue in _intent_contract_issues(state):
        if issue not in result["risks"]:
            result["risks"].append(issue)
    state.risks = result["risks"]
    state.fallbacks = result["fallbacks"]
    state.need_human_confirm = result["need_human_confirm"]
    _log(state, "risk_checker", "检查预算、天气、节奏和偏好覆盖", result)
    return state


def reflect(state: AgentState) -> AgentState:
    issues = list(state.risks)
    if not state.final_plan or not _plan_has_executable_items(state.final_plan):
        issues.append("没有生成有效行程")
    replan_needed = any(_issue_requires_replan(issue) for issue in issues)
    passed = not any("超过用户限制" in issue or "没有生成" in issue for issue in issues) and not replan_needed
    rule_reflection = {
        "passed": passed,
        "issues": issues,
        "next_action": "final" if passed else "replan" if replan_needed else "ask_user",
        "review": "计划满足核心约束" if passed else "计划仍有未满足约束",
    }
    if state.constraints.get("task_type") in {"errand", "meal", "todo"} or _uses_fallback_places(state.final_plan or {}):
        state.reflection = rule_reflection
    else:
        llm_reflection = _reflect_with_llm(state, rule_reflection) or rule_reflection
        if rule_reflection["passed"] and not _has_hard_reflection_issue(llm_reflection):
            llm_reflection["passed"] = True
            llm_reflection["next_action"] = "final"
            llm_reflection["issues"] = []
        state.reflection = llm_reflection
    state.reflection["replan_count"] = state.replan_count
    _log(state, "reflection", "评估当前计划是否可直接输出", state.reflection)
    return state


def _reflect_with_llm(state: AgentState, rule_reflection: dict[str, Any]) -> dict[str, Any] | None:
    if not _llm_enabled():
        return None
    payload = {
        "intent_contract": state.intent_contract,
        "execution_plan": state.execution_plan,
        "constraints": state.constraints,
        "final_plan": state.final_plan,
        "risks": state.risks,
        "fallbacks": state.fallbacks,
        "rule_reflection": rule_reflection,
    }
    try:
        reflection = llm_client.json_complete(REFLECTION_PROMPT, json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        state.llm_usage.append({"node": "reflection", "status": "error", "error": str(exc)})
        return None
    if "passed" not in reflection or "next_action" not in reflection:
        state.llm_usage.append({"node": "reflection", "status": "ignored", "reason": "invalid_json_shape"})
        return None
    state.llm_usage.append({"node": "reflection", "status": "success", "model": _llm_model_name()})
    return reflection


def _filter_reflection_blocked_places(candidates: list[dict], replan_context: dict[str, Any]) -> list[dict]:
    issues = _reflection_issues(replan_context)
    if not issues:
        return candidates
    blocked_text = "\n".join(
        issue for issue in issues if any(word in issue for word in ["暂停开放", "不能安排", "不可安排", "不适合安排"])
    )
    if not blocked_text:
        return candidates
    blocked_names = set()
    for issue in blocked_text.splitlines():
        prefix = re.split(r"[（(]", issue, maxsplit=1)[0].strip()
        prefix = re.sub(r"^(问题|风险|提醒)[:：]\s*", "", prefix).strip()
        if prefix:
            blocked_names.add(prefix)
    return [
        candidate
        for candidate in candidates
        if not any(
            name and (name in str(candidate.get("name", "")) or str(candidate.get("name", "")) in name)
            for name in blocked_names
        )
        and not any(str(candidate.get("name", "")) and str(candidate.get("name", "")) in issue for issue in blocked_text.splitlines())
    ]


def _travel_priority(candidate: dict) -> tuple[int, int, int, int, int, int, int]:
    goal_bonus = int(candidate.get("goal_match_score", 0) or 0)
    event_bonus = int(candidate.get("event_score", 0) or 0)
    web_bonus = int(candidate.get("web_match_score", 0) or 0)
    iconic_bonus = 1 if _is_iconic_place(candidate) else 0
    popularity_bonus = int(candidate.get("popularity_score", 0) or 0)
    evidence_bonus = len(candidate.get("evidence") or [])
    return goal_bonus, event_bonus, web_bonus, iconic_bonus, popularity_bonus, evidence_bonus, int(candidate.get("score", 0))


def _destination_issue(state: AgentState) -> str | None:
    if state.constraints.get("task_type") in {"errand", "meal", "todo"}:
        return None
    validation = (state.final_plan or {}).get("destination_validation") or _validate_destination_plan(
        state,
        (state.final_plan or {}).get("itinerary") or [],
    )
    if validation.get("passed") is False:
        return validation.get("reason") or "计划目的地与用户目标不符"
    if state.constraints.get("route_scope") == "cross_city_trip":
        access_route = (state.final_plan or {}).get("access_route") or {}
        if not access_route.get("needed"):
            return "缺少从出发地到目的地的到达路线"
    return None


def _validate_destination_plan(state: AgentState, itinerary: list[dict]) -> dict[str, Any]:
    destination = state.constraints.get("destination") or {}
    destination_name = destination.get("name") or state.constraints.get("destination_place")
    if not destination_name:
        return {"passed": True, "matched": []}
    if destination.get("type") == "city":
        city = destination.get("city") or destination_name
        if city in {state.constraints.get("city"), state.constraints.get("destination_city")} and itinerary:
            matched = [item.get("place") for item in itinerary if item.get("place") and not _is_city_name(str(item.get("place")), str(city))]
            if matched:
                return {"passed": True, "matched": list(dict.fromkeys(matched))}
    aliases = _place_aliases(destination_name)
    if destination.get("raw"):
        aliases.extend(_place_aliases(str(destination["raw"])))
    if destination.get("city"):
        aliases.append(str(destination["city"]))
    matched = []
    for item in itinerary:
        text = " ".join(str(item.get(key, "")) for key in ["place", "area", "address"])
        if any(alias and alias in text for alias in aliases):
            matched.append(item.get("place"))
    if matched:
        return {"passed": True, "matched": list(dict.fromkeys(matched))}
    return {
        "passed": False,
        "matched": [],
        "reason": f"计划目的地与用户目标不符：用户想去{destination_name}，但行程没有安排该目的地或其周边点位",
    }


def _meal_candidates(foods: list[dict[str, Any]], constraints: dict[str, Any]) -> list[dict[str, Any]]:
    budget = constraints.get("budget")
    city = constraints.get("city") or constraints.get("destination_city") or constraints.get("default_city")
    result = []
    for index, food in enumerate(foods[:12]):
        item = _normalize_task_place(food, food.get("name") or "餐饮候选", int(food.get("duration_minutes") or 75), index)
        item["tags"] = list(dict.fromkeys((item.get("tags") or []) + ["美食"]))
        item["reason"] = _meal_reason(item, budget)
        result.append(item)
    return sorted(result, key=lambda item: _meal_priority(item, str(city or "")), reverse=True)[:8]


def _meal_reason(item: dict[str, Any], budget: int | None) -> str:
    if _is_national_chain_meal(item):
        return "标准连锁火锅候选，稳定但不作为本地特色优先推荐"
    if _meal_local_score(item) >= 6:
        return "更贴近本地火锅/特色餐饮体验，适合作为优先候选"
    price = int(item.get("estimated_cost") or 0)
    if budget and price and price <= max(80, budget * 0.5):
        return "预算内优先候选，适合作为本次正餐"
    return "餐饮地点候选，价格/排队需要出发前确认"


def _meal_priority(item: dict[str, Any], city: str) -> tuple[int, int, int, int]:
    text = _meal_text(item)
    tags = set(item.get("tags") or [])
    score = _meal_local_score(item)
    if city and city in text:
        score += 4
    if "火锅" in text or "火锅" in tags:
        score += 8
    if "美食" in tags:
        score += 2
    score -= sum(14 for word in NATIONAL_CHAIN_MEAL_WORDS if word in text)
    return score, int(bool(item.get("location"))), -int(item.get("estimated_cost") or 0), -int(item.get("source_order") or 0)


def _place_aliases(place_name: str) -> list[str]:
    aliases = [part for part in re.split(r"[·\-（）()]", place_name) if len(part) >= 2]
    for keyword in _all_popular_keywords():
        if keyword in place_name:
            aliases.append(keyword)
    suffix_removed = re.sub(r"(风景区|旅游度假区|景区|公园|博物馆|美术馆|夜景|店)$", "", place_name)
    if len(suffix_removed) >= 2:
        aliases.append(suffix_removed)
    return list(dict.fromkeys(aliases))


def _is_iconic_place(place: dict[str, Any]) -> bool:
    name = place.get("name", "")
    city = place.get("city")
    keywords = POPULAR_PLACE_KEYWORDS_BY_CITY.get(city, []) + _all_popular_keywords()
    return any(keyword in name for keyword in keywords)


def _local_popularity_score(place: dict[str, Any]) -> int:
    score = 14 if _is_iconic_place(place) else 0
    rating = place.get("rating")
    try:
        rating_value = float(rating)
    except (TypeError, ValueError):
        rating_value = 0
    if rating_value >= 4.6:
        score += 8
    elif rating_value >= 4.2:
        score += 5
    return score
