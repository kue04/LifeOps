"""攻略文案与消息组装：把结构化计划渲染成面向用户的自然语言。

从 agent/nodes.py 整组搬迁，闭包自洽，不依赖其他 Agent 节点。
"""

from __future__ import annotations

from typing import Any

from agent.constants import (
    CITY_GUIDE_INTROS,
    LOCAL_FOOD_TIPS_BY_CITY,
    NATIONAL_CHAIN_MEAL_WORDS,
)
from agent.intent_signals import (
    _is_travel_guide_plan,
)
from agent.place_utils import (
    _is_city_name,
    _meal_text,
)
from agent.state import AgentState
from agent.text_utils import (
    _access_route_message,
    _budget_message,
    _build_todo_message,
    _cost_text,
    _duration_from_time,
    _execution_summary,
    _guide_city,
    _guide_place_category,
    _guide_place_key,
    _guide_place_score,
    _guide_practical_tips,
    _linked_named_item,
    _linked_place,
    _linked_source,
    _recommendation_basis_message,
    _research_plan_note,
    _weather_advice,
)


def _guide_place_candidates(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    food_tags = {"美食", "火锅", "川菜", "小吃", "茶馆", "酒店", "住宿"}
    result = []
    for place in places:
        name = place.get("name")
        if not name or _is_city_placeholder_place(place):
            continue
        if set(place.get("tags") or []).intersection(food_tags):
            continue
        if any(word in str(name) for word in ["游客中心", "政务中心", "委员会", "停车场", "牌坊", "公交站", "物业", "酒店", "客栈", "民宿", "运营中心", "售票", "大厅", "广场", "涵松苑"]):
            continue
        result.append({
            "place": name,
            "area": place.get("area"),
            "address": place.get("address"),
            "map_url": place.get("map_url"),
            "tags": place.get("tags") or [],
            "play_points": place.get("play_points") or [],
            "evidence": place.get("evidence") or [],
            "popularity_score": place.get("popularity_score") or 0,
        })
    deduped = []
    seen = set()
    for item in sorted(result, key=lambda item: (_guide_place_score(item), int(item.get("popularity_score") or 0)), reverse=True):
        key = _guide_place_key(str(item.get("place") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:16]


def _is_city_placeholder_place(place: dict[str, Any]) -> bool:
    name = str(place.get("name") or "").strip()
    city = str(place.get("city") or "").strip()
    if not name or not city:
        return False
    return _is_city_name(name, city)


def _build_assistant_message(state: AgentState) -> str:
    return _build_assistant_message_from_plan(state.final_plan or {})


def _build_assistant_message_from_plan(plan: dict[str, Any]) -> str:
    if plan.get("task_type") == "todo":
        return _build_todo_message(plan)
    if plan.get("task_type") in {"errand", "meal"}:
        return _build_life_task_message(plan)
    if _is_travel_guide_plan(plan):
        return _build_travel_guide_message(plan)
    itinerary = plan.get("itinerary", [])
    title = plan.get("title", "这份计划")
    budget = plan.get("budget", {})
    risks = plan.get("risks", [])
    summary = plan.get("summary") or ""
    weather = plan.get("weather") or {}
    research = plan.get("travel_research") or {}
    lifestyle = plan.get("lifestyle_places") or {}
    access_route = plan.get("access_route") or {}
    lines = [f"**{title}**"]
    lines.append(_execution_summary(research, weather))
    if weather:
        lines.append(
            f"**天气与节奏**：{weather.get('date', '当天')} {weather.get('condition', '未知')}，"
            f"{weather.get('temperature', '温度未知')}。{_weather_advice(weather)}"
        )
    research_note = _research_plan_note(research)
    if research_note:
        lines.append(research_note)
    basis_note = _recommendation_basis_message(plan.get("recommendation_basis") or {})
    if basis_note:
        lines.append(basis_note)
    if access_route.get("needed"):
        lines.append(_access_route_message(access_route))
    if itinerary:
        lines.append("**到达后怎么玩**")
        for item in itinerary:
            place = _linked_place(item)
            play_points = "；".join(item.get("play_points", [])[:3])
            details = [
                f"- **{item['time']} | {place}**",
                f"  地址：{item.get('address') or item.get('area', '待确认')}；建议停留：{_duration_from_time(item.get('time', ''))}",
            ]
            cost_text = _cost_text(item)
            if cost_text:
                details.append(f"  费用：{cost_text}")
            evidence = item.get("evidence", [])
            if evidence:
                details.append("  搜索依据：" + "；".join(evidence[:2]))
            if play_points:
                details.append(f"  怎么玩：{play_points}")
            if item.get("reason"):
                details.append(f"  为什么放这里：{item['reason']}")
            lines.append("\n".join(details))
    if summary:
        lines.append(summary)
    alternatives = plan.get("alternatives") or []
    if alternatives:
        lines.append("**方案二：可替换玩法**")
        for item in alternatives[:4]:
            parts = [f"- {_linked_place({'place': item['name'], 'map_url': item.get('map_url')})}"]
            if item.get("address"):
                parts.append(f"地址：{item['address']}")
            play_points = "；".join(item.get("play_points", [])[:2])
            if play_points:
                parts.append(f"亮点：{play_points}")
            lines.append("  ".join(parts))
    if budget:
        lines.append(_budget_message(budget))
    living_tips = _living_tips(plan, lifestyle)
    if living_tips:
        lines.append(living_tips)
    if risks:
        lines.append("**提醒**：" + "；".join(risks))
    sources = research.get("sources") or []
    if sources:
        lines.append("**参考来源**：" + "；".join(_linked_source(item) for item in sources[:4]))
    return "\n\n".join(lines)


def _build_travel_guide_message(plan: dict[str, Any]) -> str:
    city = _guide_city(plan)
    weather = plan.get("weather") or {}
    research = plan.get("travel_research") or {}
    budget = plan.get("budget") or {}
    risks = plan.get("risks") or []
    places = _guide_places(plan)
    meals = _guide_meals(plan.get("meal_candidates") or (plan.get("lifestyle_places") or {}).get("foods") or [])
    lines = [f"**{city}美食 + 美景攻略**"]
    lines.append(CITY_GUIDE_INTROS.get(city, f"这份攻略围绕{city}的核心景点、餐饮和顺路动线来安排，适合直接拿去做出行参考。"))
    lines.append(_execution_summary(research, weather))
    basis_note = _recommendation_basis_message(plan.get("recommendation_basis") or {})
    if basis_note:
        lines.append(basis_note)
    if weather:
        lines.append(
            f"**天气与节奏**：{weather.get('date', '当天')} {weather.get('condition', '未知')}，"
            f"{weather.get('temperature', '温度未知')}。{_weather_advice(weather)}"
        )
    if places:
        lines.append("**必打卡景点**")
        lines.extend(_guide_place_line(item) for item in places[:5])
    if meals:
        lines.append("**火锅精选推荐**")
        lines.extend(_guide_meal_line(item) for item in meals[:5])
    food_tips = LOCAL_FOOD_TIPS_BY_CITY.get(city) or []
    if food_tips:
        lines.append("**风味美食 & 经典小吃**")
        lines.extend(f"- {item}" for item in food_tips)
    itinerary = plan.get("itinerary") or []
    if itinerary:
        lines.append("**精选行程规划**")
        lines.extend(_guide_itinerary_line(item) for item in itinerary)
    if budget:
        lines.append(_budget_message(budget))
    tips = _guide_practical_tips(city, plan)
    if tips:
        lines.append("**出行实用贴士**")
        lines.extend(f"- {tip}" for tip in tips)
    if risks:
        lines.append("**提醒**：" + "；".join(risks))
    sources = research.get("sources") or []
    if sources:
        lines.append("**参考来源**：" + "；".join(_linked_source(item) for item in sources[:4]))
    return "\n\n".join(lines)


def _guide_places(plan: dict[str, Any]) -> list[dict[str, Any]]:
    food_tags = {"美食", "火锅", "川菜", "小吃", "茶馆"}
    items: list[dict[str, Any]] = []
    for item in plan.get("itinerary") or []:
        if not set(item.get("tags") or []).intersection(food_tags):
            items.append(item)
    for item in plan.get("guide_places") or []:
        items.append(item)
    for item in plan.get("alternatives") or []:
        items.append({
            "place": item.get("name"),
            "area": item.get("address") or "",
            "address": item.get("address"),
            "map_url": item.get("map_url"),
            "tags": item.get("tags") or [],
            "play_points": item.get("play_points") or [],
        })
    sorted_items = sorted(items, key=_guide_place_score, reverse=True)
    seen = set()
    result = []
    for category in ["culture", "water_street", "pickle", "ancient_town", "mountain", "view", "museum"]:
        match = next(
            (
                item for item in sorted_items
                if _guide_place_category(item) == category
                and _guide_place_key(str(item.get("place") or item.get("name") or "")) not in seen
            ),
            None,
        )
        if match:
            key = _guide_place_key(str(match.get("place") or match.get("name") or ""))
            seen.add(key)
            result.append(match)
    for item in sorted_items:
        name = item.get("place") or item.get("name")
        key = _guide_place_key(str(name or ""))
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _guide_meals(meals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    local_meals = [item for item in meals if not _is_national_chain_meal(item)]
    return local_meals if len(local_meals) >= 3 else meals


def _guide_place_line(item: dict[str, Any]) -> str:
    name = item.get("place") or item.get("name") or "景点"
    area = item.get("area") or item.get("address") or "地址待确认"
    tags = set(item.get("tags") or [])
    points = "；".join(item.get("play_points") or [])
    if "爬山" in tags or "运动" in tags:
        reason = "自然风光和徒步体验更强，建议预留半天到一天，雨天注意防滑。"
    elif any(word in str(name) for word in ["祠", "故居", "三苏"]):
        reason = "适合放在上午慢慢看，重点感受东坡文化和老城人文底色。"
    elif "泡菜" in str(name):
        reason = "适合了解东坡泡菜和地方饮食文化，也适合作为轻量室内段。"
    elif "博物馆" in tags or "展览" in tags:
        reason = "适合了解地方文化，也能作为天气不稳时的室内段。"
    elif any(word in str(name) for word in ["街", "水街", "老街", "古镇"]):
        reason = "适合慢逛、拍照和安排夜景，餐后散步也顺手。"
    elif "楼" in str(name):
        reason = "适合登楼或临江观景，作为市区文化散步的一段。"
    else:
        reason = points or "适合作为城市游主线点位，出发前确认开放时间。"
    return f"- **{_linked_place(item)}**：{area}。{reason}"


def _guide_meal_line(item: dict[str, Any]) -> str:
    address = item.get("address") or item.get("area") or "地址待确认"
    tags = "、".join(item.get("tags") or [])
    reason = item.get("reason") or "适合作为本次用餐候选，排队和营业时间出发前确认。"
    cost = int(item.get("estimated_cost") or 0)
    cost_text = f"；参考人均约 {cost} 元" if cost else ""
    return f"- **{_linked_named_item(item)}**：{tags or '餐饮'}；{reason}{cost_text}；地址：{address}"


def _guide_itinerary_line(item: dict[str, Any]) -> str:
    place = _linked_place(item)
    points = "；".join(item.get("play_points") or [])
    suffix = f"。{points}" if points else ""
    return f"- **{item.get('time', '时间待定')} | {place}**：{item.get('address') or item.get('area') or '地点待确认'}{suffix}"


def _build_life_task_message(plan: dict[str, Any]) -> str:
    lines = [f"**{plan.get('title', '生活任务计划')}**"]
    if plan.get("summary"):
        lines.append(plan["summary"])
    itinerary = plan.get("itinerary") or []
    if itinerary:
        lines.append("**执行时间轴**")
        for item in itinerary:
            details = [f"- **{item.get('time', '时间待定')} | {_linked_place(item)}**"]
            details.append(f"  地址/位置：{item.get('address') or item.get('area') or '待确认'}")
            if item.get("reason"):
                details.append(f"  理由：{item['reason']}")
            points = "；".join(item.get("play_points") or [])
            if points:
                details.append(f"  完成标准：{points}")
            lines.append("\n".join(details))
    if plan.get("budget"):
        lines.append(_budget_message(plan["budget"]))
    confirm = plan.get("confirm_actions") or []
    if confirm:
        lines.append("**待确认动作**：" + "；".join(item.get("label", "需要确认") for item in confirm))
    return "\n\n".join(lines)


def _living_tips(plan: dict[str, Any], lifestyle: dict[str, list[dict]] | None = None) -> str:
    city = (plan.get("title") or "").split("轻松")[0].split("一日")[0] or "目的地"
    itinerary = plan.get("itinerary", [])
    areas = [item.get("area") for item in itinerary if item.get("area")]
    area_text = "、".join(dict.fromkeys(areas[:3])) if areas else "主线景点附近"
    foods = (lifestyle or {}).get("foods", [])
    hotels = (lifestyle or {}).get("hotels", [])
    food_text = "、".join(_linked_named_item(item) for item in foods[:3]) if foods else f"{city}本地小吃/特色餐厅"
    hotel_text = "、".join(_linked_named_item(item) for item in hotels[:3]) if hotels else f"{area_text}或交通枢纽附近酒店"
    return (
        "**衣食住行小贴士**："
        f"穿着以舒适鞋为主，{area_text}之间建议优先地铁/网约车衔接；"
        f"中午可以考虑 {food_text}，少绕路；"
        f"如果住一晚，可优先看 {hotel_text}，第二天移动成本更低。"
    )


def _is_national_chain_meal(item: dict[str, Any]) -> bool:
    text = _meal_text(item)
    return any(word in text for word in NATIONAL_CHAIN_MEAL_WORDS)
