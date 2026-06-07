from __future__ import annotations


def estimate_budget(places: list[dict], budget_limit: int | None = None, pace: str | None = None) -> dict:
    known_places = [place for place in places if place.get("cost_known") or int(place.get("estimated_cost", 0)) > 0]
    unknown_places = [place["name"] for place in places if not place.get("cost_known") and int(place.get("estimated_cost", 0)) == 0]
    activity_cost = sum(int(place["estimated_cost"]) for place in known_places)
    target_total = _target_total(budget_limit)
    meal_budget = _meal_budget(budget_limit, pace, target_total, activity_cost)
    transport_budget = _transport_budget(places, budget_limit, target_total, activity_cost + meal_budget)
    total = activity_cost + meal_budget + transport_budget
    return {
        "activity_cost": activity_cost,
        "meal_budget": meal_budget,
        "transport_budget": transport_budget,
        "budget_limit": budget_limit,
        "target_total": target_total,
        "budget_usage": round(total / budget_limit, 2) if budget_limit else None,
        "unknown_activity_cost_items": unknown_places,
        "total": total,
    }


def _target_total(budget_limit: int | None) -> int | None:
    if budget_limit is None:
        return None
    return int(budget_limit * 0.75)


def _meal_budget(budget_limit: int | None, pace: str | None, target_total: int | None, activity_cost: int) -> int:
    if budget_limit is None:
        return 100
    if budget_limit <= 200:
        return 60
    if budget_limit <= 500:
        base = 150 if pace in {"中等", "紧凑"} else 130
    else:
        base = 220
    if target_total:
        base = max(base, min(260, target_total - activity_cost - 100))
    return max(60, base)


def _transport_budget(places: list[dict], budget_limit: int | None, target_total: int | None, used: int) -> int:
    base = 30 + max(0, len(places) - 1) * 20
    if budget_limit is not None and budget_limit <= 200:
        return min(base, 50)
    if len({place.get("area") for place in places}) > 1:
        base += 30
    if target_total:
        base = max(base, min(160, target_total - used))
    return max(30, min(base, 180))
