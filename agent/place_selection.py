"""候选地点筛选：去重、按城市收敛、按预算与节奏挑选最终点位。

从 agent/nodes.py 整组搬迁，闭包自洽，不依赖其他 Agent 节点。
"""

from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import quote

from agent.constants import POPULAR_PLACE_KEYWORDS_BY_CITY
from agent.guide_messages import (
    _is_city_placeholder_place,
)
from agent.intent_signals import (
    _target_place_count,
)
from agent.place_utils import (
    _apply_reference_ticket_price,
    _coordinates,
    _dedupe_places,
    _is_too_similar,
    _is_unconfirmed_task_place,
    _place_mix_category,
    _preference_seed_places,
    _seed_duration,
    _seed_place_tags,
    _seed_play_points,
)
from agent.plan_builders import (
    _improve_budget_fit,
)
from agent.scoring import (
    _filter_reflection_blocked_places,
    _is_iconic_place,
    _place_aliases,
    _travel_priority,
)
from agent.search import (
    _search_city_trip_places,
    _travel_preferences,
)
from agent.state import AgentState
from agent.text_utils import (
    _selection_quality,
)
from config import settings
from services.geocoder import geocode_place
from tools.places import search_places


def _select_places(candidates: list[dict], constraints: dict, replan_context: dict[str, Any] | None = None) -> list[dict]:
    candidates = _filter_reflection_blocked_places(candidates, replan_context or {})
    budget = constraints.get("budget") or 500
    avoid = set(constraints.get("avoid", []))
    preferences = constraints.get("preferences", [])
    target_count = _target_place_count(constraints, replan_context or {})
    if not preferences:
        return _select_compact_places(candidates, budget, avoid, target_count)
    selected = []
    cost = 150
    for preference in preferences:
        match = next(
            (
                candidate
                for candidate in candidates
                if preference in candidate.get("tags", [])
                and avoid.isdisjoint(candidate.get("tags", []))
                and candidate["name"] not in {item["name"] for item in selected}
                and cost + candidate["estimated_cost"] <= budget
            ),
            None,
        )
        if match and len(selected) < target_count:
            selected.append(match)
            cost += match["estimated_cost"]
    selected_tags = set().union(*(set(item.get("tags", [])) for item in selected)) if selected else set()
    for candidate in candidates:
        if len(selected) >= target_count:
            break
        if candidate["name"] in {item["name"] for item in selected}:
            continue
        if not avoid.isdisjoint(candidate.get("tags", [])):
            continue
        if set(candidate.get("tags", [])).issubset(selected_tags) and len(selected) >= 2:
            continue
        if cost + candidate["estimated_cost"] <= budget:
            selected.append(candidate)
            selected_tags.update(candidate.get("tags", []))
            cost += candidate["estimated_cost"]
    return _improve_budget_fit(selected, candidates, constraints, avoid)


def _ensure_place_locations(places: list[dict]) -> list[dict]:
    allow_external_geocode = settings.place_provider != "mock"
    for place in places:
        if place.get("provider") == "city_seed":
            _hydrate_place_from_map_search(place)
        _apply_reference_ticket_price(place)
        if place.get("location"):
            continue
        if not allow_external_geocode:
            continue
        if _is_unconfirmed_task_place(place):
            continue
        query = " ".join(
            str(part)
            for part in [place.get("city"), place.get("name"), place.get("address") or place.get("area")]
            if part
        ).strip()
        if not query:
            continue
        try:
            location = geocode_place(query)
        except Exception:
            continue
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
            place["location"] = f"{longitude},{latitude}"
    return places


def _hydrate_place_from_map_search(place: dict[str, Any]) -> None:
    city = place.get("city")
    name = place.get("name")
    if not city or not name:
        return
    try:
        matches = search_places(str(city), [str(name)], [])
    except Exception:
        return
    match = _best_map_match(str(name), matches)
    if not match:
        return
    for key in ["area", "address", "location", "map_url", "source_url"]:
        if match.get(key):
            place[key] = match[key]
    place["source_title"] = match.get("source_title") or "高德地图地点搜索"
    place["provider"] = "city_seed+amap"
    place["tags"] = list(dict.fromkeys((place.get("tags") or []) + (match.get("tags") or [])))
    if match.get("estimated_cost"):
        place["estimated_cost"] = match["estimated_cost"]
        place["cost_known"] = bool(match.get("cost_known"))
        place["cost_note"] = match.get("cost_note") or place.get("cost_note")


def _best_map_match(place_name: str, matches: list[dict]) -> dict[str, Any] | None:
    filtered = [item for item in matches if _is_relevant_to_place(place_name, item.get("name", ""))]
    if not filtered:
        return None
    bad_words = ["地铁站", "公交站", "大街", "停车场", "售票处", "游客中心"]
    return max(
        filtered,
        key=lambda item: (
            int(bool(item.get("location"))) * 8
            + int(place_name in item.get("name", "")) * 6
            + int(bool(item.get("estimated_cost"))) * 3
            - sum(8 for word in bad_words if word in item.get("name", "")),
        ),
    )


def _select_compact_places(candidates: list[dict], budget: int, avoid: set[str], target_count: int = 3) -> list[dict]:
    usable = [
        candidate
        for candidate in candidates
        if avoid.isdisjoint(candidate.get("tags", [])) and 150 + candidate["estimated_cost"] <= budget
    ]
    usable = sorted(usable, key=_travel_priority, reverse=True)
    if len(usable) <= target_count:
        return usable
    anchor = usable[0]
    selected = [anchor]
    cost = 150 + anchor["estimated_cost"]
    for candidate in sorted(usable[1:], key=lambda item: (_similarity_penalty(selected, item), -_selection_quality(item), _distance_between(anchor, item), -item.get("score", 0))):
        if len(selected) >= target_count:
            break
        if cost + candidate["estimated_cost"] > budget:
            continue
        if _is_too_similar(selected, candidate):
            continue
        if _exceeds_default_city_mix(selected, candidate, target_count):
            continue
        selected.append(candidate)
        cost += candidate["estimated_cost"]
    for candidate in usable:
        if len(selected) >= target_count:
            break
        if candidate["name"] in {item["name"] for item in selected}:
            continue
        if _exceeds_default_city_mix(selected, candidate, target_count):
            continue
        if cost + candidate["estimated_cost"] <= budget:
            selected.append(candidate)
            cost += candidate["estimated_cost"]
    if len(selected) < min(2, target_count):
        for candidate in usable:
            if len(selected) >= min(2, target_count):
                break
            if candidate["name"] in {item["name"] for item in selected}:
                continue
            if cost + candidate["estimated_cost"] <= budget:
                selected.append(candidate)
                cost += candidate["estimated_cost"]
    return selected


def _exceeds_default_city_mix(selected: list[dict], candidate: dict, target_count: int) -> bool:
    category = _place_mix_category(candidate)
    if category not in {"museum", "park"}:
        return False
    current_limited = sum(1 for item in selected if _place_mix_category(item) in {"museum", "park"})
    limited_cap = 2 if target_count >= 5 else 1
    return current_limited >= limited_cap


def _similarity_penalty(selected: list[dict], candidate: dict) -> int:
    return 1 if _is_too_similar(selected, candidate) else 0


def _filter_travel_places(places: list[dict], preferences: list[str] | None = None) -> list[dict]:
    requested = set(preferences or [])
    travel_places = []
    for place in places:
        if _is_city_placeholder_place(place):
            continue
        tags = set(place.get("tags", []))
        if tags.intersection({"酒店", "住宿", "閰掑簵", "浣忓"}):
            continue
        if tags.intersection({"美食", "缇庨"}) and not requested.intersection(tags):
            continue
        travel_places.append(place)
    return travel_places


def _ensure_city_trip_places(places: list[dict], state: AgentState, city: str | None) -> list[dict]:
    if not city:
        return places
    destination = state.constraints.get("destination") or {}
    is_city_trip = (
        state.constraints.get("route_scope") == "city_trip"
        or destination.get("type") in {"city", "district"}
        or (state.constraints.get("city") and not destination)
    )
    if not is_city_trip:
        return places
    travel_count = _city_trip_travel_count(places, state)
    if travel_count >= 3:
        return places
    live_places = _search_city_trip_places(city, state)
    if live_places:
        places = _dedupe_places(places + live_places)
        travel_count = _city_trip_travel_count(places, state)
    if travel_count >= 3 and not _broad_city_places_need_seed(places, state):
        return places
    seed_places = _city_seed_places(
        city,
        state.constraints.get("preferences") or [],
        state.constraints.get("activity_intent"),
    )
    if seed_places:
        return _dedupe_places(places + seed_places)
    return _dedupe_places(places + _generic_city_search_places(city, state.constraints.get("activity_intent")))


def _broad_city_places_need_seed(places: list[dict], state: AgentState) -> bool:
    if not _is_broad_city_sightseeing_request(state):
        return False
    travel_places = _filter_travel_places(places, state.constraints.get("preferences", []))
    if len(travel_places) < 4:
        return True
    return not any(_is_iconic_place(place) for place in travel_places)


def _city_trip_travel_count(places: list[dict], state: AgentState) -> int:
    food_tags = {"美食", "火锅", "川菜", "小吃", "茶馆"}
    return len([
        place for place in _filter_travel_places(places, state.constraints.get("preferences", []))
        if not set(place.get("tags") or []).intersection(food_tags)
    ])


def _is_broad_city_sightseeing_request(state: AgentState) -> bool:
    destination = state.constraints.get("destination") or {}
    if destination.get("type") not in {"city", "district"} and not (state.constraints.get("city") and not destination):
        return False
    if _travel_preferences(state.constraints.get("preferences") or []):
        return False
    text = f"{state.user_input} {state.goal or ''}"
    return any(word in text for word in ["旅游", "景点", "推荐", "攻略", "好玩", "打卡"])


def _is_relevant_to_place(place_name: str, text: str) -> bool:
    compact_name = re.sub(r"[·\-（）()]", "", place_name)
    compact_text = re.sub(r"[·\-（）()]", "", text)
    if compact_name and compact_name in compact_text:
        return True
    keywords = _place_aliases(place_name)
    return any(keyword in compact_text for keyword in keywords)


def _fallback_places_for_city(city: str, preferences: list[str] | None = None, activity_intent: str | None = None) -> list[dict[str, Any]]:
    names = POPULAR_PLACE_KEYWORDS_BY_CITY.get(city) or []
    result = []
    for index, name in enumerate(names[:6]):
        tags = _seed_place_tags(name, preferences or [], activity_intent)
        result.append({
            "name": name,
            "city": city,
            "area": city,
            "address": f"{city}{name}",
            "tags": tags,
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "地点来自城市热门地标兜底，票价/营业时间待确认",
            "duration_minutes": _seed_duration(tags),
            "intensity": "中" if "爬山" in tags or "散步" in tags else "低",
            "source_order": index,
            "map_url": f"https://ditu.amap.com/search?query={quote(f'{city} {name}')}",
            "source_url": f"https://ditu.amap.com/search?query={quote(f'{city} {name}')}",
            "source_title": "城市热门地标兜底",
            "play_points": _seed_play_points(name, tags),
            "provider": "city_seed",
            "popularity_score": 18,
        })
    if not result:
        return []
    result.extend(_preference_seed_places(city, preferences or [], result))
    return result


def _city_seed_places(city: str, preferences: list[str] | None = None, activity_intent: str | None = None) -> list[dict[str, Any]]:
    return _fallback_places_for_city(city, preferences, activity_intent)


def _generic_city_search_places(city: str, activity_intent: str | None = None) -> list[dict[str, Any]]:
    templates = [
        ("城市核心游玩区（地图搜索）", ["景点", "散步", "室外"], "用地图搜索当地核心景点/商圈，作为主线起点；具体地点和开放信息待确认"),
        ("展览/博物馆候选（地图搜索）", ["展览", "博物馆", "室内"], "用地图搜索当地展览、美术馆或博物馆，作为室内停留点；预约和开放信息待确认"),
        ("夜景/步行街候选（地图搜索）", ["夜景", "散步", "室外"], "用地图搜索夜景、江河湖岸或步行街，作为傍晚段；安全和交通信息待确认"),
    ]
    if activity_intent in {"爬山", "登山", "徒步"}:
        templates[0] = ("登山/徒步候选（地图搜索）", ["爬山", "徒步", "运动", "室外"], "用地图搜索当地登山、徒步或公园路线；开放和路况待确认")
    result = []
    for index, (name, tags, point) in enumerate(templates):
        query = name.replace("（地图搜索）", "").replace("/", " ")
        result.append({
            "name": name,
            "city": city,
            "area": city,
            "address": f"{city}{query}",
            "tags": tags,
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "地图服务降级后的类别型候选，票价/营业时间待确认",
            "duration_minutes": _seed_duration(tags),
            "intensity": "中" if any(tag in tags for tag in ["爬山", "徒步", "散步"]) else "低",
            "source_order": 200 + index,
            "map_url": f"https://ditu.amap.com/search?query={quote(f'{city} {query}')}",
            "source_url": f"https://ditu.amap.com/search?query={quote(f'{city} {query}')}",
            "source_title": "地图服务降级兜底",
            "play_points": [point],
            "provider": "city_fallback",
            "popularity_score": 6,
        })
    return result


def _distance_between(a: dict, b: dict) -> float:
    coord_a = _coordinates(a)
    coord_b = _coordinates(b)
    if not coord_a or not coord_b:
        return math.inf
    lon1, lat1 = coord_a
    lon2, lat2 = coord_b
    radius = 6371
    lat_delta = math.radians(lat2 - lat1)
    lon_delta = math.radians(lon2 - lon1)
    hav = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(lon_delta / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(hav))
