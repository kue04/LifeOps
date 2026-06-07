from __future__ import annotations

import math
from urllib.parse import quote

import requests

from config import settings


def estimate_route(places: list[dict]) -> dict:
    ordered = _order_by_location(places) or sorted(places, key=lambda place: (place["area"], place["duration_minutes"]))
    total_minutes = 0
    legs = []
    previous = "出发地"
    previous_place = None
    for place in ordered:
        travel_minutes = 25 if previous_place is None else _travel_minutes(previous_place, place)
        total_minutes += travel_minutes
        legs.append({"from": previous, "to": place["name"], "minutes": travel_minutes, "provider": "estimated"})
        previous = place["name"]
        previous_place = place
    return {
        "ordered_places": ordered,
        "legs": legs,
        "travel_minutes": total_minutes,
        "provider": "estimated",
    }


def estimate_access_route(origin: dict | None, destination: dict | None) -> dict:
    if not origin or not destination:
        return {
            "needed": False,
            "provider": "none",
            "summary": "没有明确出发地或目的地，暂不生成到达路线",
            "steps": [],
            "warnings": [],
        }
    origin_label = origin.get("name") or origin.get("city") or origin.get("raw") or "出发地"
    destination_label = destination.get("name") or destination.get("raw") or "目的地"
    result = {
        "needed": True,
        "from": origin_label,
        "to": destination_label,
        "provider": "estimated",
        "summary": f"从{origin_label}前往{destination_label}，跨城交通班次需以官方平台实时查询为准",
        "mode": "mixed",
        "minutes": None,
        "distance_km": None,
        "steps": [
            f"从{origin_label}出发，优先查询高铁/长途交通到{destination_label}附近枢纽",
            f"到达后转乘景区接驳、公交或网约车前往{destination_label}入口",
        ],
        "map_url": _map_url(origin_label, destination_label),
        "warnings": ["跨城火车/高铁/景区接驳班次变化较快，出发前需要在官方平台确认"],
    }
    amap = _estimate_amap_driving(origin, destination)
    return result | amap if amap else result


def _order_by_location(places: list[dict]) -> list[dict] | None:
    if len(places) <= 1 or any(_coordinates(place) is None for place in places):
        return None
    remaining = places[:]
    ordered = [remaining.pop(0)]
    while remaining:
        current = ordered[-1]
        next_index = min(
            range(len(remaining)),
            key=lambda index: _distance_km(current, remaining[index]),
        )
        ordered.append(remaining.pop(next_index))
    return ordered


def _travel_minutes(a: dict, b: dict) -> int:
    distance = _distance_km(a, b)
    if distance is None:
        return 18
    return max(12, min(50, int(distance * 5) + 8))


def _distance_km(a: dict, b: dict) -> float | None:
    coord_a = _coordinates(a)
    coord_b = _coordinates(b)
    if not coord_a or not coord_b:
        return None
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


def _coordinates(place: dict) -> tuple[float, float] | None:
    location = place.get("location")
    if not isinstance(location, str) or "," not in location:
        return None
    lon, lat = location.split(",", 1)
    try:
        return float(lon), float(lat)
    except ValueError:
        return None


def _estimate_amap_driving(origin: dict, destination: dict) -> dict | None:
    if not settings.amap_api_key:
        return None
    origin_coord = _coordinates(origin)
    destination_coord = _coordinates(destination)
    if not origin_coord or not destination_coord:
        return None
    origin_text = f"{origin_coord[0]},{origin_coord[1]}"
    destination_text = f"{destination_coord[0]},{destination_coord[1]}"
    try:
        response = requests.get(
            "https://restapi.amap.com/v3/direction/driving",
            params={
                "key": settings.amap_api_key,
                "origin": origin_text,
                "destination": destination_text,
                "extensions": "base",
            },
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None
    if data.get("status") != "1":
        return None
    paths = (data.get("route") or {}).get("paths") or []
    if not paths:
        return None
    path = paths[0]
    try:
        distance_km = round(int(path.get("distance", 0)) / 1000, 1)
        minutes = max(1, round(int(path.get("duration", 0)) / 60))
    except (TypeError, ValueError):
        distance_km = None
        minutes = None
    return {
        "provider": "amap_driving",
        "mode": "driving",
        "minutes": minutes,
        "distance_km": distance_km,
        "summary": f"高德估算驾车约{distance_km}公里，约{minutes}分钟；公共交通/高铁仍需单独确认",
        "steps": ["高德驾车路线可作为到达耗时参考", "若跨城出行，优先以铁路/航班/客运官方班次为准"],
    }


def _map_url(origin: str, destination: str) -> str:
    return "https://ditu.amap.com/dir?from%5Bname%5D={}&to%5Bname%5D={}".format(
        quote(origin),
        quote(destination),
    )
