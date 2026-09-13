"""动态执行步骤：按执行计划逐步调用工具并累积 artifacts。

从 agent/nodes.py 整组搬迁，闭包自洽，不依赖其他 Agent 节点。
"""

from __future__ import annotations

from typing import Any

from agent.intent import (
    _extract_errand_items,
    _extract_place_names_from_search,
    _parse_todo_goal,
)
from agent.intent_signals import (
    _dynamic_city,
    _is_mixed_intent,
    _legacy_tool_name,
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
)
from agent.plan_builders import (
    _errand_candidate_places,
)
from agent.scoring import _meal_candidates, _travel_priority
from agent.search import _build_travel_research, _search_web_for_travel, _travel_preferences
from agent.state import AgentState
from agent.text_utils import (
    _budget_preview,
    _budget_summary,
    _confirm_actions_for,
    _constrain_mixed_budget,
    _extract_lifestyle_places,
    _filter_places_by_city,
    _intent_has,
    _log,
    _places_preview,
    _route_preview,
    _route_summary,
    _weather_summary,
)
from agent.timeline import _annotate_places_for_goal
from agent.tool_router import (
    _build_search_query,
    _emit_tool_event,
    _enrich_places_with_search_evidence,
    _prepend_destination_places,
    _tool_result,
)
from services.scorer import score_candidates
from tools.budget import estimate_budget
from tools.places import search_places
from tools.route import estimate_route
from tools.weather import get_weather


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
