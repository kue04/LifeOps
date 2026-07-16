from __future__ import annotations

import json
from pathlib import Path

import requests


CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "geocode_cache.json"

SEED_COORDS = {
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579),
    "杭州": (30.2741, 120.1551),
    "福州": (26.0745, 119.2965),
    "厦门": (24.4798, 118.0894),
}


def geocode_city(city: str) -> dict:
    cache = _load_cache()
    if city in cache:
        return cache[city]
    if city in SEED_COORDS:
        lat, lng = SEED_COORDS[city]
        result = {"name": city, "latitude": lat, "longitude": lng, "source": "seed"}
        _save_cache_item(city, result, cache)
        return result

    result = _geocode_with_nominatim(city)
    _save_cache_item(city, result, cache)
    return result


def geocode_place(query: str) -> dict:
    cache_key = f"place:{query}"
    cache = _load_cache()
    if cache_key in cache:
        return cache[cache_key]
    result = _geocode_with_nominatim(query)
    _save_cache_item(cache_key, result, cache)
    return result


def _geocode_with_nominatim(city: str) -> dict:
    for query in _query_variants(city):
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "addressdetails": 1,
                "accept-language": "zh-CN",
            },
            headers={"User-Agent": "LifeOpsAgent/0.1"},
            timeout=3,
        )
        response.raise_for_status()
        results = response.json()
        if results:
            item = results[0]
            return {
                "name": city,
                "display_name": item.get("display_name"),
                "latitude": float(item["lat"]),
                "longitude": float(item["lon"]),
                "boundingbox": item.get("boundingbox"),
                "source": "nominatim",
                "query": query,
            }
    raise RuntimeError(f"Nominatim cannot geocode city: {city}")


def _query_variants(city: str) -> list[str]:
    variants = [city]
    if not city.endswith("市"):
        variants.append(city + "市")
    variants.extend([f"{city}, 中国", f"{city}市, 中国"])
    return list(dict.fromkeys(variants))


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def _save_cache_item(city: str, result: dict, cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache[city] = result
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
