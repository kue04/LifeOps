from __future__ import annotations

import re
from typing import Any

from agent.constants import (
    PREFERENCE_WORDS,
    TASK_TYPES,
)
from agent.guide_messages import (
    _build_assistant_message,
)
from agent.intent import (
    _extract_avoid,
    _extract_city_hint,
    _extract_errand_items,
    _extract_place_names_from_search,
    _extract_place_roles,
    _extract_with_llm,
    _looks_like_travel_request,
    _parse_todo_goal,
)
from agent.intent_signals import (
    _allowed_dynamic_tools,
    _dynamic_city,
    _is_mixed_intent,
    _is_travel_guide_plan,
    _legacy_tool_name,
    _reflection_is_final,
    _reflection_issues,
    _remove_avoided_preferences,
)
from agent.place_selection import (
    _ensure_city_trip_places,
    _ensure_place_locations,
    _filter_travel_places,
    _is_broad_city_sightseeing_request,
    _is_relevant_to_place,
    _select_places,
)
from agent.place_utils import (
    _city_guide_search_batches,
    _city_travel_search_preferences,
    _dedupe_places,
    _estimate_access_route_if_needed,
    _lifestyle_search_batches,
    _meal_search_words,
    _mentions_current_area,
)
from agent.plan_builders import (
    _build_dynamic_plan,
    _build_execution_plan,
    _build_intent_contract,
    _errand_candidate_places,
    _infer_goal,
)
from agent.scoring import (
    _meal_candidates,
    _travel_priority,
    check_risks_node,
    reflect,
)
from agent.search import (
    _build_travel_research,
    _search_web_for_travel,
    _travel_preferences,
)
from agent.state import AgentState
from agent.text_utils import (
    _artifact_summary,
    _budget_preview,
    _budget_summary,
    _confirm_actions_for,
    _constrain_mixed_budget,
    _extract_current_location,
    _extract_lifestyle_places,
    _extract_pace,
    _extract_trip_days,
    _filter_places_by_city,
    _first_match,
    _has_meal_intent,
    _intent_has,
    _llm_model_name,
    _log,
    _places_preview,
    _route_preview,
    _route_summary,
    _weather_summary,
    _with_quality_warning,
)
from agent.timeline import (
    _annotate_places_for_goal,
)
from agent.tool_router import (
    _build_search_query,
    _call_life_task_tools,
    _emit_tool_event,
    _enrich_places_with_search_evidence,
    _prepend_destination_places,
    _tool_result,
    travel_tool_router,
)
from services.date_resolver import resolve_date_text
from services.scorer import score_candidates
from tools.budget import estimate_budget
from tools.memory import load_user_profile
from tools.places import search_places
from tools.route import estimate_route
from tools.weather import get_weather

# 对外公开的图节点入口。graph.py 通过 `from agent.nodes import ...` 消费，
# 即使实现已搬迁到子模块，这些名字也必须保留在本模块命名空间中。
__all__ = [
    "check_clarification",
    "check_risks_node",
    "execute_plan",
    "extract_constraints",
    "final_response",
    "load_memory",
    "normalize_dates",
    "plan_steps",
    "reflect",
    "synthesize_plan",
]


def extract_constraints(state: AgentState) -> AgentState:
    text = state.user_input
    llm_constraints = _extract_with_llm(text)
    if llm_constraints.pop("_llm_used", False):
        state.llm_usage.append({"node": "constraint_extractor", "status": "success", "model": _llm_model_name()})

    budget_match = re.search(r"预算\s*(\d+)|(\d+)\s*元|控制在\s*(\d+)", text)
    budget = next((int(item) for item in budget_match.groups() if item), None) if budget_match else None
    place_roles = _extract_place_roles(text, llm_constraints, state.constraints)
    destination_role = place_roles.get("destination")
    origin_role = place_roles.get("origin")
    activity_area = place_roles.get("activity_area") or {}
    text_city = _extract_city_hint(text)
    city = (
        (destination_role or {}).get("city")
        or activity_area.get("city")
        or text_city
        or (origin_role or {}).get("city")
        or state.constraints.get("default_city")
    )
    date = _first_match(text, ["今天", "明天", "后天", "本周六", "本周日", "下周六", "下周日", "周六", "周日", "周末"])
    pace = _extract_pace(text)
    avoid = _extract_avoid(text)
    current_location = _extract_current_location(text) or (
        state.constraints.get("origin_location") if _mentions_current_area(text) else None
    )
    llm_avoid = llm_constraints.get("avoid") or []
    avoid = list(dict.fromkeys(avoid + llm_avoid))
    explicit_preferences = [word for word in PREFERENCE_WORDS if word in text and word not in avoid]
    if "看展" in text and "展览" not in explicit_preferences and "展览" not in avoid:
        explicit_preferences.append("展览")
    raw_preferences = explicit_preferences or ([] if _looks_like_travel_request(text) else llm_constraints.get("preferences") or [])
    preferences = _remove_avoided_preferences(raw_preferences, avoid)

    if "太贵" in text or "控制在" in text:
        state.replan_count += 1

    task_type = _infer_task_type(text, llm_constraints, state.constraints)
    if task_type == "meal" and "美食" not in preferences and "美食" not in avoid:
        preferences = list(dict.fromkeys(preferences + ["美食"]))
    state.goal = llm_constraints.get("goal") or _infer_goal_from_roles(text, city, place_roles)
    hotel_brand = "汉庭" if "汉庭" in text else None
    updates = {
        "task_type": task_type,
        "city": city or llm_constraints.get("city"),
        "origin": origin_role,
        "destination": destination_role,
        "activity_area": place_roles.get("activity_area"),
        "via_points": place_roles.get("via_points"),
        "route_scope": place_roles.get("route_scope") if place_roles.get("route_scope") != "unknown" else ("city_trip" if city else None),
        "activity_intent": place_roles.get("activity_intent"),
        "destination_city": (destination_role or {}).get("city"),
        "destination_place": (destination_role or {}).get("name"),
        "destination_type": (destination_role or {}).get("type"),
        "origin_city": (origin_role or {}).get("city") or state.constraints.get("origin_city"),
        "origin_location": current_location,
        "date": date or llm_constraints.get("date"),
        "time_window": llm_constraints.get("time_window") or ("全天" if any(word in text for word in ["一天", "全天"]) else None),
        "budget": budget or llm_constraints.get("budget"),
        "pace": pace or llm_constraints.get("pace"),
        "preferences": preferences,
        "avoid": avoid,
        "hotel_brand": llm_constraints.get("hotel_brand") or hotel_brand,
        "trip_days": llm_constraints.get("trip_days") or _extract_trip_days(text),
    }
    for key, value in updates.items():
        if value not in (None, [], ""):
            state.constraints[key] = value
    state.intent_contract = _build_intent_contract(state, llm_constraints)

    _log(state, "intent_extraction", f"识别到任务：{state.goal or '生活规划'}", {
        "task_type": task_type,
        "missing_fields": llm_constraints.get("missing_fields", []),
        "confidence": llm_constraints.get("confidence", 0),
    })
    return state


def normalize_dates(state: AgentState) -> AgentState:
    resolved = resolve_date_text(state.constraints.get("date"))
    for key, value in resolved.items():
        if value:
            state.constraints[key] = value
    _log(state, "date_resolver", "将相对日期转换为具体日期", {
        "input": state.constraints.get("date"),
        "date_iso": state.constraints.get("date_iso"),
        "date_weekday": state.constraints.get("date_weekday"),
    })
    return state


def load_memory(state: AgentState) -> AgentState:
    state.user_profile = load_user_profile(state.user_id)
    avoid = set(state.constraints.get("avoid", []))
    if (state.constraints.get("task_type") in {None, "travel", "unknown"}
        and not state.constraints.get("preferences")
        and not _looks_like_travel_request(state.user_input)):
        state.constraints["preferences"] = [
            item for item in state.user_profile.get("likes", []) if item not in avoid
        ]
    if not state.constraints.get("pace"):
        state.constraints["pace"] = state.user_profile.get("pace")
    _log(state, "memory_lookup", "读取长期偏好补全当前约束", state.user_profile)
    return state


def check_clarification(state: AgentState) -> AgentState:
    missing = []
    task_type = state.constraints.get("task_type") or "travel"
    has_destination = bool(
        state.constraints.get("destination")
        or state.constraints.get("destination_place")
        or state.constraints.get("activity_area")
        or state.constraints.get("city")
    )
    is_travel_request = _looks_like_travel_request(state.user_input)
    if task_type == "todo":
        required = []
    elif task_type in {"errand", "meal"}:
        required = []
    else:
        required = [] if is_travel_request else [("date", "日期")]
    if task_type != "todo" and not has_destination:
        required.insert(0, ("city", "城市/目的地"))
    if task_type == "unknown" and not is_travel_request:
        required.append(("preferences", "偏好"))
    for key, label in required:
        if key == "city" and has_destination:
            continue
        if not state.constraints.get(key):
            missing.append(label)
    if missing:
        state.need_human_confirm = True
        state.clarification_question = "还需要补充：" + "、".join(missing)
        _log(state, "clarification", "当前信息不足，需要用户补充", {"missing": missing})
    else:
        _log(state, "clarification", "信息足够，继续执行规划", {"missing": []})
    return state


def plan_steps(state: AgentState) -> AgentState:
    state.execution_plan = _build_execution_plan(state)
    state.plan_steps = _execution_plan_to_steps(state.execution_plan)
    _log(state, "planner", "生成本轮动态执行计划", {
        "intent_contract": state.intent_contract,
        "execution_plan": state.execution_plan,
        "steps": state.plan_steps,
    })
    return state


def execute_plan(state: AgentState) -> AgentState:
    state.artifacts = {}
    for step in state.execution_plan or _build_execution_plan(state):
        tool = step.get("tool")
        if tool not in _allowed_dynamic_tools():
            step["status"] = "skipped"
            continue
        step["status"] = "running"
        try:
            _execute_dynamic_step(state, step)
        except Exception:
            step["status"] = "failed"
            state.plan_steps = _execution_plan_to_steps(state.execution_plan)
            raise
        step["status"] = "completed"
    state.plan_steps = _execution_plan_to_steps(state.execution_plan)
    _log(state, "execute_plan", "按意图执行动态工具计划", {
        "execution_plan": state.execution_plan,
        "artifacts": _artifact_summary(state.artifacts),
    })
    return state


def synthesize_plan(state: AgentState) -> AgentState:
    state.final_plan = _build_dynamic_plan(state)
    if state.final_plan is not None:
        state.final_plan.setdefault("intent_contract", state.intent_contract)
        state.final_plan.setdefault("execution_plan", state.execution_plan)
    _log(state, "synthesize_plan", "根据意图合同和工具结果生成计划", {
        "intent_contract": state.intent_contract,
        "result_types": (state.intent_contract or {}).get("required_outputs", []),
        "plan_task_type": state.final_plan.get("task_type") if state.final_plan else None,
        "itinerary_count": len((state.final_plan or {}).get("itinerary") or []),
    })
    return state


def route_task(state: AgentState) -> AgentState:
    task_type = state.constraints.get("task_type") or "travel"
    if task_type not in {"travel", "errand", "meal", "todo"}:
        task_type = "travel"
    state.constraints["task_type"] = task_type
    _log(state, "task_router", "按任务类型选择执行分支", {"task_type": task_type})
    return state


def call_tools(state: AgentState) -> AgentState:
    if state.constraints.get("task_type") == "todo":
        return todo_decomposer(state)
    if state.constraints.get("task_type") in {"errand", "meal"}:
        return _call_life_task_tools(state)
    return travel_tool_router(state)


def todo_decomposer(state: AgentState) -> AgentState:
    parsed = _parse_todo_goal(state.user_input)
    state.tool_results.append(_tool_result("todo_rule_parser", parsed))
    state._weather = {}  # type: ignore[attr-defined]
    state._places = []  # type: ignore[attr-defined]
    state._lifestyle_places = {"foods": [], "hotels": []}  # type: ignore[attr-defined]
    state._search_results = {"provider": "none", "results": [], "note": "todo 场景不调用地图/天气/网页搜索"}  # type: ignore[attr-defined]
    state._travel_research = {"provider": "none", "sources": [], "note": "todo 场景使用规则拆解，不调用外部工具"}  # type: ignore[attr-defined]
    state._todo_parse = parsed  # type: ignore[attr-defined]
    _log(state, "todo_decomposer", "todo 场景跳过地图、天气和搜索工具", {"task_type": "todo", "items_count": len(parsed.get("tasks", []))})
    return state


































def final_response(state: AgentState) -> dict[str, Any]:
    if state.clarification_question:
        return {
            "status": "need_clarification",
            "trace_id": state.trace_id,
            "question": state.clarification_question,
            "constraints": state.constraints,
            "llm_usage": state.llm_usage,
            "execution_log": state.execution_log,
        }

    is_final = _reflection_is_final(state.reflection)
    quality_warnings = [] if is_final else _reflection_issues(state.reflection)
    assistant_message = _build_assistant_message(state)
    if quality_warnings:
        assistant_message = _with_quality_warning(assistant_message, quality_warnings)
    if state.final_plan and _is_travel_guide_plan(state.final_plan):
        state.final_plan["assistant_message"] = assistant_message
        state.final_plan["overview"] = assistant_message
        state.final_plan["summary"] = assistant_message
    _log(state, "final_response", "组装给用户的自然语言回复", {"assistant_message": assistant_message})
    return {
        "status": "success" if is_final else "partial_success",
        "trace_id": state.trace_id,
        "constraints": state.constraints,
        "plan_steps": state.plan_steps,
        "tool_results": state.tool_results,
        "candidates": state.candidates,
        "final_plan": state.final_plan,
        "assistant_message": assistant_message,
        "quality_warnings": quality_warnings,
        "risks": state.risks,
        "fallbacks": state.fallbacks,
        "reflection": state.reflection,
        "llm_usage": state.llm_usage,
        "execution_log": state.execution_log,
    }




























def _execution_plan_to_steps(execution_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "step": item.get("purpose") or item.get("tool"),
            "tool": _legacy_tool_name(item.get("tool")),
            "status": item.get("status", "pending"),
        }
        for item in execution_plan
    ]






def _execute_dynamic_step(state: AgentState, step: dict[str, Any]) -> None:
    tool = str(step.get("tool"))
    if tool == "todo_decompose":
        _dynamic_todo_decompose(state)
    elif tool == "weather":
        _dynamic_weather(state)
    elif tool == "place_search":
        _dynamic_place_search(state)
    elif tool == "search":
        _dynamic_search(state)
    elif tool == "meal_pick":
        _dynamic_meal_pick(state)
    elif tool == "errand_parse":
        _dynamic_errand_parse(state)
    elif tool == "route":
        _dynamic_route(state)
    elif tool == "budget":
        _dynamic_budget(state)
    elif tool == "confirm_action":
        _dynamic_confirm_actions(state)


def _dynamic_todo_decompose(state: AgentState) -> None:
    parsed = _parse_todo_goal(state.user_input)
    state.artifacts["todo"] = parsed
    state._todo_parse = parsed  # type: ignore[attr-defined]
    state.tool_results.append(_tool_result("todo_rule_parser", parsed))
    _emit_tool_event(state, "execute_plan", "todo_decompose", "拆解待办任务", "done", output_summary={"tasks": len(parsed.get("tasks", []))})


def _dynamic_weather(state: AgentState) -> None:
    city = _dynamic_city(state)
    weather = get_weather(city, state.constraints.get("date_iso") or state.constraints.get("date")) if city else {}
    state.artifacts["weather"] = weather
    state._weather = weather  # type: ignore[attr-defined]
    state.tool_results.append(_tool_result("weather_tool", weather))
    _emit_tool_event(state, "execute_plan", "weather_tool", "获取天气", "done", input_data={"city": city}, output_summary=_weather_summary(weather or {}))


def _dynamic_place_search(state: AgentState) -> None:
    city = _dynamic_city(state)
    preferences = state.constraints.get("preferences") or []
    if _intent_has(state, "meal") and "美食" not in preferences:
        preferences = list(dict.fromkeys(preferences + ["美食"]))
    places: list[dict[str, Any]] = []
    search_batches = _place_search_batches(state, preferences)
    if city and _intent_has(state, "travel"):
        search_batches.extend(_city_guide_search_batches(city))
    if city:
        for batch in search_batches:
            places = _dedupe_places(places + search_places(city, batch, state.constraints.get("avoid") or [], state.constraints.get("hotel_brand")))
        if _intent_has(state, "travel"):
            for batch in _lifestyle_search_batches(state):
                places = _dedupe_places(places + search_places(city, batch, state.constraints.get("avoid") or [], state.constraints.get("hotel_brand")))
    places = _prepend_destination_places(places, state)
    if city:
        places = _filter_places_by_city(places, city)
        if _intent_has(state, "travel"):
            places = _ensure_city_trip_places(places, state, city)
    places = _annotate_places_for_goal(places, state)
    lifestyle_places = _extract_lifestyle_places(places)
    state.artifacts["places"] = places
    state.artifacts["lifestyle_places"] = lifestyle_places
    state._places = places  # type: ignore[attr-defined]
    state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
    state.tool_results.append(_tool_result("place_search_tool", places))
    _emit_tool_event(state, "execute_plan", "place_search_tool", "查找地点候选", "done", input_data={"city": city, "preferences": preferences, "search_batches": search_batches + (_lifestyle_search_batches(state) if city and _intent_has(state, "travel") else [])}, output_summary={"places_count": len(places), "food_places_count": len(lifestyle_places.get("foods", [])), "hotel_places_count": len(lifestyle_places.get("hotels", []))}, preview_items=_places_preview(places))


def _place_search_batches(state: AgentState, preferences: list[str]) -> list[list[str]]:
    cleaned = [preference for preference in preferences if preference != "缇庨"]
    if not _intent_has(state, "travel"):
        return [cleaned]
    food_preferences = [preference for preference in cleaned if preference in _meal_search_words()]
    travel_preferences = _travel_preferences(cleaned)
    if _intent_has(state, "meal"):
        return [
            _city_travel_search_preferences(state, travel_preferences),
            food_preferences or ["美食"],
        ]
    if _is_broad_city_sightseeing_request(state):
        return [_city_travel_search_preferences(state, travel_preferences)]
    return [cleaned]


















def _dynamic_search(state: AgentState) -> None:
    query = _build_search_query(state)
    search = _search_web_for_travel(state, query) if query else {"provider": "none", "results": [], "note": "no query"}
    research = _build_travel_research(search)
    places = _enrich_places_with_search_evidence(state.artifacts.get("places", []), search)
    places = _expand_places_from_search_results(places, search, state)
    lifestyle_places = _extract_lifestyle_places(places)
    state.artifacts["search_results"] = search
    state.artifacts["travel_research"] = research
    state.artifacts["places"] = places
    state.artifacts["lifestyle_places"] = lifestyle_places
    state._search_results = search  # type: ignore[attr-defined]
    state._travel_research = research  # type: ignore[attr-defined]
    state._places = places  # type: ignore[attr-defined]
    state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
    state.tool_results.append(_tool_result("web_search_tool", search, input_data={"query": query, "max_results": 10}))
    _log(state, "tool_router", "完成网页信息查询", {
        "search_query": query,
        "search_provider": search.get("provider"),
        "search_results_count": len(search.get("results") or []),
        "research_sources": len(research.get("sources") or []),
    })
    _emit_tool_event(state, "execute_plan", "web_search_tool", "补充网页来源", "done", input_data={"query": query}, output_summary={"sources_count": len(research.get("sources", [])), "web_expanded_places_count": len(places), "food_places_count": len(lifestyle_places.get("foods", [])), "hotel_places_count": len(lifestyle_places.get("hotels", []))})


def _expand_places_from_search_results(places: list[dict[str, Any]], search: dict[str, Any], state: AgentState) -> list[dict[str, Any]]:
    city = _dynamic_city(state)
    if not city or not _intent_has(state, "travel"):
        return places
    names = [
        name for name in _extract_place_names_from_search(search)
        if name not in {place.get("name") for place in places}
    ]
    if not names:
        return places
    try:
        lookup_names = names[:8]
        discovered = search_places(city, lookup_names, state.constraints.get("avoid") or [], state.constraints.get("hotel_brand"))
    except Exception:
        return places
    discovered = [
        place for place in _filter_places_by_city(discovered, city)
        if any(_is_relevant_to_place(name, str(place.get("name", ""))) for name in lookup_names)
    ]
    return _dedupe_places(places + _enrich_places_with_search_evidence(discovered, search))






def _dynamic_meal_pick(state: AgentState) -> None:
    lifestyle = state.artifacts.get("lifestyle_places") or getattr(state, "_lifestyle_places", {"foods": []})
    foods = lifestyle.get("foods") or state.artifacts.get("places", [])
    candidates = _meal_candidates(foods, state.constraints)
    state.artifacts["meal_candidates"] = candidates
    state.candidates = candidates if not state.candidates else state.candidates
    _emit_tool_event(state, "execute_plan", "meal_pick", "筛选餐饮候选", "done", output_summary={"meal_candidates": len(candidates)}, preview_items=_places_preview(candidates))


def _dynamic_errand_parse(state: AgentState) -> None:
    items = _extract_errand_items(state.user_input)
    state.artifacts["errand_items"] = items
    _emit_tool_event(state, "execute_plan", "errand_parse", "整理跑腿事项", "done", output_summary={"items_count": len(items)})


def _dynamic_route(state: AgentState) -> None:
    places = _dynamic_route_places(state)
    route_data = estimate_route(places) if places else {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    if _intent_has(state, "travel"):
        route_data["access_route"] = _estimate_access_route_if_needed(state)
    state.artifacts["route"] = route_data
    state.tool_results.append(_tool_result("route_tool", route_data))
    _emit_tool_event(state, "execute_plan", "route_tool", "估算路线", "done", output_summary=_route_summary(route_data), preview_items=_route_preview(route_data))


def _dynamic_budget(state: AgentState) -> None:
    route_data = state.artifacts.get("route") or {}
    places = route_data.get("ordered_places") or _dynamic_route_places(state)
    budget = estimate_budget(places, state.constraints.get("budget"), state.constraints.get("pace"))
    if _is_mixed_intent(state):
        budget = _constrain_mixed_budget(budget, state.constraints.get("budget"))
    state.artifacts["budget"] = budget
    state.tool_results.append(_tool_result("budget_tool", budget))
    _emit_tool_event(state, "execute_plan", "budget_tool", "估算预算", "done", output_summary=_budget_summary(budget), preview_items=_budget_preview(budget))


def _dynamic_confirm_actions(state: AgentState) -> None:
    actions = []
    if _intent_has(state, "todo"):
        actions.extend(_confirm_actions_for("todo", (state.artifacts.get("todo") or {}).get("tasks", [])))
    if _intent_has(state, "meal"):
        actions.extend(_confirm_actions_for("meal", (state.artifacts.get("meal_candidates") or [])[:1]))
    if _intent_has(state, "errand"):
        actions.extend(_confirm_actions_for("errand", state.artifacts.get("errand_items") or []))
    state.artifacts["confirm_actions"] = actions
    _emit_tool_event(state, "execute_plan", "confirm_action", "生成待确认动作", "done", output_summary={"actions_count": len(actions)})






def _dynamic_route_places(state: AgentState) -> list[dict[str, Any]]:
    places = state.artifacts.get("places") or getattr(state, "_places", [])
    result: list[dict[str, Any]] = []
    if _intent_has(state, "errand"):
        result.extend(_errand_candidate_places(state.artifacts.get("errand_items") or _extract_errand_items(state.user_input), places))
    if _intent_has(state, "travel"):
        travel_preferences = _travel_preferences(state.constraints.get("preferences", []))
        travel_places = _filter_travel_places(places, travel_preferences)
        if _intent_has(state, "meal"):
            travel_places = [
                place for place in travel_places
                if not set(place.get("tags") or []).intersection({"美食", "火锅", "川菜", "小吃", "茶馆"})
            ]
        scored = sorted(score_candidates(travel_places, travel_preferences, state.constraints.get("budget"), state.constraints.get("pace"), state.artifacts.get("weather") or {}), key=_travel_priority, reverse=True)
        state.candidates = scored
        route_constraints = dict(state.constraints)
        route_constraints["preferences"] = travel_preferences
        result.extend(_select_places(scored, route_constraints, state.replan_context))
    if _intent_has(state, "meal"):
        meal_candidates = state.artifacts.get("meal_candidates") or _meal_candidates((state.artifacts.get("lifestyle_places") or {}).get("foods", []), state.constraints)
        result.extend(meal_candidates[:1])
    return _dedupe_places([_ensure_place_locations([item])[0] for item in result if item])
























































































































































































def _infer_task_type(text: str, llm_constraints: dict[str, Any], context: dict[str, Any]) -> str:
    if context.get("task_type") and any(word in text for word in ["太贵", "换", "改", "控制在", "轻松点", "重排"]):
        return "replan"
    if any(word in text.lower() for word in ["todo", "to-do"]) or any(word in text for word in ["待办", "拆解", "拆成", "任务列表", "完成标准", "里程碑", "时间块"]):
        return "todo"
    if any(word in text for word in ["取快递", "拿快递", "寄快递", "寄件", "办事", "办理", "跑腿", "顺路", "送到", "送去", "买药", "买菜", "买礼物"]):
        return "errand"
    if _looks_like_travel_request(text):
        return "travel"
    if _has_meal_intent(text):
        return "meal"
    llm_type = str(llm_constraints.get("task_type") or "").strip()
    mapping = {
        "travel_plan": "travel",
        "errands": "errand",
        "meal_plan": "meal",
        "todo": "todo",
        "replan": "replan",
    }
    if llm_type in mapping:
        return mapping[llm_type]
    if llm_type in TASK_TYPES:
        return llm_type
    return "unknown"






















































def _infer_goal_from_roles(text: str, city: str | None, roles: dict[str, Any]) -> str:
    destination = roles.get("destination") or {}
    if destination.get("name"):
        return f"规划{destination['name']}游玩路线"
    return _infer_goal(text, city)








































































































































