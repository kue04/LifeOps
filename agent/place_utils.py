"""地点与候选处理工具：坐标、去重、相似度、种子点位、城市与地点名判定。

从 agent/nodes.py 抽出的叶子工具函数，不依赖 Agent 流程状态，
可被约束抽取、规划、评分、反思等节点共用。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from agent.constants import (
    CITY_GUIDE_POI_QUERY_TERMS,
    CITY_SEARCH_CONTEXT_TERMS,
    KNOWN_CITIES,
    MEAL_INTENT_WORDS,
    POPULAR_PLACE_KEYWORDS_BY_CITY,
    PREFERENCE_PLACE_KEYWORDS_BY_CITY,
    PROVINCE_HINTS,
    REFERENCE_TICKET_PRICES,
)
from agent.state import AgentState
from services.geocoder import geocode_place
from tools.route import estimate_access_route


def _all_popular_keywords() -> list[str]:
    keywords = []
    for city_keywords in POPULAR_PLACE_KEYWORDS_BY_CITY.values():
        keywords.extend(city_keywords)
    return list(dict.fromkeys(keywords))


def _apply_reference_ticket_price(place: dict[str, Any]) -> None:
    if int(place.get("estimated_cost") or 0) > 0:
        return
    city = place.get("city")
    name = place.get("name") or ""
    city_prices = REFERENCE_TICKET_PRICES.get(str(city), {})
    for keyword, price in city_prices.items():
        if keyword in name:
            place["estimated_cost"] = price
            place["cost_known"] = False
            place["cost_note"] = f"常见门票参考约 {price} 元，出发前以官方购票页为准"
            return


def _city_guide_search_batches(city: str) -> list[list[str]]:
    terms = CITY_GUIDE_POI_QUERY_TERMS.get(city) or []
    return [terms[index:index + 4] for index in range(0, len(terms), 4) if terms[index:index + 4]]


def _city_in_text(text: str) -> str | None:
    return next((city for city in KNOWN_CITIES if city in text), None)


def _city_search_context_terms(city: str | None) -> list[str]:
    if not city:
        return []
    return CITY_SEARCH_CONTEXT_TERMS.get(str(city), [])


def _city_travel_search_preferences(state: AgentState, preferences: list[str] | None = None) -> list[str]:
    preferences = preferences or []
    activity = state.constraints.get("activity_intent")
    if activity in {"爬山", "登山", "徒步"}:
        base = [activity, "景区", "森林公园", "山"]
    else:
        base = ["景点", "旅游景点", "古镇", "博物馆"]
    return list(dict.fromkeys(preferences + base))


def _clean_place_text(value: str) -> str:
    value = re.split(r"[，。,；;？?\s]", value, maxsplit=1)[0]
    value = re.sub(r"^(爬|游|逛|去|到|前往)", "", value)
    value = re.sub(r"(玩)?[一二两三四五六七八九十\d]+天$", "", value)
    value = re.sub(r"[一二两三四五六七八九十\d]+日游$", "", value)
    value = re.sub(r"(出发|旅游|旅行|游玩|爬山|登山|徒步|看展|展览|玩|路线|推荐|计划)$", "", value)
    return value.strip("的了 ")


def _coordinates(place: dict) -> tuple[float, float] | None:
    location = place.get("location")
    if not isinstance(location, str) or "," not in location:
        return None
    lon, lat = location.split(",", 1)
    try:
        return float(lon), float(lat)
    except ValueError:
        return None


def _dedupe_places(places: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for place in places:
        name = place.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(place)
    return result


def _destination_tags(destination: dict[str, Any], activity_intent: str | None) -> list[str]:
    tags = {"景点"}
    text = f"{destination.get('name', '')} {destination.get('raw', '')} {activity_intent or ''}"
    if any(word in text for word in ["山", "爬", "徒步", "登山"]):
        tags.update(["爬山", "徒步", "运动", "室外"])
    if any(word in text for word in ["展", "馆", "博物馆", "美术馆"]):
        tags.update(["展览", "室内"])
    if "散步" in text:
        tags.update(["散步", "室外"])
    return list(tags)


def _estimate_access_route_if_needed(state: AgentState) -> dict[str, Any]:
    origin = state.constraints.get("origin") or {}
    destination = state.constraints.get("destination") or {}
    if not origin or not destination:
        return estimate_access_route(origin or None, destination or None)
    origin_city = origin.get("city")
    destination_city = destination.get("city")
    origin_name = origin.get("name") or origin.get("raw")
    destination_name = destination.get("name") or destination.get("raw")
    same_city = origin_city and destination_city and origin_city == destination_city and not origin.get("location")
    same_place = origin_name and destination_name and origin_name == destination_name
    default_same_city = origin.get("source") == "default_city" and origin_city and origin_city in {destination_city, destination_name}
    if state.constraints.get("route_scope") != "cross_city_trip" or same_city or same_place or default_same_city:
        city = destination_city or origin_city or destination_name or origin_name or state.constraints.get("city")
        return {
            "needed": False,
            "from": origin_name,
            "to": destination_name,
            "provider": "same_city",
            "summary": f"{city}市内活动，无需生成跨城到达路线" if city else "市内活动，无需生成跨城到达路线",
            "mode": "local",
            "steps": [],
            "warnings": [],
        }
    return estimate_access_route(origin, destination)


def _explicit_non_default_city(text: str, default_city: str) -> str | None:
    return next((city for city in KNOWN_CITIES if city != default_city and city in text), None)


def _first_place_provider(places: list[dict[str, Any]]) -> str | None:
    return next((place.get("provider") for place in places if place.get("provider")), None)


def _is_broad_region_hint(value: str) -> bool:
    return value in PROVINCE_HINTS


def _is_city_name(name: str, city: str) -> bool:
    def normalize(value: str) -> str:
        return value.replace("市", "").strip()

    return bool(name and city and normalize(name) == normalize(city))


def _is_encyclopedia_host(host: str) -> bool:
    return any(domain in host for domain in ["wikipedia.org", "baike.baidu.com", "baike.sogou.com", "baike.so.com"])


def _is_origin_phrase(value: str) -> bool:
    return any(word in value for word in ["当前位置", "现在这个地方", "我这里", "从这里", "从我这"])


def _is_too_similar(selected: list[dict], candidate: dict) -> bool:
    if not selected:
        return False
    if candidate.get("provider") == "destination":
        return False
    candidate_tags = set(candidate.get("tags", []))
    for item in selected:
        if item.get("provider") == "destination":
            continue
        same_area = item.get("area") == candidate.get("area")
        overlap_tags = set(item.get("tags", [])).intersection(candidate_tags)
        specific_overlap = overlap_tags - {"散步", "室外", "室内", "景点"}
        if len(overlap_tags.intersection({"展览", "博物馆"})) >= 2:
            return True
        if same_area and (specific_overlap or len(overlap_tags) >= 3):
            return True
    return False


def _is_unconfirmed_task_place(place: dict[str, Any]) -> bool:
    text = " ".join(str(place.get(key, "")) for key in ["name", "area", "address", "cost_note"])
    return "待确认" in text or "璺戣吙" in set(place.get("tags") or [])


def _lifestyle_search_batches(state: AgentState) -> list[list[str]]:
    hotel_brand = state.constraints.get("hotel_brand")
    return [
        ["美食", "特色餐厅", "小吃"],
        [hotel_brand, "酒店", "住宿"] if hotel_brand else ["酒店", "住宿"],
    ]


def _match_place_for_errand(item: dict[str, Any], places: list[dict[str, Any]]) -> dict[str, Any] | None:
    action = item.get("action")
    wanted_tags = {
        "买": {"美食", "书店", "室内"},
        "吃饭": {"美食"},
    }.get(action, set())
    if not wanted_tags:
        return None
    return next((place for place in places if wanted_tags.intersection(place.get("tags", []))), None)


def _meal_local_score(item: dict[str, Any]) -> int:
    text = str(item.get("name") or "")
    score = 0
    for word in ["老火锅", "庭院", "社区", "茶壶", "鲜货", "鲜鱼", "美蛙", "老街坊", "苏家大院", "聚乐城", "淑华", "辣妹子", "369"]:
        if word in text:
            score += 6
    return score


def _meal_search_words() -> set[str]:
    return set(MEAL_INTENT_WORDS) | {"咖啡", "茶馆", "甜品", "烧烤", "夜宵", "餐厅", "小吃", "火锅", "川菜", "美食"}


def _meal_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key, "")) for key in ["name", "area", "address"])


def _mentions_current_area(text: str) -> bool:
    return any(word in text for word in ["附近", "周边", "当前位置", "我这里", "从这里", "现在这个地方"])


def _normalize_task_place(place: dict[str, Any] | None, title: str, duration: int, index: int) -> dict[str, Any]:
    if place:
        result = dict(place)
    else:
        result = {
            "name": title,
            "area": "地点待确认",
            "address": "地点待确认",
            "tags": ["跑腿"],
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "具体费用待确认",
            "play_points": ["先确认地址、营业时间和是否需要预约/排队"],
        }
    result.setdefault("area", result.get("address") or "地点待确认")
    result.setdefault("address", result.get("area") or "地点待确认")
    result.setdefault("tags", ["跑腿"])
    result.setdefault("estimated_cost", 0)
    result.setdefault("cost_known", False)
    result.setdefault("cost_note", "具体费用待确认")
    result["duration_minutes"] = int(result.get("duration_minutes") or duration)
    result["source_order"] = index
    return result


def _place_mix_category(place: dict[str, Any]) -> str:
    name = str(place.get("name") or place.get("place") or "")
    tags = set(place.get("tags") or [])
    if "博物馆" in name or "美术馆" in name or tags.intersection({"博物馆", "展览"}):
        return "museum"
    if any(word in name for word in ["公园", "湿地", "广场"]):
        return "park"
    if any(word in name for word in ["山", "风景区", "索道"]) or tags.intersection({"爬山", "徒步", "登山", "运动"}):
        return "mountain"
    if any(word in name for word in ["花市", "市场", "夜市", "街", "巷", "古镇", "水街"]):
        return "street_market"
    if any(word in name for word in ["楼", "塔", "坊", "祠", "寺", "故居", "城墙"]):
        return "culture_view"
    if any(word in name for word in ["湖", "池", "江", "河", "海", "岛", "湾"]):
        return "waterfront"
    return "other"


def _preference_seed_places(city: str, preferences: list[str], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    covered = set().union(*(set(place.get("tags", [])) for place in existing)) if existing else set()
    result = []
    templates = PREFERENCE_PLACE_KEYWORDS_BY_CITY.get(city, {})
    for preference in preferences:
        if preference in covered or preference not in templates:
            continue
        name, tags, point = templates[preference]
        result.append({
            "name": name,
            "city": city,
            "area": city,
            "address": f"{city}{preference}地图搜索",
            "tags": tags,
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "偏好地点来自城市真实地点兜底，消费待确认",
            "duration_minutes": 60,
            "intensity": "低",
            "source_order": 100 + len(result),
            "map_url": f"https://ditu.amap.com/search?query={quote(f'{city} {name}')}",
            "source_url": f"https://ditu.amap.com/search?query={quote(f'{city} {name}')}",
            "source_title": "城市偏好地点兜底",
            "play_points": [point],
            "provider": "city_seed",
            "popularity_score": 10,
        })
    return result


def _safe_geocode_location(query: str) -> str | None:
    try:
        result = geocode_place(query)
    except Exception:
        return None
    lat = result.get("latitude")
    lon = result.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"{lon},{lat}"
    return None


def _seed_duration(tags: list[str]) -> int:
    if "爬山" in tags:
        return 150
    if "博物馆" in tags or "展览" in tags:
        return 120
    return 90


def _seed_place_tags(name: str, preferences: list[str], activity_intent: str | None) -> list[str]:
    tags = {"景点"}
    text = f"{name} {' '.join(preferences)} {activity_intent or ''}"
    if any(word in text for word in ["博物馆", "省博", "展", "馆"]):
        tags.update(["展览", "博物馆", "室内"])
    if any(word in text for word in ["湖", "桥", "街", "巷", "步行街", "散步", "夜景"]):
        tags.update(["散步", "室外"])
    if "夜景" in text or any(word in name for word in ["长江大桥", "江汉路", "外滩", "珠江"]):
        tags.update(["夜景", "室外"])
    if any(word in text for word in ["山", "爬山", "徒步", "登山"]):
        tags.update(["爬山", "徒步", "运动", "室外"])
    return list(tags)


def _seed_play_points(name: str, tags: list[str]) -> list[str]:
    points = [f"作为{name}相关城市地标兜底候选，出发前确认开放和预约信息"]
    if "博物馆" in tags or "展览" in tags:
        points.append("适合安排为室内展览/馆藏段")
    if "夜景" in tags:
        points.append("适合傍晚或夜间作为观景段")
    if "散步" in tags:
        points.append("适合轻松步行串联")
    return points
