from __future__ import annotations

import requests

from config import settings
from services.geocoder import geocode_city


def get_weather(city: str, date: str | None = None) -> dict:
    try:
        if settings.weather_provider == "amap":
            return _get_amap_weather(city, date)
        if settings.weather_provider == "openmeteo":
            return _get_openmeteo_weather(city, date)
        if settings.weather_provider == "openweather":
            return _get_openweather(city, date)
        return _mock_weather(city, date)
    except Exception as exc:
        fallback = _mock_weather(city, date)
        fallback["provider"] = "mock"
        fallback["provider_warning"] = f"{settings.weather_provider}: {exc}"
        return fallback


def _safe_openmeteo_weather(city: str, date: str | None) -> dict:
    try:
        return _get_openmeteo_weather(city, date)
    except Exception as exc:
        fallback = _mock_weather(city, date)
        fallback["provider"] = "mock"
        fallback["provider_warning"] = f"openmeteo: {exc}"
        return fallback


def _get_openmeteo_weather(city: str, date: str | None) -> dict:
    location = _resolve_city_location(city)
    forecast = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "Asia/Shanghai",
            "forecast_days": 14,
        },
        timeout=10,
    )
    forecast.raise_for_status()
    data = forecast.json()
    daily = data.get("daily", {})
    times = daily.get("time", [])
    index = times.index(date) if date in times else 0
    code = daily.get("weather_code", [None])[index]
    rain_probability = daily.get("precipitation_probability_max", [0])[index] or 0
    temp_min = daily.get("temperature_2m_min", ["?"])[index]
    temp_max = daily.get("temperature_2m_max", ["?"])[index]
    condition = _openmeteo_condition(code)
    return {
        "city": city,
        "date": times[index] if times else date or "未指定",
        "condition": condition,
        "temperature": f"{temp_min}-{temp_max}C",
        "precipitation_probability": rain_probability,
        "outdoor_risk": "medium" if rain_probability >= 40 or "雨" in condition else "low",
        "provider": "openmeteo",
        "raw": {"location": location, "forecast": data},
    }


def _resolve_city_location(city: str) -> dict:
    return geocode_city(city)


def _get_openweather(city: str, date: str | None) -> dict:
    if not settings.openweather_api_key:
        raise RuntimeError("OPENWEATHER_API_KEY is required when WEATHER_PROVIDER=openweather")
    response = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={
            "q": city,
            "appid": settings.openweather_api_key,
            "units": "metric",
            "lang": "zh_cn",
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    condition = data["weather"][0]["description"]
    temp = data["main"]["temp"]
    rain_risk = "medium" if any(word in condition for word in ["雨", "rain"]) else "low"
    return {
        "city": city,
        "date": date or "未指定",
        "condition": condition,
        "temperature": f"{temp:.0f}C",
        "outdoor_risk": rain_risk,
        "provider": "openweather",
        "raw": data,
    }


def _get_amap_weather(city: str, date: str | None) -> dict:
    if not settings.amap_api_key:
        raise RuntimeError("AMAP_API_KEY is required when WEATHER_PROVIDER=amap")
    city_code = _amap_city_code(city)
    response = requests.get(
        "https://restapi.amap.com/v3/weather/weatherInfo",
        params={
            "key": settings.amap_api_key,
            "city": city_code,
            "extensions": "base",
            "output": "JSON",
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "1":
        raise RuntimeError(data.get("info") or "amap weather failed")
    live = (data.get("lives") or [{}])[0]
    condition = live.get("weather") or "未知"
    temperature = live.get("temperature")
    return {
        "city": city,
        "date": date or live.get("reporttime") or "未指定",
        "condition": condition,
        "temperature": f"{temperature}C" if temperature else "未知",
        "outdoor_risk": "medium" if any(word in condition for word in ["雨", "雪", "霾", "雾"]) else "low",
        "provider": "amap",
        "raw": data,
    }


def _amap_city_code(city: str) -> str:
    response = requests.get(
        "https://restapi.amap.com/v3/geocode/geo",
        params={
            "key": settings.amap_api_key,
            "address": city,
            "city": city,
            "output": "JSON",
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    geocodes = data.get("geocodes") or []
    if geocodes:
        return geocodes[0].get("adcode") or city
    return city


def _mock_weather(city: str, date: str | None) -> dict:
    weather_by_city = {
        "杭州": {"condition": "小雨", "temperature": "20-25C", "outdoor_risk": "medium"},
        "福州": {"condition": "多云", "temperature": "23-29C", "outdoor_risk": "low"},
        "厦门": {"condition": "多云", "temperature": "24-29C", "outdoor_risk": "low"},
        "上海": {"condition": "多云", "temperature": "21-27C", "outdoor_risk": "low"},
        "北京": {"condition": "晴", "temperature": "18-28C", "outdoor_risk": "low"},
    }
    return weather_by_city.get(
        city,
        {"condition": "多云", "temperature": "20-26C", "outdoor_risk": "low"},
    ) | {"city": city, "date": date or "未指定", "provider": "mock"}


def _openmeteo_condition(code: int | None) -> str:
    if code is None:
        return "未知"
    if code == 0:
        return "晴"
    if code in {1, 2, 3}:
        return "多云"
    if code in {45, 48}:
        return "雾"
    if code in {51, 53, 55, 56, 57}:
        return "毛毛雨"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "雨"
    if code in {71, 73, 75, 77, 85, 86}:
        return "雪"
    if code in {95, 96, 99}:
        return "雷雨"
    return "未知"
