from __future__ import annotations


ACTIVE_TAGS = {"爬山", "徒步", "登山", "运动"}
INDOOR_TAGS = {"室内", "展览", "博物馆", "书店"}
OUTDOOR_TAGS = {"室外", "散步", "夜景", "公园", "爬山", "徒步", "登山", "运动"}


def score_candidates(
    places: list[dict],
    preferences: list[str],
    budget: int | None,
    pace: str | None,
    weather: dict,
) -> list[dict]:
    preference_set = set(preferences)
    scored = []
    for place in places:
        components = _score_components(place, preference_set, budget, pace, weather)
        quality_penalty = _quality_penalty(place)
        score = sum(components.values()) - quality_penalty
        scored.append(
            place
            | {
                "score": score,
                "score_components": components | {"quality_penalty": -quality_penalty},
                "score_reasons": _reasons(place, preference_set, budget, pace, weather, components),
            }
        )
    return sorted(scored, key=lambda item: item["score"], reverse=True)


def _score_components(place: dict, preferences: set[str], budget: int | None, pace: str | None, weather: dict) -> dict[str, int]:
    tags = set(place.get("tags", []))
    cost = int(place.get("estimated_cost", 0))
    duration = int(place.get("duration_minutes", 90))

    matched = preferences.intersection(tags)
    preference_score = min(30, len(matched) * 15)

    active_requested = bool(preferences.intersection(ACTIVE_TAGS))
    active_place = bool(tags.intersection(ACTIVE_TAGS))
    activity_score = 12 if active_requested and active_place else 4 if active_place else 0

    budget_score = _budget_score(cost, budget)
    duration_score = _duration_score(duration, active_requested, active_place)
    weather_score = _weather_score(tags, weather)
    pace_score = _pace_score(place, pace, active_place, duration)
    popularity_score = _popularity_score(place)
    source_rank_score = _source_rank_score(place)
    goal_match_score = _goal_match_score(place)

    return {
        "preference": preference_score,
        "goal_match": goal_match_score,
        "activity": activity_score,
        "popularity": popularity_score,
        "source_rank": source_rank_score,
        "budget": budget_score,
        "duration": duration_score,
        "weather": weather_score,
        "pace": pace_score,
    }


def _budget_score(cost: int, budget: int | None) -> int:
    if budget is None:
        return 14
    if cost == 0:
        return 18
    ratio = cost / max(budget, 1)
    if ratio <= 0.2:
        return 18
    if ratio <= 0.5:
        return 12
    return 6


def _duration_score(duration: int, active_requested: bool, active_place: bool) -> int:
    if active_requested and active_place:
        if duration >= 150:
            return 18
        if duration >= 90:
            return 14
        return 8
    if 60 <= duration <= 150:
        return 14
    if duration < 60:
        return 8
    return 10


def _weather_score(tags: set[str], weather: dict) -> int:
    risky_outdoor = weather.get("outdoor_risk") == "medium" and bool(tags.intersection(OUTDOOR_TAGS))
    if risky_outdoor:
        return 4
    if weather.get("outdoor_risk") == "medium" and bool(tags.intersection(INDOOR_TAGS)):
        return 14
    return 10


def _pace_score(place: dict, pace: str | None, active_place: bool, duration: int) -> int:
    intensity = place.get("intensity")
    if pace in {"紧凑", "中等"}:
        if active_place or intensity in {"中", "高"} or duration >= 150:
            return 12
        return 5
    if pace == "轻松":
        if intensity == "低" and duration <= 150:
            return 12
        if active_place:
            return 4
        return 8
    return 8


def _popularity_score(place: dict) -> int:
    score = int(place.get("popularity_score", 0) or 0)
    if place.get("event_score"):
        score += 8
    if place.get("evidence"):
        score += min(10, len(place.get("evidence", [])) * 4)
    rating = place.get("rating")
    try:
        rating_value = float(rating)
    except (TypeError, ValueError):
        rating_value = 0
    if rating_value >= 4.6:
        score += 8
    elif rating_value >= 4.2:
        score += 5
    return min(score, 28)


def _goal_match_score(place: dict) -> int:
    return min(int(place.get("goal_match_score", 0) or 0), 24)


def _source_rank_score(place: dict) -> int:
    if place.get("provider") == "curated":
        return 18
    order = place.get("source_order")
    if not isinstance(order, int):
        return 0
    if order < 8:
        return 8
    if order < 24:
        return 5
    return 2


def _quality_penalty(place: dict) -> int:
    name = place.get("name", "").lower()
    if name in {"星巴克", "starbucks"}:
        return 8
    if name.isascii():
        return 4
    return 0


def _reasons(place: dict, preferences: set[str], budget: int | None, pace: str | None, weather: dict, components: dict[str, int]) -> list[str]:
    tags = set(place.get("tags", []))
    matched = preferences.intersection(tags)
    reasons = []

    if matched:
        reasons.append("匹配偏好：" + "、".join(sorted(matched)))
    if components.get("goal_match", 0) >= 12:
        reasons.append("更贴合这次出行目标")
    if preferences.intersection(ACTIVE_TAGS) and tags.intersection(ACTIVE_TAGS):
        reasons.append("运动量更足，适合爬坡/徒步")
    if components.get("popularity", 0) >= 16:
        reasons.append("网页资料/当地热度更高，优先级靠前")
    elif components.get("popularity", 0) >= 8:
        reasons.append("有网页资料或评分热度支撑")
    if weather.get("outdoor_risk") == "medium" and tags.intersection(OUTDOOR_TAGS):
        reasons.append("雨天室外有风险，需防滑和备选方案")
    elif weather.get("outdoor_risk") == "medium" and tags.intersection(INDOOR_TAGS):
        reasons.append("室内为主，雨天稳定性更好")
    if components["budget"] >= 18:
        reasons.append("费用低，预算压力小")
    if components["duration"] >= 18:
        reasons.append("停留时间长，能满足深度游玩")
    if pace in {"紧凑", "中等"} and components["pace"] >= 12:
        reasons.append("节奏和体力消耗匹配")
    if pace == "轻松" and components["pace"] >= 12:
        reasons.append("适合轻松节奏")

    return reasons or ["综合评分较稳"]
