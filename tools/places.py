from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

from config import settings
from services.geocoder import geocode_city, geocode_place


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "mock_places.json"
AMAP_MAX_KEYWORDS = 4
AMAP_MAX_PLACES = 20
AMAP_TOTAL_TIMEOUT_SECONDS = 12.0


def search_places(city: str, preferences: list[str], avoid: list[str] | None = None, hotel_brand: str | None = None) -> list[dict]:
    avoid = avoid or []
    if settings.place_provider == "amap":
        try:
            amap_places = _filter_quality_places(_search_amap(city, preferences, hotel_brand))
            curated_places = _with_links(_mark_provider(_search_mock(city, preferences), "curated"))
            return _filter_avoided(_merge_places(curated_places, amap_places), avoid)
        except Exception as exc:
            return _filter_avoided(_with_links(_mark_provider(_search_mock(city, preferences), "mock", f"amap: {exc}")), avoid)
    if settings.place_provider == "osm":
        try:
            return _filter_avoided(_with_links(_mark_provider(_search_osm(city, preferences), "osm")), avoid)
        except Exception as exc:
            return _filter_avoided(_with_links(_mark_provider(_search_mock(city, preferences), "mock", f"osm: {exc}")), avoid)
    return _filter_avoided(_with_links(_mark_provider(_search_mock(city, preferences), "mock")), avoid)


def _mark_provider(places: list[dict], provider: str, warning: str | None = None) -> list[dict]:
    for place in places:
        place["provider"] = provider
        if warning:
            place["provider_warning"] = warning
    return places


def _merge_places(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for place in primary + secondary:
        name = place.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        merged.append(place)
    return merged


def _search_mock(city: str, preferences: list[str]) -> list[dict]:
    places = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    matched_city = [place for place in places if place["city"] == city]
    preference_set = set(preferences)
    return sorted(matched_city, key=lambda place: len(preference_set.intersection(place["tags"])), reverse=True)


def _search_amap(city: str, preferences: list[str], hotel_brand: str | None = None) -> list[dict]:
    if not settings.amap_api_key:
        raise RuntimeError("AMAP_API_KEY is required when PLACE_PROVIDER=amap")
    keywords = _amap_keywords(preferences, hotel_brand)[:AMAP_MAX_KEYWORDS]
    places: list[dict] = []
    seen = set()
    deadline = time.monotonic() + AMAP_TOTAL_TIMEOUT_SECONDS
    last_error: Exception | None = None
    for keyword in keywords:
        if len(places) >= AMAP_MAX_PLACES or time.monotonic() >= deadline:
            break
        params = {
            "key": settings.amap_api_key,
            "keywords": keyword,
            "city": city,
            "citylimit": "true",
            "extensions": "base",
            "offset": 5,
            "page": 1,
        }
        try:
            data = _amap_get_json(params, min(5, max(1, deadline - time.monotonic())))
        except requests.RequestException as exc:
            last_error = exc
            if places:
                break
            continue
        except RuntimeError as exc:
            last_error = exc
            if places:
                break
            continue
        if data.get("status") != "1":
            last_error = RuntimeError(data.get("info") or "amap place search failed")
            if places:
                break
            continue
        for item in data.get("pois", []):
            name = item.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            places.append(_amap_poi_to_place(city, item, keyword, len(places)))
            if len(places) >= AMAP_MAX_PLACES:
                break
    if not places and last_error:
        raise RuntimeError(str(last_error))
    return _mark_provider(places, "amap")


def _amap_get_json(params: dict, timeout_seconds: float) -> dict:
    url = "https://restapi.amap.com/v3/place/text"
    try:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": "LifeOpsAgent/0.1", "Connection": "close"},
            timeout=(2, timeout_seconds),
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return _amap_get_json_with_curl(url, params, timeout_seconds)


def _amap_get_json_with_curl(url: str, params: dict, timeout_seconds: float) -> dict:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("amap requests failed and curl is unavailable")
    request_url = f"{url}?{urlencode(params)}"
    completed = subprocess.run(
        [curl, "-sS", "--max-time", str(max(1, int(timeout_seconds))), request_url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=max(2, int(timeout_seconds) + 1),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "amap curl request failed")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("amap curl response is not valid json") from exc


def _amap_keywords(preferences: list[str], hotel_brand: str | None = None) -> list[str]:
    if not preferences:
        base = ["景点", "博物馆", "公园", hotel_brand or "特色餐厅"]
        return list(dict.fromkeys(base))
    mapping = {
        "景点": ["景点", "旅游景点"],
        "旅游": ["景点", "旅游景点"],
        "旅游景点": ["旅游景点", "风景区"],
        "景区": ["风景区", "景区"],
        "古镇": ["古镇", "历史街区"],
        "展览": ["美术馆", "博物馆", "展览馆"],
        "博物馆": ["博物馆"],
        "夜景": ["夜景", "观景点"],
        "海边": ["海边", "海滨", "沙滩", "海岸"],
        "散步": ["公园", "历史街区"],
        "爬山": ["景区", "登山", "森林公园", "山"],
        "徒步": ["景区", "步道", "森林公园", "山"],
        "登山": ["景区", "登山", "森林公园", "山"],
        "公园": ["公园"],
        "书店": ["书店"],
        "美食": ["特色餐厅"],
        "火锅": ["火锅"],
        "川菜": ["川菜"],
        "小吃": ["小吃"],
        "茶馆": ["茶馆"],
        "咖啡": ["咖啡"],
    }
    keywords: list[str] = []
    for preference in preferences:
        keywords.extend(mapping.get(preference, [preference]))
    keywords.extend(["景点", hotel_brand or "特色餐厅"])
    return list(dict.fromkeys(keywords))


def _amap_poi_to_place(city: str, item: dict, keyword: str, source_order: int) -> dict:
    name = item.get("name", "")
    address = item.get("address") if isinstance(item.get("address"), str) else ""
    area = item.get("adname") or item.get("business_area") or city
    tags = _infer_amap_tags(keyword, item)
    cost = _amap_cost(item)
    return {
        "name": name,
        "city": city,
        "area": area,
        "address": address or area,
        "tags": tags,
        "estimated_cost": cost,
        "cost_known": cost > 0,
        "cost_note": _cost_note(cost, "高德地点详情" if cost > 0 else None),
        "duration_minutes": _estimate_duration(tags),
        "intensity": "低",
        "rating": (item.get("biz_ext") or {}).get("rating"),
        "popularity_score": _amap_popularity(item, keyword),
        "source_order": source_order,
        "location": item.get("location"),
        "map_url": _map_url(city, name, address or area),
        "source_url": _map_url(city, name, address or area),
        "source_title": "高德地图地点搜索",
        "play_points": _play_points(tags, area),
        "raw": item,
    }


def _infer_amap_tags(keyword: str, item: dict) -> list[str]:
    name_type_text = " ".join(str(value) for value in [item.get("type"), item.get("name")] if value)
    text = " ".join(str(value) for value in [keyword, item.get("type"), item.get("name")] if value)
    tags = set()
    food_signal = any(word in text for word in ["餐", "美食", "火锅", "川菜", "小吃", "烧烤", "夜宵", "甜品", "茶馆"])
    if any(word in text for word in ["咖啡", "咖啡厅"]):
        tags.update(["咖啡", "室内"])
    if any(word in text for word in ["美术馆", "博物馆", "展览", "展览馆"]):
        tags.update(["展览", "博物馆", "室内"])
    if any(word in text for word in ["公园", "景点", "风景", "观景", "历史街区"]):
        tags.update(["散步", "室外"])
    mountain_signal = (
        any(word in name_type_text for word in ["登山", "爬山", "徒步", "步道", "古径", "森林公园", "福道"])
        or ("风景名胜" in name_type_text and any(word in name_type_text for word in ["山", "峰", "岭", "峡"]))
    )
    if not food_signal and mountain_signal:
        tags.update(["爬山", "运动", "室外"])
    if "夜景" in text:
        tags.update(["夜景", "散步", "室外"])
    if any(word in text for word in ["海边", "海滨", "沙滩", "海岸", "看海"]):
        tags.update(["海边", "散步", "室外"])
    if "书店" in text:
        tags.update(["书店", "室内"])
    if food_signal:
        tags.update(["美食", "室内"])
    if "火锅" in text:
        tags.add("火锅")
    if "川菜" in text:
        tags.add("川菜")
    if "小吃" in text:
        tags.add("小吃")
    if "茶馆" in text:
        tags.add("茶馆")
    if "酒店" in text or "宾馆" in text:
        tags.update(["酒店", "住宿"])
    return list(tags or {"景点"})


def _estimate_duration(tags: list[str]) -> int:
    if "酒店" in tags or "住宿" in tags:
        return 0
    if "爬山" in tags or "运动" in tags:
        return 180
    if "咖啡" in tags or "美食" in tags:
        return 75
    if "展览" in tags or "博物馆" in tags:
        return 120
    return 90


def _play_points(tags: list[str], area: str) -> list[str]:
    points = []
    if "展览" in tags or "博物馆" in tags:
        points.append("看展/馆藏，适合避开天气影响")
    if "散步" in tags:
        points.append(f"在{area}周边慢走拍照，不需要强消费")
    if "爬山" in tags or "运动" in tags:
        points.append("适合爬坡、徒步和长距离行走")
    if "夜景" in tags:
        points.append("傍晚或入夜后观景更合适")
    if "美食" in tags:
        points.append("作为正餐或休息补给点")
    if "酒店" in tags or "住宿" in tags:
        points.append(f"适合作为{area}附近住宿备选")
    return points or ["根据现场开放区域轻量游玩"]


def _filter_avoided(places: list[dict], avoid: list[str]) -> list[dict]:
    avoid_set = set(avoid)
    if not avoid_set:
        return places
    return [place for place in places if avoid_set.isdisjoint(place.get("tags", []))]


def _with_links(places: list[dict]) -> list[dict]:
    for place in places:
        name = place.get("name", "")
        city = place.get("city", "")
        address = place.get("address") or place.get("area") or city
        place.setdefault("address", address)
        place.setdefault("map_url", _map_url(city, name, address))
        place.setdefault("source_url", place["map_url"])
        place.setdefault("source_title", place.get("provider", "地点搜索"))
        place.setdefault("play_points", _play_points(place.get("tags", []), place.get("area", city)))
    return places


def _map_url(city: str, name: str, address: str) -> str:
    return f"https://ditu.amap.com/search?query={quote(f'{city} {name} {address}'.strip())}"


def _geocode_place_location(city: str, name: str, address: str) -> str | None:
    query = " ".join(part for part in [city, name, address] if part).strip()
    if not query:
        return None
    try:
        result = geocode_place(query)
    except Exception:
        return None
    latitude = result.get("latitude")
    longitude = result.get("longitude")
    if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
        return f"{longitude},{latitude}"
    return None


def _search_osm(city: str, preferences: list[str]) -> list[dict]:
    location = geocode_city(city)
    bbox = location.get("boundingbox")
    if bbox:
        south, north, west, east = bbox[0], bbox[1], bbox[2], bbox[3]
    else:
        south, west, north, east = _bbox_around(location["latitude"], location["longitude"])
    response = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": _overpass_query(preferences).format(south=south, west=west, north=north, east=east)},
        headers={"User-Agent": "LifeOpsAgent/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    elements = response.json().get("elements", [])
    places = [_osm_element_to_place(city, item, preferences) for item in elements]
    return _filter_quality_places(places)[:30]


def _overpass_query(preferences: list[str]) -> str:
    filters = _osm_filters(preferences)
    return f"""
    [out:json][timeout:20];
    (
      {filters}
    );
    out center tags 60;
    """


def _osm_filters(preferences: list[str]) -> str:
    tags = set(preferences)
    parts = []
    if "咖啡" in tags or "美食" in tags:
        parts += [
            'node["amenity"="cafe"]({south},{west},{north},{east});',
            'way["amenity"="cafe"]({south},{west},{north},{east});',
        ]
    if not tags or "展览" in tags or "博物馆" in tags:
        parts += [
            'node["tourism"="museum"]({south},{west},{north},{east});',
            'way["tourism"="museum"]({south},{west},{north},{east});',
            'node["tourism"="gallery"]({south},{west},{north},{east});',
            'way["tourism"="gallery"]({south},{west},{north},{east});',
        ]
    if not tags or "夜景" in tags or "散步" in tags or "公园" in tags or "海边" in tags:
        parts += [
            'node["tourism"="viewpoint"]({south},{west},{north},{east});',
            'way["leisure"="park"]({south},{west},{north},{east});',
            'node["natural"="beach"]({south},{west},{north},{east});',
            'way["waterway"]({south},{west},{north},{east});',
        ]
    if "书店" in tags:
        parts += [
            'node["shop"="books"]({south},{west},{north},{east});',
            'way["shop"="books"]({south},{west},{north},{east});',
        ]
    return "\n".join(parts or ['node["tourism"]({south},{west},{north},{east});'])


def _osm_element_to_place(city: str, element: dict, preferences: list[str]) -> dict:
    tags = element.get("tags", {})
    inferred = _infer_osm_tags(tags, preferences)
    return {
        "name": tags.get("name:zh") or tags.get("name"),
        "city": city,
        "area": tags.get("addr:district") or tags.get("addr:suburb") or city,
        "tags": inferred,
        "estimated_cost": _estimate_cost(inferred),
        "duration_minutes": 90 if "咖啡" in inferred else 120,
        "intensity": "低",
        "location": _osm_location(element),
        "raw": element,
    }


def _infer_osm_tags(tags: dict, preferences: list[str]) -> list[str]:
    result = set()
    if tags.get("amenity") == "cafe":
        result.update(["咖啡", "室内"])
    if tags.get("tourism") in {"museum", "gallery"}:
        result.update(["展览", "室内"])
    if tags.get("tourism") == "viewpoint" or tags.get("leisure") == "park" or tags.get("natural") == "beach" or tags.get("waterway"):
        result.update(["夜景", "散步", "室外"])
    if tags.get("shop") == "books":
        result.update(["书店", "室内"])
    return list(result or {"生活"})


def _filter_quality_places(places: list[dict]) -> list[dict]:
    seen = set()
    filtered = []
    for place in places:
        name = place.get("name") or ""
        if not name or len(name) < 2:
            continue
        if _is_low_quality_name(name):
            continue
        if name in seen:
            continue
        seen.add(name)
        filtered.append(place)
    return filtered


def _is_low_quality_name(name: str) -> bool:
    lowered = name.lower()
    blocked = ["starbucks", "shangdao cafe", "星巴克", "85度c", "加州咖啡"]
    weak_place_terms = ["售楼", "营销中心", "生活馆", "服务中心", "停车场", "游客中心", "政务中心", "牌坊", "委员会", "管委会", "政府"]
    return any(item in lowered for item in blocked) or any(item in name for item in weak_place_terms)


def _amap_cost(item: dict) -> int:
    cost = (item.get("biz_ext") or {}).get("cost")
    try:
        value = int(float(cost)) if cost not in (None, "", "[]") else 0
    except (TypeError, ValueError):
        return 0
    return value if 0 <= value <= 500 else 0


def _amap_popularity(item: dict, keyword: str = "") -> int:
    text = " ".join(str(item.get(key, "")) for key in ["keytag", "type", "biz_type"])
    name = str(item.get("name") or "")
    score = 0
    if keyword and (keyword in name or name in keyword):
        score += 20
    if "5A" in text:
        score += 18
    if "4A" in text:
        score += 12
    if "国家级景点" in text:
        score += 10
    if "文物古迹" in text:
        score += 6
    if "博物馆" in text:
        score += 4
    return score


def _estimate_cost(tags: list[str], name: str = "") -> int:
    return 0


def _cost_note(cost: int, source: str | None = None) -> str:
    if cost == 0:
        return "未从搜索/地图数据确认票价，活动费暂不计入"
    return f"票价来自{source or '可验证来源'}，实际以官方价格为准"


def _osm_location(element: dict) -> str | None:
    if "lat" in element and "lon" in element:
        return f"{element['lon']},{element['lat']}"
    center = element.get("center")
    if center:
        return f"{center['lon']},{center['lat']}"
    return None


def _bbox_around(lat: float, lng: float, delta: float = 0.25) -> tuple[float, float, float, float]:
    return lat - delta, lng - delta, lat + delta, lng + delta
