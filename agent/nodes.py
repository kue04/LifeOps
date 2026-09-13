from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

from agent.constants import (
    FAMOUS_DESTINATIONS,
    PREFERENCE_WORDS,
    TASK_TYPES,
)
from agent.guide_messages import (
    _build_assistant_message,
    _build_assistant_message_from_plan,
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
    _covered_preferences,
    _dynamic_city,
    _is_mixed_intent,
    _is_travel_guide_plan,
    _legacy_tool_name,
    _plan_has_enough_city_items,
    _plan_uses_candidate_places,
    _reflection_is_final,
    _reflection_issues,
    _remove_avoided_preferences,
    _text_has_recent_activity_signal,
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
    _city_search_context_terms,
    _city_travel_search_preferences,
    _dedupe_places,
    _destination_tags,
    _estimate_access_route_if_needed,
    _first_place_provider,
    _lifestyle_search_batches,
    _meal_search_words,
    _mentions_current_area,
)
from agent.plan_builders import (
    _build_dynamic_plan,
    _build_errand_plan,
    _build_execution_plan,
    _build_intent_contract,
    _build_meal_plan,
    _build_rule_based_plan,
    _build_todo_plan,
    _errand_candidate_places,
    _infer_goal,
)
from agent.prompts import PLAN_GENERATOR_PROMPT
from agent.scoring import (
    _local_popularity_score,
    _meal_candidates,
    _travel_priority,
    check_risks_node,
    reflect,
)
from agent.search import (
    _build_travel_research,
    _search_query_city,
    _search_query_terms,
    _search_web_for_travel,
    _travel_preferences,
)
from agent.state import AgentState
from agent.text_utils import (
    _artifact_summary,
    _budget_preview,
    _budget_summary,
    _compact_payload,
    _confirm_actions_for,
    _constrain_mixed_budget,
    _dedupe_text_parts,
    _evidence_preview,
    _extract_current_location,
    _extract_lifestyle_places,
    _extract_pace,
    _extract_ticket_price,
    _extract_trip_days,
    _filter_places_by_city,
    _first_match,
    _has_meal_intent,
    _intent_has,
    _llm_enabled,
    _llm_model_name,
    _log,
    _places_preview,
    _route_preview,
    _route_summary,
    _search_preview,
    _search_summary,
    _weather_summary,
    _with_quality_warning,
)
from agent.timeline import (
    _annotate_places_for_goal,
)
from services.date_resolver import resolve_date_text
from services.llm_client import llm_client
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


def errand_tool_router(state: AgentState) -> AgentState:
    return _call_life_task_tools(state)


def meal_tool_router(state: AgentState) -> AgentState:
    return _call_life_task_tools(state)


def travel_tool_router(state: AgentState) -> AgentState:
    destination = state.constraints.get("destination") or {}
    origin = state.constraints.get("origin") or {}
    city = state.constraints.get("destination_city") or destination.get("city") or state.constraints.get("city")
    preferences = state.constraints.get("preferences") or []
    avoid = state.constraints.get("avoid") or []
    date_for_tools = state.constraints.get("date_iso") or state.constraints.get("date")

    _emit_tool_event(
        state,
        "tool_router",
        "weather_tool",
        "正在查询天气",
        "running",
        input_data={"city": city, "date": date_for_tools, "destination": destination.get("name")},
        progress=45,
    )
    weather = _tool_result("weather_tool", get_weather(city, date_for_tools))
    _emit_tool_event(
        state,
        "tool_router",
        "weather_tool",
        "天气查询完成",
        "done",
        input_data={"city": city, "date": date_for_tools, "destination": destination.get("name")},
        output_summary=_weather_summary(weather["data"]),
        preview_items=[_weather_summary(weather["data"])],
        progress=49,
    )

    _emit_tool_event(
        state,
        "tool_router",
        "place_search_tool",
        "正在搜索候选地点",
        "running",
        input_data={"city": city, "destination": destination, "origin": origin, "preferences": preferences, "avoid": avoid, "hotel_brand": state.constraints.get("hotel_brand")},
        progress=52,
    )
    places_raw = search_places(city, preferences, avoid, state.constraints.get("hotel_brand"))
    places_raw = _prepend_destination_places(places_raw, state)
    city_places = _filter_places_by_city(places_raw, city)
    if city_places:
        city_places = _ensure_city_trip_places(city_places, state, city)
    _emit_tool_event(
        state,
        "tool_router",
        "place_search_tool",
        "候选地点搜索完成",
        "done",
        input_data={"city": city, "destination": destination, "preferences": preferences, "avoid": avoid, "hotel_brand": state.constraints.get("hotel_brand")},
        output_summary={
            "provider": _first_place_provider(places_raw),
            "raw_places_count": len(places_raw),
            "city_places_count": len(city_places),
        },
        preview_items=_places_preview(city_places),
        progress=58,
    )

    if not city_places:
        search_data = {
            "provider": "skipped",
            "query": None,
            "results": [],
            "note": "地点搜索未返回真实候选，跳过网页补证据并等待用户补充区域/偏好",
        }
        search = _tool_result("web_search_tool", search_data, input_data={"query": None})
        places: list[dict[str, Any]] = []
        travel_places: list[dict[str, Any]] = []
        lifestyle_places = {"foods": [], "hotels": []}
        places_result = _tool_result("place_search_tool", places)
        state.need_human_confirm = True
        state.clarification_question = f"没有查到 {city} 的真实候选地点。请补充更具体的区域/偏好后再试。"
        state.tool_results.extend([weather, places_result, search])
        state._weather = weather["data"]  # type: ignore[attr-defined]
        state._places = travel_places  # type: ignore[attr-defined]
        state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
        state._search_results = search_data  # type: ignore[attr-defined]
        state._travel_research = _build_travel_research(search_data)  # type: ignore[attr-defined]
        _log(state, "tool_router", "地点搜索未返回真实候选，停止生成正式行程", {
            "weather": weather["data"],
            "places_count": 0,
            "travel_places_count": 0,
            "raw_places_count": len(places_raw),
            "avoid": avoid,
            "origin": origin,
            "destination": destination,
            "route_scope": state.constraints.get("route_scope"),
            "search_provider": search_data.get("provider"),
        })
        return state

    search_query = _build_search_query(state)
    _emit_tool_event(
        state,
        "tool_router",
        "web_search_tool",
        "正在补充网页证据",
        "running",
        input_data={"query": search_query, "max_results": 3},
        progress=60,
    )
    search = _tool_result("web_search_tool", _search_web_for_travel(state, search_query, max_results=10), input_data={"query": search_query, "max_results": 10})
    _emit_tool_event(
        state,
        "tool_router",
        "web_search_tool",
        "网页证据补充完成",
        "done",
        input_data={"query": search_query, "max_results": 3},
        output_summary=_search_summary(search["data"]),
        preview_items=_search_preview(search["data"]),
        progress=64,
    )

    _emit_tool_event(
        state,
        "tool_router",
        "place_evidence_merge",
        "正在把网页证据合并到地点",
        "running",
        input_data={"places_count": len(city_places), "search_results_count": len(search["data"].get("results", []))},
        progress=66,
    )
    places = _annotate_places_for_goal(
        _enrich_places_with_search_evidence(city_places, search["data"]),
        state,
    )
    _emit_tool_event(
        state,
        "tool_router",
        "place_evidence_merge",
        "地点证据合并完成",
        "done",
        input_data={"places_count": len(city_places), "search_results_count": len(search["data"].get("results", []))},
        output_summary={
            "matched_places_count": sum(1 for place in places if place.get("evidence")),
            "sources_count": len(_build_travel_research(search["data"]).get("sources", [])),
        },
        preview_items=_evidence_preview(places),
        progress=68,
    )

    travel_places = _filter_travel_places(places, state.constraints.get("preferences", []))
    lifestyle_places = _extract_lifestyle_places(places)
    places_result = _tool_result("place_search_tool", places)
    _emit_tool_event(
        state,
        "tool_router",
        "place_filter",
        "地点分类和过滤完成",
        "done",
        input_data={"places_count": len(places), "avoid": avoid},
        output_summary={
            "travel_places_count": len(travel_places),
            "food_places_count": len(lifestyle_places.get("foods", [])),
            "hotel_places_count": len(lifestyle_places.get("hotels", [])),
        },
        preview_items=_places_preview(travel_places),
        progress=70,
    )

    state.tool_results.extend([weather, places_result, search])
    state._weather = weather["data"]  # type: ignore[attr-defined]
    state._places = travel_places  # type: ignore[attr-defined]
    state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
    state._search_results = search["data"]  # type: ignore[attr-defined]
    state._travel_research = _build_travel_research(search["data"])  # type: ignore[attr-defined]

    _log(state, "tool_router", "完成天气、地点和实时信息查询", {
        "weather": weather["data"],
        "places_count": len(places),
        "travel_places_count": len(travel_places),
        "raw_places_count": len(places_raw),
        "avoid": avoid,
        "origin": origin,
        "destination": destination,
        "route_scope": state.constraints.get("route_scope"),
        "search_query": search_query,
        "search_provider": search["data"].get("provider"),
        "search_results_count": len(search["data"].get("results", [])),
        "research_sources": len(state._travel_research.get("sources", [])),  # type: ignore[attr-defined]
    })
    return state










def _call_life_task_tools(state: AgentState) -> AgentState:
    task_type = state.constraints.get("task_type")
    node_name = f"{task_type}_tool_router" if task_type in {"errand", "meal"} else "tool_router"
    city = state.constraints.get("city") or state.constraints.get("default_city")
    preferences = state.constraints.get("preferences") or (["美食"] if task_type == "meal" else [])
    avoid = state.constraints.get("avoid") or []
    places = search_places(city, preferences, avoid, state.constraints.get("hotel_brand")) if city else []
    lifestyle_places = _extract_lifestyle_places(places)
    if task_type == "meal" and not lifestyle_places.get("foods"):
        lifestyle_places["foods"] = _meal_candidates(places, state.constraints)
    places_result = _tool_result("place_search_tool", places)
    state.tool_results.append(places_result)
    state._weather = {}  # type: ignore[attr-defined]
    state._places = places  # type: ignore[attr-defined]
    state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
    state._search_results = {"provider": "none", "results": [], "note": f"{task_type} 场景跳过网页搜索"}  # type: ignore[attr-defined]
    state._travel_research = {"provider": "none", "sources": [], "note": f"{task_type} 场景使用规则和地点候选生成 MVP"}  # type: ignore[attr-defined]
    _log(state, node_name, "完成生活任务轻量工具准备", {
        "task_type": task_type,
        "city": city,
        "places_count": len(places),
        "food_places_count": len(lifestyle_places.get("foods", [])),
        "skipped_tools": ["weather_tool", "web_search_tool"],
    })
    return state


def generate_plan(state: AgentState) -> AgentState:
    task_type = state.constraints.get("task_type") or "travel"
    if task_type == "todo":
        state.final_plan = _build_todo_plan(state)
        _log(state, "plan_generator", "生成待办拆解计划", {
            "task_type": "todo",
            "tasks_count": len(state.final_plan.get("todo_items", [])) if state.final_plan else 0,
        })
        return state
    if task_type == "errand":
        state.final_plan = _build_errand_plan(state)
        _log(state, "plan_generator", "生成跑腿顺路计划", {
            "task_type": "errand",
            "items_count": len(state.final_plan.get("errand_items", [])) if state.final_plan else 0,
        })
        return state
    if task_type == "meal":
        state.final_plan = _build_meal_plan(state)
        _log(state, "plan_generator", "生成餐饮计划", {
            "task_type": "meal",
            "candidates_count": len(state.final_plan.get("meal_candidates", [])) if state.final_plan else 0,
        })
        return state

    selected = _select_places(state.candidates, state.constraints, state.replan_context)
    selected = _ensure_place_locations(selected)
    access_route_data = _estimate_access_route_if_needed(state)
    _emit_tool_event(
        state,
        "plan_generator",
        "route_tool",
        "正在估算到达路线和目的地内路线",
        "running",
        input_data={
            "origin": state.constraints.get("origin"),
            "destination": state.constraints.get("destination"),
            "selected_places": [item.get("name") for item in selected],
        },
        progress=73,
    )
    route = _tool_result("route_tool", estimate_route(selected))
    route["data"]["access_route"] = access_route_data
    _emit_tool_event(
        state,
        "plan_generator",
        "route_tool",
        "路线估算完成",
        "done",
        input_data={
            "origin": state.constraints.get("origin"),
            "destination": state.constraints.get("destination"),
            "selected_places": [item.get("name") for item in selected],
        },
        output_summary=_route_summary(route["data"]),
        preview_items=_route_preview(route["data"]),
        progress=76,
    )
    _emit_tool_event(
        state,
        "plan_generator",
        "budget_tool",
        "正在计算预算",
        "running",
        input_data={"budget_limit": state.constraints.get("budget"), "pace": state.constraints.get("pace")},
        progress=78,
    )
    budget = _tool_result(
        "budget_tool",
        estimate_budget(route["data"]["ordered_places"], state.constraints.get("budget"), state.constraints.get("pace")),
    )
    _emit_tool_event(
        state,
        "plan_generator",
        "budget_tool",
        "预算计算完成",
        "done",
        input_data={"budget_limit": state.constraints.get("budget"), "pace": state.constraints.get("pace")},
        output_summary=_budget_summary(budget["data"]),
        preview_items=_budget_preview(budget["data"]),
        progress=80,
    )
    state.tool_results.extend([route, budget])

    base_plan = _build_rule_based_plan(state, route["data"], budget["data"])
    llm_plan = _generate_plan_with_llm(state, route["data"], budget["data"], base_plan)
    if llm_plan and _plan_uses_candidate_places(llm_plan, selected) and _plan_has_enough_city_items(llm_plan, state):
        llm_plan.setdefault("weather", base_plan.get("weather"))
        llm_plan.setdefault("travel_research", base_plan.get("travel_research"))
        llm_plan.setdefault("alternatives", base_plan.get("alternatives", []))
        llm_plan.setdefault("access_route", base_plan.get("access_route"))
        llm_plan.setdefault("local_route", base_plan.get("local_route"))
        llm_plan.setdefault("destination_validation", base_plan.get("destination_validation"))
        llm_plan["budget"] = base_plan.get("budget", llm_plan.get("budget", {}))
        llm_plan["summary"] = base_plan.get("summary", llm_plan.get("summary", ""))
        state.final_plan = _enrich_plan_items(llm_plan, selected)
    else:
        if llm_plan:
            state.llm_usage.append({"node": "plan_generator", "status": "rejected", "reason": "plan_contains_places_not_returned_by_tools"})
        state.final_plan = base_plan

    _log(state, "plan_generator", "生成最终计划", {
        "selected_places": [item["name"] for item in selected],
        "covered_preferences": sorted(_covered_preferences(selected, state.constraints.get("preferences", []))),
        "budget_total": state.final_plan["budget"]["total"] if state.final_plan else None,
    })
    return state


def travel_plan_generator(state: AgentState) -> AgentState:
    return generate_plan(state)




def errand_plan_generator(state: AgentState) -> AgentState:
    state.final_plan = _build_errand_plan(state)
    _log(state, "errand_plan_generator", "生成跑腿顺路计划", {
        "task_type": "errand",
        "items_count": len(state.final_plan.get("errand_items", [])) if state.final_plan else 0,
    })
    return state


def meal_plan_generator(state: AgentState) -> AgentState:
    state.final_plan = _build_meal_plan(state)
    _log(state, "meal_plan_generator", "生成餐饮计划", {
        "task_type": "meal",
        "candidates_count": len(state.final_plan.get("meal_candidates", [])) if state.final_plan else 0,
    })
    return state


def todo_plan_generator(state: AgentState) -> AgentState:
    state.final_plan = _build_todo_plan(state)
    _log(state, "todo_plan_generator", "生成待办拆解计划", {
        "task_type": "todo",
        "tasks_count": len(state.final_plan.get("todo_items", [])) if state.final_plan else 0,
    })
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












def _generate_plan_with_llm(state: AgentState, route: dict, budget: dict, base_plan: dict[str, Any]) -> dict[str, Any] | None:
    if not _llm_enabled():
        return None
    payload = {
        "user_input": state.user_input,
        "constraints": state.constraints,
        "weather": state._weather,  # type: ignore[attr-defined]
        "web_search": state._search_results,  # type: ignore[attr-defined]
        "travel_research": state._travel_research,  # type: ignore[attr-defined]
        "lifestyle_places": state._lifestyle_places,  # type: ignore[attr-defined]
        "candidates": state.candidates[:8],
        "route": route,
        "budget": budget,
        "base_plan": base_plan,
        "reflection": state.replan_context or state.reflection,
        "instruction": "先基于 web_search/travel_research 总结天气、近期活动、景点攻略等依据；选点必须先满足用户目标和偏好，其次优先当地热门/标志性景点和有近期活动证据的地点，再只使用 candidates/base_plan 中已有地点生成路线；必须遵守 avoid，不要编造来源。",
    }
    try:
        plan = llm_client.json_complete(PLAN_GENERATOR_PROMPT, json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        state.llm_usage.append({"node": "plan_generator", "status": "error", "error": str(exc)})
        return None
    if not plan.get("itinerary") or not plan.get("budget"):
        state.llm_usage.append({"node": "plan_generator", "status": "ignored", "reason": "invalid_json_shape"})
        return None
    plan.setdefault("assistant_message", _build_assistant_message_from_plan(plan))
    state.llm_usage.append({"node": "plan_generator", "status": "success", "model": _llm_model_name()})
    return plan
















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










def _build_search_query(state: AgentState) -> str:
    destination_obj = state.constraints.get("destination") or {}
    city = _search_query_city(state, destination_obj)
    destination = state.constraints.get("destination_place") or destination_obj.get("name") or ""
    date_iso = state.constraints.get("date_iso") or state.constraints.get("date") or ""
    weekday = state.constraints.get("date_weekday") or ""
    preferences = " ".join(state.constraints.get("preferences", []))
    avoid = " ".join(f"避开{item}" for item in state.constraints.get("avoid", []))
    goal = state.goal or ""
    try:
        days = int(state.constraints.get("trip_days") or 1)
    except (TypeError, ValueError):
        days = 1
    trip_text = f"{days}日游" if days > 1 else "一日游"
    parts = [
        city,
        *_city_search_context_terms(city),
        destination,
        date_iso,
        weekday,
        trip_text,
        goal,
        preferences,
        avoid,
        *_search_query_terms(state, destination_obj, days),
    ]
    return " ".join(part for part in _dedupe_text_parts(parts) if part).strip()














































































































































































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
































def _prepend_destination_places(places: list[dict], state: AgentState) -> list[dict]:
    destination_obj = state.constraints.get("destination") or {}
    destination_place = state.constraints.get("destination_place") or destination_obj.get("name")
    if not destination_place:
        return places
    destination = next(
        (item for item in FAMOUS_DESTINATIONS.values() if item.get("place") == destination_place),
        None,
    )
    if not destination:
        if destination_obj.get("type") == "city":
            return places
        city = destination_obj.get("city") or state.constraints.get("destination_city") or state.constraints.get("city")
        anchor = {
            "name": destination_place,
            "city": city,
            "area": destination_place,
            "address": destination_obj.get("address") or destination_place,
            "tags": _destination_tags(destination_obj, state.constraints.get("activity_intent")),
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "目的地门票/交通费用需以官方平台为准，暂不计入活动费",
            "duration_minutes": 120,
            "intensity": "中",
            "map_url": f"https://ditu.amap.com/search?query={quote(' '.join(str(part) for part in [city, destination_place] if part))}",
            "source_url": f"https://ditu.amap.com/search?query={quote(' '.join(str(part) for part in [city, destination_place] if part))}",
            "source_title": "目的地识别",
            "play_points": ["围绕用户指定目的地安排，避免误用出发地附近景点"],
            "location": destination_obj.get("location"),
            "provider": "destination",
            "source_order": 0,
            "popularity_score": 24,
        }
        return _dedupe_places([anchor] + places)
    anchors = []
    for index, item in enumerate(destination.get("places", [])):
        anchors.append({
            "name": item["name"],
            "city": destination["city"],
            "area": item.get("area") or destination_place,
            "address": item.get("address") or destination_place,
            "tags": item.get("tags") or destination["tags"],
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "景区门票/索道/换乘费用需以官方预约平台为准，暂不计入活动费",
            "duration_minutes": item.get("duration_minutes", 90),
            "intensity": item.get("intensity", "中"),
            "map_url": f"https://ditu.amap.com/search?query={destination['city']}%20{item['name']}",
            "source_url": f"https://ditu.amap.com/search?query={destination['city']}%20{item['name']}",
            "source_title": "目的地景区识别",
            "play_points": item.get("play_points", []),
            "location": item.get("location"),
            "provider": "destination",
            "source_order": index,
            "popularity_score": 30,
        })
    return _dedupe_places(anchors + places)


























def _enrich_places_with_search_evidence(places: list[dict], search_data: dict[str, Any]) -> list[dict]:
    results = search_data.get("results") or []
    for place in places:
        evidence = []
        match_count = 0
        popularity_score = max(int(place.get("popularity_score", 0) or 0), _local_popularity_score(place))
        event_score = 0
        for result in results:
            title = result.get("name") or result.get("title") or ""
            snippet = result.get("summary") or result.get("snippet") or ""
            text = f"{title} {snippet}"
            if not _is_relevant_to_place(place["name"], text):
                continue
            match_count += 1
            if title:
                evidence.append(title)
            popularity_score += 6
            if _text_has_recent_activity_signal(text):
                event_score += 1
            price = _extract_ticket_price(text)
            if price is not None:
                place["estimated_cost"] = price
                place["cost_known"] = True
                place["cost_note"] = (
                    "网页搜索结果显示免费/免门票，实际以官方/现场为准"
                    if price == 0
                    else f"从网页搜索结果识别到约 {price} 元，实际以官方/现场为准"
                )
                break
        if evidence:
            place["evidence"] = list(dict.fromkeys(evidence))[:3]
        else:
            place.setdefault("evidence", [])
            place.setdefault("cost_known", False)
            place.setdefault("cost_note", "未从搜索/地图数据确认票价，活动费暂不计入")
        place["popularity_score"] = min(popularity_score, 30)
        place["event_score"] = min(event_score, 3)
        place["web_match_score"] = min(match_count * 8, 32)
    return places


















def _tool_result(tool_name: str, data: Any, input_data: Any = None) -> dict[str, Any]:
    result = {"tool_name": tool_name, "status": "success", "data": data, "error": None}
    if input_data is not None:
        result["input"] = _compact_payload(input_data)
    return result


def _emit_tool_event(
    state: AgentState,
    parent_node: str,
    tool_name: str,
    summary: str,
    status: str,
    input_data: Any = None,
    output_summary: Any = None,
    preview_items: list[Any] | None = None,
    progress: int | None = None,
) -> None:
    callback = getattr(state, "_progress_callback", None)
    if not callback:
        return
    event = {
        "trace_id": state.trace_id,
        "phase": "tool",
        "parent_node": parent_node,
        "node": tool_name,
        "tool_name": tool_name,
        "summary": summary,
        "status": status,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "input": _compact_payload(input_data),
        "output_summary": _compact_payload(output_summary),
        "preview_items": _compact_preview(preview_items),
    }
    if state.replan_context:
        event["details"] = {"round": "auto_replan"}
    if progress is not None:
        event["progress"] = progress
    callback(event)




def _compact_preview(items: list[Any] | None) -> list[Any]:
    return [_compact_payload(item) for item in (items or [])[:8]]








































def _enrich_plan_items(plan: dict[str, Any], selected: list[dict]) -> dict[str, Any]:
    place_by_name = {place["name"]: place for place in selected}
    for item in plan.get("itinerary", []):
        place = place_by_name.get(item.get("place"))
        if not place:
            continue
        for key in ["address", "location", "map_url", "source_url", "source_title", "play_points", "cost_known", "cost_note", "evidence"]:
            if place.get(key) and not item.get(key):
                item[key] = place[key]
    plan["assistant_message"] = _build_assistant_message_from_plan(plan)
    return plan














