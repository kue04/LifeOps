"""计划构建：按任务类型生成出行/待办/餐饮/混合计划的完整结构。

从 agent/nodes.py 整组搬迁，闭包自洽，不依赖其他 Agent 节点。
"""

from __future__ import annotations

import json
import math
from typing import Any

from agent.guide_messages import (
    _guide_place_candidates,
)
from agent.intent import (
    _extract_errand_items,
    _looks_like_travel_request,
    _parse_todo_goal,
)
from agent.intent_signals import (
    _dynamic_city,
    _required_outputs_for_subtasks,
    _uniquely_covers_preference,
)
from agent.place_utils import (
    _match_place_for_errand,
    _normalize_task_place,
    _place_mix_category,
)
from agent.prompts import PLANNER_PROMPT
from agent.scoring import (
    _meal_candidates,
    _validate_destination_plan,
)
from agent.state import AgentState
from agent.text_utils import (
    _confirm_actions_for,
    _dedupe_execution_steps,
    _dedupe_sub_tasks,
    _dedupe_text_parts,
    _extract_famous_destination,
    _has_errand_intent,
    _has_meal_intent,
    _has_todo_intent,
    _intent_has,
    _llm_enabled,
    _mixed_item_reason,
    _recommendation_basis,
    _summary,
    _time_label,
)
from agent.timeline import _timeline_from_errands, _timeline_from_meals, _timeline_from_todos
from services.llm_client import llm_client
from tools.budget import estimate_budget
from tools.route import estimate_route


def _build_intent_contract(state: AgentState, llm_constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    text = state.user_input
    llm_constraints = llm_constraints or {}
    sub_tasks = _infer_sub_tasks(text, state.constraints)
    hard_constraints = {
        key: state.constraints.get(key)
        for key in ["city", "destination", "origin", "date", "date_iso", "time_window", "budget", "pace", "route_scope"]
        if state.constraints.get(key) not in (None, "", [])
    }
    soft_preferences = {
        "preferences": state.constraints.get("preferences", []),
        "avoid": state.constraints.get("avoid", []),
        "companions": llm_constraints.get("companions"),
    }
    required_outputs = _required_outputs_for_subtasks(sub_tasks)
    missing_fields = list(llm_constraints.get("missing_fields") or [])
    return {
        "goal": state.goal or llm_constraints.get("goal") or _infer_goal(text, state.constraints.get("city")),
        "primary_task_type": state.constraints.get("task_type") or "unknown",
        "sub_tasks": sub_tasks,
        "hard_constraints": hard_constraints,
        "soft_preferences": soft_preferences,
        "required_outputs": required_outputs,
        "missing_fields": missing_fields,
    }


def _infer_sub_tasks(text: str, constraints: dict[str, Any]) -> list[dict[str, Any]]:
    sub_tasks: list[dict[str, Any]] = []
    if _has_errand_intent(text):
        sub_tasks.append({"type": "errand", "label": "跑腿/顺路事项", "source": "rule"})
    if _has_meal_intent(text):
        sub_tasks.append({"type": "meal", "label": "餐饮安排", "source": "rule"})
    if _has_todo_intent(text):
        sub_tasks.append({"type": "todo", "label": "待办拆解", "source": "rule"})
    has_non_travel_life_task = any(item.get("type") in {"errand", "meal", "todo"} for item in sub_tasks)
    destination = constraints.get("destination") or {}
    has_specific_destination = bool(destination and destination.get("type") not in {"city", "district"})
    if _looks_like_travel_request(text) or has_specific_destination or (constraints.get("activity_area") and not has_non_travel_life_task):
        sub_tasks.append({"type": "travel", "label": "出行/游玩路线", "source": "rule"})
    if not sub_tasks:
        task_type = constraints.get("task_type") if constraints.get("task_type") in {"travel", "errand", "meal", "todo"} else "todo"
        sub_tasks.append({"type": task_type, "label": "生活任务规划", "source": "fallback"})
    return _dedupe_sub_tasks(sub_tasks)


def _build_execution_plan(state: AgentState) -> list[dict[str, Any]]:
    contract = state.intent_contract or _build_intent_contract(state)
    task_types = {item.get("type") for item in contract.get("sub_tasks", [])}
    steps: list[dict[str, Any]] = []
    if "todo" in task_types:
        steps.append({"tool": "todo_decompose", "purpose": "拆解待办和完成标准"})
    if task_types.intersection({"travel", "errand", "meal"}):
        if "travel" in task_types:
            steps.append({"tool": "weather", "purpose": "判断天气和室内外风险"})
        steps.append({"tool": "place_search", "purpose": "查找可导航地点候选"})
        if "travel" in task_types:
            steps.append({"tool": "search", "purpose": "补充网页来源和近期信息"})
        if "meal" in task_types:
            steps.append({"tool": "meal_pick", "purpose": "筛选餐饮候选"})
        if "errand" in task_types:
            steps.append({"tool": "errand_parse", "purpose": "整理跑腿事项"})
        steps.append({"tool": "route", "purpose": "估算路线和顺路顺序"})
        steps.append({"tool": "budget", "purpose": "估算预算"})
    steps.append({"tool": "confirm_action", "purpose": "列出需要用户确认的外部动作"})
    return _dedupe_execution_steps(steps)


def _build_plan_steps(state: AgentState) -> list[dict[str, Any]]:
    task_type = state.constraints.get("task_type") or "travel"
    if task_type == "todo":
        return [
            {"step": "识别目标和约束", "tool": "rule_parser"},
            {"step": "拆解待办任务", "tool": "todo_decomposer"},
            {"step": "安排时间块", "tool": "time_block_planner"},
            {"step": "生成完成标准", "tool": "acceptance_criteria"},
            {"step": "列出需要确认的提醒/日历动作", "tool": "confirm_action_builder"},
        ]
    if task_type == "errand":
        return [
            {"step": "识别跑腿事项", "tool": "rule_parser"},
            {"step": "查询可用地点候选", "tool": "place_search_tool"},
            {"step": "估算顺路路线", "tool": "route_tool"},
            {"step": "估算交通和餐饮预算", "tool": "budget_tool"},
            {"step": "生成顺路时间轴", "tool": "plan_generator"},
            {"step": "列出需要确认的外部动作", "tool": "confirm_action_builder"},
        ]
    if task_type == "meal":
        return [
            {"step": "识别餐饮预算、口味和距离偏好", "tool": "rule_parser"},
            {"step": "查询餐饮地点候选", "tool": "place_search_tool"},
            {"step": "估算路线和预算", "tool": "route_tool/budget_tool"},
            {"step": "生成餐饮候选和推荐理由", "tool": "plan_generator"},
            {"step": "列出需要确认的订座/排队动作", "tool": "confirm_action_builder"},
        ]
    fallback_steps = [
        {"step": "读取用户偏好（旅行请求仅作辅助，不覆盖当次约束）", "tool": "memory_tool"},
        {"step": "查询天气", "tool": "weather_tool"},
        {"step": "用地图工具查询真实地点、地址和可跳转链接", "tool": "place_search_tool"},
        {"step": "网页搜索目的地天气、景点、近期活动、免费玩法和攻略", "tool": "web_search_tool"},
        {"step": "估算路线", "tool": "route_tool"},
        {"step": "估算预算", "tool": "budget_tool"},
        {"step": "生成一日计划", "tool": "plan_generator"},
        {"step": "检查风险", "tool": "risk_checker"},
        {"step": "反思计划质量", "tool": "reflection"},
    ]
    if not _llm_enabled():
        return fallback_steps
    try:
        result = llm_client.json_complete(
            PLANNER_PROMPT,
            json.dumps({"constraints": state.constraints, "goal": state.goal, "user_input": state.user_input}, ensure_ascii=False),
        )
        if isinstance(result.get("steps"), list) and result["steps"]:
            return result["steps"]
    except Exception:
        pass
    return fallback_steps


def _build_rule_based_plan(state: AgentState, route: dict, budget: dict) -> dict[str, Any]:
    itinerary = []
    trip_days = int(state.constraints.get("trip_days") or 1)
    places_per_day = max(1, math.ceil(len(route["ordered_places"]) / max(trip_days, 1)))
    current_day = 1
    current_minutes = 9 * 60 + 30
    legs = route.get("legs", [])
    for index, place in enumerate(route["ordered_places"]):
        day = min(trip_days, index // places_per_day + 1)
        if day != current_day:
            current_day = day
            current_minutes = 9 * 60 + 30
        travel_minutes = legs[index]["minutes"] if index < len(legs) else 20
        current_minutes += max(10, int(travel_minutes))
        start = _time_label(current_minutes)
        current_minutes += place["duration_minutes"]
        end = _time_label(current_minutes)
        itinerary.append({
            "day": day,
            "time": f"{start}-{end}",
            "place": place["name"],
            "area": place["area"],
            "address": place.get("address"),
            "location": place.get("location"),
            "map_url": place.get("map_url"),
            "source_url": place.get("source_url"),
            "source_title": place.get("source_title"),
            "play_points": place.get("play_points", []),
            "cost_note": place.get("cost_note"),
            "cost_known": place.get("cost_known", False),
            "evidence": place.get("evidence", []),
            "reason": "；".join(place.get("score_reasons", [])[:2]) or "综合评分较高",
            "cost": place["estimated_cost"],
            "tags": place["tags"],
        })
    destination_name = (state.constraints.get("destination") or {}).get("name") or state.constraints.get("destination_place")
    title_place = destination_name or state.constraints.get("city", "本地")
    validation = _validate_destination_plan(state, itinerary)
    access_route = route.get("access_route") or {}
    return {
        "task_type": "travel",
        "title": f"{title_place}一日计划",
        "goal": state.goal,
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "trip_days": trip_days,
        "origin": state.constraints.get("origin"),
        "destination": state.constraints.get("destination"),
        "access_route": access_route,
        "local_route": {"ordered_places": route["ordered_places"], "legs": route["legs"], "travel_minutes": route.get("travel_minutes")},
        "destination_validation": validation,
        "weather": state._weather,  # type: ignore[attr-defined]
        "travel_research": state._travel_research,  # type: ignore[attr-defined]
        "lifestyle_places": state._lifestyle_places,  # type: ignore[attr-defined]
        "itinerary": itinerary,
        "alternatives": _build_alternatives(state.candidates, route["ordered_places"]),
        "recommendation_basis": _recommendation_basis(state, route["ordered_places"], state.candidates),
        "guide_places": _guide_place_candidates(state.artifacts.get("places") or getattr(state, "_places", [])),
        "route": route["legs"],
        "budget": budget,
        "summary": _summary(itinerary, budget, access_route),
    }


def _build_dynamic_plan(state: AgentState) -> dict[str, Any]:
    if not state.intent_contract:
        state.intent_contract = _build_intent_contract(state)
    task_types = {item.get("type") for item in state.intent_contract.get("sub_tasks", [])}
    if task_types == {"todo"}:
        return _build_todo_plan(state)
    if task_types == {"meal"}:
        return _build_meal_plan(state)
    if task_types == {"errand"}:
        return _build_errand_plan(state)
    if task_types == {"travel"}:
        return _build_dynamic_travel_plan(state)
    return _build_mixed_plan(state, task_types)


def _build_dynamic_travel_plan(state: AgentState) -> dict[str, Any]:
    route = state.artifacts.get("route") or {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    budget = state.artifacts.get("budget") or estimate_budget(route.get("ordered_places", []), state.constraints.get("budget"), state.constraints.get("pace"))
    if route.get("ordered_places"):
        plan = _build_rule_based_plan(state, route, budget)
    else:
        plan = _build_errand_plan(state) if _has_errand_intent(state.user_input) else _build_todo_plan(state)
        plan["task_type"] = "travel"
    plan["intent_contract"] = state.intent_contract
    plan["execution_plan"] = state.execution_plan
    return plan


def _build_mixed_plan(state: AgentState, task_types: set[str]) -> dict[str, Any]:
    route = state.artifacts.get("route") or {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    budget = state.artifacts.get("budget") or estimate_budget(route.get("ordered_places", []), state.constraints.get("budget"), state.constraints.get("pace"))
    itinerary = _mixed_itinerary_from_artifacts(state, route)
    errand_items = state.artifacts.get("errand_items") or (_extract_errand_items(state.user_input) if "errand" in task_types else [])
    meal_candidates = state.artifacts.get("meal_candidates") or []
    todo_parse = state.artifacts.get("todo") or (_parse_todo_goal(state.user_input) if "todo" in task_types else {})
    travel_research = state.artifacts.get("travel_research") or getattr(state, "_travel_research", {"provider": "none", "sources": [], "note": "动态计划未调用网页搜索"})
    weather = state.artifacts.get("weather") or getattr(state, "_weather", {})
    actions = state.artifacts.get("confirm_actions") or []
    title_city = _dynamic_city(state) or "本地"
    plan = {
        "task_type": "mixed",
        "title": f"{title_city}综合生活计划",
        "goal": state.intent_contract.get("goal") or state.goal,
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "weather": weather,
        "travel_research": travel_research,
        "itinerary": itinerary,
        "errand_items": errand_items,
        "meal_candidates": meal_candidates,
        "todo_items": todo_parse.get("tasks", []),
        "time_blocks": todo_parse.get("time_blocks", []),
        "acceptance_criteria": todo_parse.get("acceptance_criteria", []),
        "lifestyle_places": state.artifacts.get("lifestyle_places") or getattr(state, "_lifestyle_places", {"foods": meal_candidates, "hotels": []}),
        "route": route.get("legs", []),
        "local_route": route,
        "access_route": route.get("access_route"),
        "budget": budget,
        "confirm_actions": actions,
        "alternatives": _build_alternatives(state.candidates, route.get("ordered_places", [])) if state.candidates else [],
        "recommendation_basis": _recommendation_basis(state, route.get("ordered_places", []), state.candidates) if state.candidates else {},
        "guide_places": _guide_place_candidates(state.artifacts.get("places") or getattr(state, "_places", [])),
        "summary": _mixed_summary(state, task_types, itinerary, budget),
        "intent_contract": state.intent_contract,
        "execution_plan": state.execution_plan,
    }
    return plan


def _mixed_itinerary_from_artifacts(state: AgentState, route: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = route.get("ordered_places") or []
    legs = route.get("legs") or []
    if ordered:
        timeline = []
        current = 9 * 60
        for index, place in enumerate(ordered):
            travel = legs[index].get("minutes", 15) if index < len(legs) else 15
            current += int(travel)
            start = _time_label(current)
            current += int(place.get("duration_minutes") or 45)
            timeline.append({
                "time": f"{start}-{_time_label(current)}",
                "place": place.get("name"),
                "area": place.get("area"),
                "address": place.get("address"),
                "location": place.get("location"),
                "map_url": place.get("map_url"),
                "play_points": place.get("play_points") or ["按顺路顺序执行"],
                "reason": _mixed_item_reason(place),
                "cost": place.get("estimated_cost", 0),
                "cost_known": place.get("cost_known", False),
                "cost_note": place.get("cost_note"),
                "tags": place.get("tags", []),
            })
        return timeline
    if _intent_has(state, "todo"):
        return _timeline_from_todos((state.artifacts.get("todo") or {}).get("tasks", []))
    return []


def _mixed_summary(state: AgentState, task_types: set[str], itinerary: list[dict[str, Any]], budget: dict[str, Any]) -> str:
    city = _dynamic_city(state) or "本地"
    food_tags = {"美食", "火锅", "川菜", "小吃", "茶馆"}
    travel_names = _dedupe_text_parts(
        item.get("place")
        for item in itinerary
        if not set(item.get("tags") or []).intersection(food_tags)
    )
    meal_names = _dedupe_text_parts(
        item.get("name")
        for item in (state.artifacts.get("meal_candidates") or [])
    )
    total = budget.get("total")
    budget_text = f"，预计 {total} 元" if isinstance(total, (int, float)) else ""
    if "travel" in task_types and "meal" in task_types:
        route_text = "、".join(travel_names[:3]) if travel_names else f"{city}核心景点"
        meal_text = "、".join(meal_names[:2]) if meal_names else f"{city}本地餐饮"
        return f"这是一条{city}游玩加用餐路线：先逛{route_text}，再把{meal_text}作为用餐候选{budget_text}；订座、付款和提醒只生成待确认动作。"
    if "errand" in task_types or "todo" in task_types:
        names = _dedupe_text_parts(item.get("place") for item in itinerary)
        task_text = "、".join(names[:3]) if names else "这些事项"
        return f"这是一条{city}综合执行路线：按顺路顺序处理{task_text}{budget_text}；外部动作只生成待确认项。"
    return f"这是一条{city}综合计划，共 {len(itinerary)} 个时间节点{budget_text}；外部动作只生成待确认项。"


def _build_errand_plan(state: AgentState) -> dict[str, Any]:
    items = _extract_errand_items(state.user_input)
    city = state.constraints.get("city") or state.constraints.get("default_city") or "本地"
    candidate_places = _errand_candidate_places(items, getattr(state, "_places", []))
    route_data = estimate_route(candidate_places) if candidate_places else {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    budget = estimate_budget(route_data.get("ordered_places", []), state.constraints.get("budget"), state.constraints.get("pace"))
    itinerary = _timeline_from_errands(items, route_data.get("ordered_places", []), route_data.get("legs", []))
    return {
        "task_type": "errand",
        "title": f"{city}跑腿顺路计划",
        "goal": state.goal or "安排生活跑腿",
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "weather": getattr(state, "_weather", {}),
        "travel_research": getattr(state, "_travel_research", {"sources": []}),
        "errand_items": items,
        "itinerary": itinerary,
        "route": route_data.get("legs", []),
        "local_route": route_data,
        "budget": budget,
        "confirm_actions": _confirm_actions_for("errand", items),
        "summary": "已按取、买、寄、办、送、用餐等事项生成顺路时间轴；具体店铺、营业时间和寄送/支付动作需要你确认后再执行。",
    }


def _build_meal_plan(state: AgentState) -> dict[str, Any]:
    city = state.constraints.get("city") or state.constraints.get("default_city") or "本地"
    lifestyle = getattr(state, "_lifestyle_places", {"foods": [], "hotels": []})
    foods = lifestyle.get("foods") or [
        place for place in getattr(state, "_places", []) if "美食" in place.get("tags", [])
    ]
    meal_candidates = _meal_candidates(foods, state.constraints)
    selected = meal_candidates[:3]
    route_data = estimate_route(selected) if selected else {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    budget = estimate_budget(selected, state.constraints.get("budget"), state.constraints.get("pace"))
    itinerary = _timeline_from_meals(selected, route_data.get("legs", []))
    return {
        "task_type": "meal",
        "title": f"{city}餐饮计划",
        "goal": state.goal or "安排餐饮选择",
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "weather": getattr(state, "_weather", {}),
        "travel_research": getattr(state, "_travel_research", {"sources": []}),
        "meal_candidates": meal_candidates,
        "lifestyle_places": {"foods": meal_candidates, "hotels": lifestyle.get("hotels", [])},
        "itinerary": itinerary,
        "route": route_data.get("legs", []),
        "local_route": route_data,
        "budget": budget,
        "confirm_actions": _confirm_actions_for("meal", meal_candidates[:1]),
        "summary": "已按预算、口味和距离优先给出餐饮候选；订座、排队取号、支付和发送消息都只作为待确认动作。",
    }


def _build_todo_plan(state: AgentState) -> dict[str, Any]:
    parsed = getattr(state, "_todo_parse", _parse_todo_goal(state.user_input))
    tasks = parsed.get("tasks", [])
    return {
        "task_type": "todo",
        "title": "待办拆解计划",
        "goal": parsed.get("goal") or state.goal or "拆解目标",
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "travel_research": {"provider": "none", "sources": [], "note": "todo 场景不调用地图/天气"},
        "itinerary": _timeline_from_todos(tasks),
        "todo_items": tasks,
        "time_blocks": parsed.get("time_blocks", []),
        "acceptance_criteria": parsed.get("acceptance_criteria", []),
        "budget": {"activity_cost": 0, "meal_budget": 0, "transport_budget": 0, "total": 0, "budget_limit": state.constraints.get("budget"), "budget_usage": 0},
        "confirm_actions": _confirm_actions_for("todo", tasks),
        "summary": "已拆成可执行任务、时间块和完成标准；提醒和日历写入只生成待确认动作，不会自动执行。",
    }


def _improve_budget_fit(selected: list[dict], candidates: list[dict], constraints: dict, avoid: set[str]) -> list[dict]:
    budget = constraints.get("budget")
    if not budget or budget < 300 or len(selected) >= 4:
        return selected
    target_activity = max(0, int(budget * 0.35))
    current = sum(int(item.get("estimated_cost", 0)) for item in selected)
    requested = set(constraints.get("preferences") or [])
    covered = set().union(*(set(item.get("tags", [])) for item in selected)) if selected else set()
    if requested and requested.issubset(covered):
        return selected
    if current >= target_activity * 0.6:
        return selected
    selected_names = {item["name"] for item in selected}
    paid_candidates = [
        item
        for item in candidates
        if item["name"] not in selected_names
        and int(item.get("estimated_cost", 0)) > 0
        and avoid.isdisjoint(item.get("tags", []))
    ]
    if not paid_candidates:
        return selected
    replacement = max(paid_candidates, key=lambda item: (item.get("score", 0), item.get("estimated_cost", 0)))
    if len(selected) < 3:
        return selected + [replacement]
    replaceable_indexes = [
        index
        for index, item in enumerate(selected)
        if not _uniquely_covers_preference(item, selected, requested)
    ]
    if not replaceable_indexes:
        return selected
    cheapest_index = min(replaceable_indexes, key=lambda index: int(selected[index].get("estimated_cost", 0)))
    improved = selected[:]
    improved[cheapest_index] = replacement
    return improved


def _build_alternatives(candidates: list[dict], selected: list[dict]) -> list[dict]:
    selected_names = {item["name"] for item in selected}
    alternatives = []
    category_counts: dict[str, int] = {}
    for candidate in candidates:
        if candidate["name"] in selected_names:
            continue
        category = _place_mix_category(candidate)
        if category in {"museum", "park"} and category_counts.get(category, 0) >= 1:
            continue
        if category_counts.get(category, 0) >= 2:
            continue
        alternatives.append({
            "name": candidate["name"],
            "address": candidate.get("address"),
            "map_url": candidate.get("map_url"),
            "play_points": candidate.get("play_points", []),
            "tags": candidate.get("tags", []),
            "evidence": candidate.get("evidence", []),
        })
        category_counts[category] = category_counts.get(category, 0) + 1
        if len(alternatives) >= 6:
            break
    return alternatives


def _errand_candidate_places(items: list[dict[str, Any]], places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(items):
        match = _match_place_for_errand(item, places)
        result.append(_normalize_task_place(match, item["title"], item.get("duration_minutes", 35), index))
    return result


def _infer_goal(text: str, city: str | None) -> str:
    destination = _extract_famous_destination(text)
    if destination:
        return f"规划{destination['place']}游玩路线"
    if any(word in text for word in ["玩", "一天", "周末"]):
        return f"规划{city or '目标城市'}生活出行"
    if any(word in text for word in ["取快递", "买", "办事", "跑腿"]):
        return "安排生活跑腿"
    return "规划生活任务"
