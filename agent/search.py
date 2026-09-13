"""网页检索与攻略研究：构造查询词、抓取搜索证据、补充候选地点。

从 agent/nodes.py 整组搬迁，闭包自洽，不依赖其他 Agent 节点。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from agent.intent import (
    _looks_like_travel_request,
)
from agent.intent_signals import (
    _dynamic_city,
    _is_mountain_or_hiking_trip,
    _text_has_attraction_or_guide_signal,
    _text_has_recent_activity_signal,
    _text_has_travel_content_signal,
)
from agent.place_utils import (
    _city_travel_search_preferences,
    _explicit_non_default_city,
    _is_encyclopedia_host,
    _meal_search_words,
)
from agent.state import AgentState
from agent.text_utils import (
    _dedupe_text_parts,
    _filter_places_by_city,
    _intent_has,
    _looks_like_city_overview_title,
    _looks_like_search_place_name,
    _search_result_key,
)
from tools.places import search_places
from tools.web_search import search_web


def _travel_preferences(preferences: list[str]) -> list[str]:
    return [preference for preference in preferences if preference not in _meal_search_words() and preference != "缇庨"]


def _search_web_for_travel(state: AgentState, query: str, max_results: int = 10, min_results: int = 5) -> dict[str, Any]:
    primary = _filter_travel_search_data(search_web(query, max_results=max_results), state)
    if not _search_should_filter_for_travel(state) or len(primary.get("results") or []) >= min_results:
        return primary
    combined = dict(primary)
    combined_results = list(primary.get("results") or [])
    seen = {_search_result_key(item) for item in combined_results}
    supplemental_queries = []
    supplemental_attempts = []
    for supplemental_query in _supplemental_travel_search_queries(state, query):
        if len(combined_results) >= min_results:
            break
        supplemental_queries.append(supplemental_query)
        extra = _filter_travel_search_data(search_web(supplemental_query, max_results=max_results), state)
        added = 0
        for item in extra.get("results") or []:
            key = _search_result_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            combined_results.append(item)
            added += 1
            if len(combined_results) >= min_results:
                break
        supplemental_attempts.append({
            "query": supplemental_query,
            "provider": extra.get("provider"),
            "results_count": len(extra.get("results") or []),
            "added_count": added,
        })
    combined["results"] = combined_results
    combined["filtered_results_count"] = len(combined_results)
    combined["minimum_results_target"] = min_results
    if supplemental_queries:
        combined["supplemental_queries"] = supplemental_queries
        combined["supplemental_attempts"] = supplemental_attempts
        note = str(combined.get("note") or "").strip()
        supplement_note = "网页来源不足时已补充景点/路线类查询"
        combined["note"] = f"{note}；{supplement_note}" if note else supplement_note
    return combined


def _supplemental_travel_search_queries(state: AgentState, primary_query: str) -> list[str]:
    destination = state.constraints.get("destination") or {}
    city = _search_query_city(state, destination) or _dynamic_city(state) or ""
    destination_name = state.constraints.get("destination_place") or destination.get("name") or ""
    base = " ".join(part for part in [city, destination_name] if part).strip() or primary_query
    queries = [
        f"{base} 必去景点 推荐 攻略",
        f"{base} 一日游 路线 攻略 景点",
        f"{base} 热门景点 榜单 游玩",
        f"{base} 旅游攻略 美食 交通",
    ]
    return [query for query in _dedupe_text_parts(queries) if query and query != primary_query]


def _search_query_city(state: AgentState, destination: dict[str, Any]) -> str:
    destination_city = state.constraints.get("destination_city") or destination.get("city")
    if destination_city:
        return str(destination_city)
    city = state.constraints.get("city") or ""
    default_city = state.constraints.get("default_city") or ""
    explicit_city = _explicit_non_default_city(state.user_input, default_city)
    if explicit_city:
        return explicit_city
    destination_name = state.constraints.get("destination_place") or destination.get("name")
    if destination_name and default_city and city == default_city:
        return ""
    return str(city)


def _search_query_terms(state: AgentState, destination: dict[str, Any], days: int) -> list[str]:
    text = state.user_input
    preferences = set(state.constraints.get("preferences") or [])
    activity_intent = state.constraints.get("activity_intent")
    destination_type = destination.get("type") or state.constraints.get("destination_type")
    route_scope = state.constraints.get("route_scope")
    terms = ["旅游景点推荐", "必去景点", "游玩攻略", "路线攻略"]

    if route_scope in {"city_trip", "cross_city_trip"} or destination_type in {"city", "district"} or (state.constraints.get("city") and not destination):
        terms.extend(["热门景点", "美食攻略", "交通"])
        if days > 1:
            terms.append(f"{days}日游攻略")

    if "展览" in preferences or activity_intent in {"看展", "展览"}:
        terms.extend(["展览", "美术馆", "博物馆", "预约"])
    if "散步" in preferences or activity_intent == "散步":
        terms.extend(["散步", "公园", "街区"])
    if "夜景" in preferences or activity_intent == "夜景":
        terms.extend(["夜景", "观景"])
    if "海边" in preferences or "海边" in text:
        terms.extend(["海边", "海滨", "沙滩", "看海"])

    if _is_mountain_or_hiking_trip(text, destination, preferences, activity_intent):
        terms.extend(["登山路线", "开放时间", "门票", "索道", "景区换乘"])
    elif destination_type in {"poi", "scenic_area"}:
        terms.extend(["开放时间", "门票", "预约", "周边"])

    return _dedupe_text_parts(terms)


def _search_city_trip_places(city: str, state: AgentState) -> list[dict[str, Any]]:
    try:
        places = search_places(
            city,
            _city_travel_search_preferences(state, []),
            state.constraints.get("avoid") or [],
            state.constraints.get("hotel_brand"),
        )
    except Exception:
        return []
    return _filter_places_by_city(places, city)


def _filter_travel_search_data(search_data: dict[str, Any], state: AgentState) -> dict[str, Any]:
    if not _search_should_filter_for_travel(state):
        return search_data
    results = search_data.get("results") or []
    if not results:
        return search_data
    kept = []
    filtered_titles = []
    for item in results:
        if _is_useful_travel_search_result(item, state):
            kept.append(item)
        else:
            filtered_titles.append(item.get("name") or item.get("title") or item.get("url") or "搜索结果")
    if not filtered_titles:
        return search_data
    filtered = dict(search_data)
    filtered["results"] = kept
    filtered["raw_results_count"] = len(results)
    filtered["filtered_results_count"] = len(kept)
    filtered["filtered_out"] = filtered_titles[:6]
    note = str(search_data.get("note") or "").strip()
    filter_note = "已过滤城市百科/概况类搜索结果"
    filtered["note"] = f"{note}；{filter_note}" if note else filter_note
    return filtered


def _search_should_filter_for_travel(state: AgentState) -> bool:
    if _intent_has(state, "travel"):
        return True
    return state.constraints.get("task_type") in {None, "travel", "mixed"} or _looks_like_travel_request(state.user_input)


def _is_useful_travel_search_result(item: dict[str, Any], state: AgentState) -> bool:
    title = str(item.get("name") or item.get("title") or "")
    content = str(item.get("summary") or item.get("snippet") or item.get("content") or "")
    text = f"{title} {content}"
    if _is_city_overview_search_result(item, state):
        return False
    return _text_has_travel_content_signal(text) or _text_has_specific_place_signal(text)


def _is_city_overview_search_result(item: dict[str, Any], state: AgentState) -> bool:
    title = str(item.get("name") or item.get("title") or "")
    content = str(item.get("summary") or item.get("snippet") or item.get("content") or "")
    url = str(item.get("url") or "")
    host = urlparse(url).netloc.lower()
    text = f"{title} {content}"
    city = _dynamic_city(state) or _search_query_city(state, state.constraints.get("destination") or {})
    destination = state.constraints.get("destination") or {}
    destination_name = str(destination.get("name") or state.constraints.get("destination_place") or "")
    if _text_has_attraction_or_guide_signal(text) and not _is_encyclopedia_host(host):
        return False
    if city and _looks_like_city_overview_title(title, city):
        return True
    if destination_name and destination.get("type") in {"city", "district"} and _looks_like_city_overview_title(title, destination_name):
        return True
    overview_words = ["百科", "维基百科", "城市概况", "城市介绍", "市情", "区情", "行政区划", "历史沿革", "地理环境", "人口", "人民政府", "政府门户"]
    if _is_encyclopedia_host(host) and any(word in text for word in overview_words):
        return True
    if (host.endswith(".gov.cn") or ".gov.cn" in host) and any(word in text for word in overview_words):
        return True
    return False


def _text_has_specific_place_signal(text: str) -> bool:
    pattern = re.compile(r"[\u4e00-\u9fff]{2,12}(?:风景区|景区|博物馆|美术馆|公园|古镇|老街|花市|湿地|民族村|寺|祠|楼|塔|坊|湖|池|山|街|巷|园|城)")
    return any(_looks_like_search_place_name(match.strip()) for match in pattern.findall(text))


def _build_travel_research(search_data: dict[str, Any]) -> dict[str, Any]:
    results = search_data.get("results") or []
    sources = []
    activity_sources = []
    for item in results:
        title = item.get("name") or item.get("title") or item.get("url") or "搜索结果"
        url = item.get("url")
        content = item.get("content") or item.get("snippet") or ""
        if url:
            source = {"title": title, "url": url, "content": content[:160], "date": item.get("datePublished")}
            sources.append(source)
            if _text_has_recent_activity_signal(f"{title} {content}"):
                activity_sources.append(source)
    return {
        "provider": search_data.get("provider"),
        "query": search_data.get("query"),
        "answer": search_data.get("answer"),
        "sources": sources,
        "activity_sources": activity_sources[:4],
        "note": search_data.get("note"),
        "attempts": search_data.get("attempts") or [],
    }
