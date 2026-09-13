"""工具路由：按任务类型编排天气/地点/路线/搜索/预算工具链并回填产物。

从 agent/nodes.py 整组搬迁，闭包自洽，不依赖其他 Agent 节点。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

from agent.constants import FAMOUS_DESTINATIONS
from agent.guide_messages import _build_assistant_message_from_plan
from agent.intent_signals import (
    _covered_preferences,
    _plan_has_enough_city_items,
    _plan_uses_candidate_places,
    _text_has_recent_activity_signal,
)
from agent.place_selection import (
    _ensure_city_trip_places,
    _ensure_place_locations,
    _filter_travel_places,
    _is_relevant_to_place,
    _select_places,
)
from agent.place_utils import (
    _city_search_context_terms,
    _dedupe_places,
    _destination_tags,
    _estimate_access_route_if_needed,
    _first_place_provider,
)
from agent.plan_builders import (
    _build_errand_plan,
    _build_meal_plan,
    _build_rule_based_plan,
    _build_todo_plan,
)
from agent.prompts import PLAN_GENERATOR_PROMPT
from agent.scoring import _local_popularity_score, _meal_candidates
from agent.search import (
    _build_travel_research,
    _search_query_city,
    _search_query_terms,
    _search_web_for_travel,
)
from agent.state import AgentState
from agent.text_utils import (
    _budget_preview,
    _budget_summary,
    _compact_payload,
    _dedupe_text_parts,
    _evidence_preview,
    _extract_lifestyle_places,
    _extract_ticket_price,
    _filter_places_by_city,
    _llm_enabled,
    _llm_model_name,
    _log,
    _places_preview,
    _route_preview,
    _route_summary,
    _search_preview,
    _search_summary,
    _weather_summary,
)
from agent.timeline import _annotate_places_for_goal
from services.llm_client import llm_client
from tools.budget import estimate_budget
from tools.places import search_places
from tools.route import estimate_route
from tools.weather import get_weather


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
