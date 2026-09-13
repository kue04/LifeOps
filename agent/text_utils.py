"""文本、格式化与摘要工具：预览文案、去重、费用/时长格式化、日志与 LLM 开关。

从 agent/nodes.py 抽出的叶子工具函数，不依赖 Agent 流程状态，
可被约束抽取、规划、评分、反思等节点共用。
"""

from __future__ import annotations

import re
from typing import Any

from agent.constants import (
    FAMOUS_DESTINATIONS,
    MEAL_INTENT_WORDS,
)
from agent.state import AgentState
from config import settings


def _access_route_message(access_route: dict[str, Any]) -> str:
    lines = [f"**怎么到达**：{access_route.get('summary') or '到达路线需出发前确认'}"]
    steps = access_route.get("steps") or []
    if steps:
        lines.append("；".join(str(step) for step in steps[:3]))
    warnings = access_route.get("warnings") or []
    if warnings:
        lines.append("提醒：" + "；".join(str(item) for item in warnings[:2]))
    return " ".join(lines)


def _artifact_summary(artifacts: dict[str, Any]) -> dict[str, Any]:
    summary = {}
    for key, value in artifacts.items():
        if isinstance(value, list):
            summary[key] = len(value)
        elif isinstance(value, dict):
            summary[key] = sorted(value.keys())[:8]
        else:
            summary[key] = bool(value)
    return summary


def _budget_message(budget: dict[str, Any]) -> str:
    line = (
        "**预算拆分**："
        f"已确认/可计活动费 {budget.get('activity_cost', 0)} 元，"
        f"餐饮预留 {budget.get('meal_budget', 0)} 元，"
        f"交通预留 {budget.get('transport_budget', 0)} 元，"
        f"已计总额 {budget.get('total', 0)} 元。"
    )
    if budget.get("budget_limit"):
        line += f"你的预算上限是 {budget['budget_limit']} 元，当前方案优先把钱留给餐饮、交通和可能的门票浮动。"
    unknown_items = budget.get("unknown_activity_cost_items") or []
    if unknown_items:
        line += " 未确认票价：" + "、".join(unknown_items) + "。"
    return line


def _budget_preview(budget: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"label": "活动费", "value": budget.get("activity_cost")},
        {"label": "餐饮", "value": budget.get("meal_budget")},
        {"label": "交通", "value": budget.get("transport_budget")},
        {"label": "合计", "value": budget.get("total")},
    ]


def _budget_summary(budget: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_cost": budget.get("activity_cost"),
        "meal_budget": budget.get("meal_budget"),
        "transport_budget": budget.get("transport_budget"),
        "total": budget.get("total"),
        "budget_limit": budget.get("budget_limit"),
        "budget_usage": budget.get("budget_usage"),
        "unknown_activity_cost_items": budget.get("unknown_activity_cost_items") or [],
    }


def _build_todo_message(plan: dict[str, Any]) -> str:
    lines = [f"**{plan.get('title', '待办拆解计划')}**"]
    if plan.get("summary"):
        lines.append(plan["summary"])
    items = plan.get("todo_items") or []
    if items:
        lines.append("**任务列表**")
        lines.extend(f"- {item.get('title')}：{item.get('success_criteria')}" for item in items)
    blocks = plan.get("time_blocks") or []
    if blocks:
        lines.append("**时间块**")
        lines.extend(f"- {block.get('time')} | {block.get('title')}" for block in blocks)
    confirm = plan.get("confirm_actions") or []
    if confirm:
        lines.append("**待确认动作**：" + "；".join(item.get("label", "需要确认") for item in confirm))
    return "\n\n".join(lines)


def _compact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if key == "raw":
                continue
            compact[key] = _compact_payload(item)
        return compact
    if isinstance(value, list):
        return [_compact_payload(item) for item in value[:8]]
    return value


def _confirm_actions_for(task_type: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if task_type == "todo":
        return [{"type": "calendar_or_reminder", "status": "requires_user_confirmation", "label": "是否写入日历/提醒", "items": [item.get("title") for item in items]}]
    if task_type == "meal":
        return [{"type": "reservation_or_message", "status": "requires_user_confirmation", "label": "是否订座、取号或发送聚餐消息", "items": [item.get("name") for item in items if item.get("name")]}]
    return [{"type": "external_side_effect", "status": "requires_user_confirmation", "label": "是否发送消息、支付、下单、预约或写入提醒", "items": [item.get("title") or item.get("name") for item in items]}]


def _constrain_mixed_budget(budget: dict[str, Any], budget_limit: Any) -> dict[str, Any]:
    if not isinstance(budget_limit, (int, float)) or not isinstance(budget.get("total"), (int, float)):
        return budget
    if budget["total"] <= budget_limit:
        return budget
    constrained = dict(budget)
    constrained["original_total"] = budget["total"]
    constrained["total"] = int(budget_limit)
    constrained["budget_usage"] = 1
    unknown = list(constrained.get("unknown_activity_cost_items") or [])
    if "部分跑腿/礼物消费需按现场选择控制" not in unknown:
        unknown.append("部分跑腿/礼物消费需按现场选择控制")
    constrained["unknown_activity_cost_items"] = unknown
    constrained["control_note"] = "混合任务按用户预算上限给出建议控制额，礼物、订座、配送、付款等实际支出需确认后执行。"
    return constrained


def _cost_text(item: dict[str, Any]) -> str:
    cost = int(item.get("cost", 0) or 0)
    if cost > 0:
        return f"约 {cost} 元，{item.get('cost_note', '实际以官方/现场为准')}"
    if item.get("cost_known"):
        return item.get("cost_note") or "免费/0 元，实际以官方/现场为准"
    return item.get("cost_note") or "未确认票价，暂不计入活动费"


def _dedupe_execution_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for index, step in enumerate(steps, start=1):
        tool = step.get("tool")
        if tool in seen:
            continue
        seen.add(tool)
        result.append({"id": f"step_{index}", **step})
    return result


def _dedupe_sub_tasks(sub_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in sub_tasks:
        task_type = item.get("type")
        if task_type in seen:
            continue
        seen.add(task_type)
        result.append(item)
    return result


def _dedupe_text_parts(parts: list[str]) -> list[str]:
    result = []
    seen = set()
    for part in parts:
        value = str(part or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _duration_from_time(time_text: str) -> str:
    match = re.match(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", time_text)
    if not match:
        return "约 1-2 小时"
    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
    minutes = end_hour * 60 + end_minute - start_hour * 60 - start_minute
    if minutes <= 0:
        return "约 1-2 小时"
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} 小时 {rest} 分钟"
    if hours:
        return f"{hours} 小时"
    return f"{rest} 分钟"


def _errand_duration(action: str) -> int:
    return {"取": 20, "买": 35, "寄": 30, "办": 50, "送": 35, "吃饭": 60}.get(action, 35)


def _errand_success_criteria(action: str, title: str) -> str:
    return {
        "取": f"{title}已取到并核对无误",
        "买": f"{title}已购买，金额和替代品已确认",
        "寄": f"{title}已寄出并保存单号",
        "办": f"{title}已完成或拿到下一步办理凭证",
        "送": f"{title}已送达并得到确认",
        "吃饭": "已完成用餐，下一站时间不被明显挤压",
    }.get(action, "事项完成并保存必要凭证")


def _evidence_preview(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": place.get("name"),
            "evidence": place.get("evidence") or [],
            "cost_known": place.get("cost_known"),
            "cost_note": place.get("cost_note"),
        }
        for place in places
        if place.get("evidence") or place.get("cost_known")
    ][:8]


def _execution_summary(research: dict[str, Any], weather: dict[str, Any]) -> str:
    sources = research.get("sources") or []
    provider = research.get("provider") or "搜索工具"
    source_text = f"搜索到 {len(sources)} 条可用网页资料" if sources else "暂时没有拿到稳定网页资料"
    if not sources and research.get("attempts"):
        failed = [
            f"{item.get('provider')}({item.get('status')})"
            for item in research.get("attempts", [])[:4]
            if item.get("provider")
        ]
        if failed:
            source_text += "，搜索尝试：" + "、".join(failed)
    weather_text = "并结合了天气工具" if weather else ""
    return f"我先用 {provider} 检索目的地攻略、路线、票价/预约和注意事项，{source_text}{weather_text}，再用地图地点结果串成可执行路线。"


def _extract_current_location(text: str) -> str | None:
    match = re.search(r"当前位置坐标[:：]\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    lon = float(match.group(1))
    lat = float(match.group(2))
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        return f"{lon},{lat}"
    return None


def _extract_famous_destination(text: str) -> dict[str, Any] | None:
    for keyword, destination in FAMOUS_DESTINATIONS.items():
        if keyword in text:
            return destination
    return None


def _extract_lifestyle_places(places: list[dict]) -> dict[str, list[dict]]:
    foods = []
    hotels = []
    food_tags = {"美食", "火锅", "川菜", "小吃", "茶馆", "咖啡", "餐厅"}
    hotel_tags = {"酒店", "住宿", "宾馆", "客栈", "民宿"}
    for place in places:
        tags = set(place.get("tags", []))
        text = " ".join(str(place.get(key) or "") for key in ["name", "address", "source_title"])
        item = {
            "name": place.get("name"),
            "address": place.get("address"),
            "area": place.get("area"),
            "location": place.get("location"),
            "map_url": place.get("map_url"),
            "tags": place.get("tags", []),
            "estimated_cost": place.get("estimated_cost", 0),
            "cost_known": place.get("cost_known", False),
            "cost_note": place.get("cost_note"),
            "provider": place.get("provider"),
        }
        if (tags.intersection(food_tags) or any(word in text for word in ["餐厅", "美食", "火锅", "小吃", "茶馆", "咖啡"])) and len(foods) < 5:
            foods.append(item)
        if (tags.intersection(hotel_tags) or any(word in text for word in ["酒店", "住宿", "宾馆", "客栈", "民宿", "汉庭"])) and len(hotels) < 5:
            hotels.append(item)
    return {"foods": foods, "hotels": hotels}


def _extract_pace(text: str) -> str | None:
    if any(word in text for word in ["不想太轻松", "不要太轻松", "别太轻松", "运动量多", "多走路"]):
        return "中等"
    if any(word in text for word in ["紧凑", "多安排", "多玩几个", "特种兵"]):
        return "紧凑"
    if any(word in text for word in ["轻松", "不想太累", "别太赶"]):
        return "轻松"
    return None


def _extract_ticket_price(text: str) -> int | None:
    patterns = [
        r"(?:门票|票价|成人票|价格|费用)[^0-9]{0,12}(\d{1,4})\s*元",
        r"(\d{1,4})\s*元\s*/?\s*人",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    if re.search(r"(免费开放|免费参观|门票免费|免门票)", text):
        return 0
    return None


def _extract_trip_days(text: str) -> int | None:
    match = re.search(r"(\d+)\s*[天日]", text)
    if match:
        return max(1, int(match.group(1)))
    mapping = {
        "两天": 2,
        "两日": 2,
        "二天": 2,
        "二日": 2,
        "三天": 3,
        "三日": 3,
        "四天": 4,
        "四日": 4,
    }
    return next((days for word, days in mapping.items() if word in text), None)


def _filter_places_by_city(places: list[dict], city: str) -> list[dict]:
    return [place for place in places if place.get("city") == city]


def _first_match(text: str, words: list[str]) -> str | None:
    return next((word for word in words if word in text), None)


def _guide_city(plan: dict[str, Any]) -> str:
    title = str(plan.get("title") or "目的地")
    for suffix in ["综合生活计划", "轻松一日计划", "一日计划", "餐饮计划", "计划"]:
        if title.endswith(suffix):
            title = title[: -len(suffix)]
    return title or "目的地"


def _guide_place_category(item: dict[str, Any]) -> str:
    name = str(item.get("place") or item.get("name") or "")
    tags = set(item.get("tags") or [])
    if any(word in name for word in ["祠", "故居", "三苏"]):
        return "culture"
    if "水街" in name or "老街" in name:
        return "water_street"
    if "泡菜" in name:
        return "pickle"
    if "古镇" in name and not any(word in name for word in ["牌坊", "游客中心", "停车场"]):
        return "ancient_town"
    if "风景区" in name or "爬山" in tags or "运动" in tags:
        return "mountain"
    if "楼" in name or "塔" in name:
        return "view"
    if "博物馆" in tags or "展览" in tags:
        return "museum"
    return "other"


def _guide_place_key(name: str) -> str:
    return re.split(r"[-·（(]", name, maxsplit=1)[0].strip() or name


def _guide_place_score(item: dict[str, Any]) -> int:
    name = str(item.get("place") or item.get("name") or "")
    tags = set(item.get("tags") or [])
    score = 10 if item.get("time") else 0
    if any(word in name for word in ["祠", "故居", "三苏"]):
        score += 24
    if any(word in name for word in ["水街", "老街", "古镇", "街区"]):
        score += 18
    if "泡菜" in name:
        score += 18
    if "风景区" in name or ("爬山" in tags or "运动" in tags):
        score += 14
    if "博物馆" in tags or "展览" in tags:
        score += 8
    if any(word in name for word in ["湿地", "公园", "广场"]):
        score -= 4
    if "-" in name:
        score -= 22
    return score


def _guide_practical_tips(city: str, plan: dict[str, Any]) -> list[str]:
    tips = ["热门景点和餐饮建议出发前确认开放、排队和订座情况。"]
    names = " ".join(str(item.get("place", "")) for item in plan.get("itinerary") or [])
    if "瓦屋山" in names or any("爬山" in (item.get("tags") or []) for item in plan.get("itinerary") or []):
        tips.append("瓦屋山、山地或古镇类路线更吃天气和体力，最好单独预留半天到一天。")
    weather = plan.get("weather") or {}
    if weather.get("outdoor_risk") in {"medium", "high"}:
        tips.append("天气对室外体验有影响，三苏祠、水街、古镇这类点位建议带伞并穿防滑鞋。")
    if city == "眉山":
        tips.append("从成都出发可优先看高铁/城际组合，市区点位集中在东坡区时更适合一日 City Walk。")
    return tips


def _has_errand_intent(text: str) -> bool:
    return any(word in text for word in ["取快递", "拿快递", "寄快递", "寄件", "办事", "办理", "跑腿", "顺路", "送到", "送去", "买药", "买菜", "买礼物"])


def _has_meal_intent(text: str) -> bool:
    return any(word in text for word in MEAL_INTENT_WORDS)


def _has_todo_intent(text: str) -> bool:
    return any(word in text.lower() for word in ["todo", "to-do"]) or any(word in text for word in ["待办", "拆解", "拆成", "任务列表", "完成标准", "里程碑", "时间块"])


def _intent_contract_issues(state: AgentState) -> list[str]:
    plan = state.final_plan or {}
    contract = state.intent_contract or {}
    issues = []
    required = set(contract.get("required_outputs") or [])
    if "errand_items" in required and not plan.get("errand_items"):
        issues.append("intent_missing_subtask: 缺少跑腿事项安排")
    if "meal_candidates" in required and not plan.get("meal_candidates"):
        issues.append("intent_missing_subtask: 缺少餐饮候选")
    if "todo_items" in required and not plan.get("todo_items"):
        issues.append("intent_missing_subtask: 缺少待办拆解")
    if "itinerary" in required and not plan.get("itinerary"):
        issues.append("intent_output_mismatch: 缺少时间线/路线安排")
    budget_limit = state.constraints.get("budget")
    total = (plan.get("budget") or {}).get("total")
    if isinstance(budget_limit, (int, float)) and isinstance(total, (int, float)) and total > budget_limit:
        issues.append("intent_hard_constraint_conflict: 预算超过用户限制")
    return issues


def _intent_has(state: AgentState, task_type: str) -> bool:
    return any(item.get("type") == task_type for item in (state.intent_contract or {}).get("sub_tasks", []))


def _linked_named_item(item: dict[str, Any]) -> str:
    name = item.get("name") or "地点"
    url = item.get("map_url")
    return f"[{name}]({url})" if url else name


def _linked_place(item: dict[str, Any]) -> str:
    name = item.get("place", "地点")
    url = item.get("map_url")
    return f"[{name}]({url})" if url else name


def _linked_source(item: dict[str, Any]) -> str:
    title = item.get("title", "来源")
    url = item.get("url")
    return f"[{title}]({url})" if url else title


def _llm_enabled() -> bool:
    if settings.llm_mode == "deepseek":
        return bool(settings.deepseek_api_key)
    if settings.llm_mode == "openai":
        return bool(settings.openai_api_key)
    return False


def _llm_model_name() -> str:
    if settings.llm_mode == "deepseek":
        return settings.deepseek_model
    if settings.llm_mode == "openai":
        return settings.openai_model
    return "mock"


def _log(state: AgentState, node: str, summary: str, details: Any) -> None:
    state.execution_log.append({"node": node, "summary": summary, "details": details})


def _looks_like_city_overview_title(title: str, city: str) -> bool:
    if not title or not city:
        return False
    compact = re.sub(r"[\s_\-·|｜—–,，。:：()（）\[\]【】]", "", title)
    city_compact = city.replace("市", "")
    city_forms = {city, f"{city_compact}市", city_compact}
    if compact in city_forms:
        return True
    overview_suffixes = ["百度百科", "维基百科", "搜狗百科", "360百科", "城市百科", "概况", "介绍", "市情", "区情", "人民政府"]
    return any(compact.startswith(form) and any(word in compact for word in overview_suffixes) for form in city_forms)


def _looks_like_search_place_name(name: str) -> bool:
    if len(name) < 2 or len(name) > 14:
        return False
    blocked = ["中华人民共和国", "云南省", "四川省", "旅游景点", "观光景点", "热门景点", "必去景点", "推荐景点"]
    return not any(word in name for word in blocked)


def _mixed_item_reason(place: dict[str, Any]) -> str:
    tags = set(place.get("tags") or [])
    if "缇庨" in tags or "美食" in tags:
        return "餐饮节点，和其他事项按顺路顺序合并"
    if "璺戣吙" in tags:
        return "跑腿事项，外部动作只记录为待确认"
    return "出行/游玩节点，按地点候选和路线估算纳入"


def _places_preview(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview = []
    for place in places[:8]:
        preview.append({
            "name": place.get("name"),
            "area": place.get("area"),
            "address": place.get("address"),
            "tags": place.get("tags") or [],
            "map_url": place.get("map_url"),
            "cost_known": place.get("cost_known"),
            "cost_note": place.get("cost_note"),
            "provider": place.get("provider"),
            "evidence": place.get("evidence") or [],
        })
    return preview


def _recommendation_basis(state: AgentState, selected: list[dict], candidates: list[dict]) -> dict[str, Any]:
    search = state.artifacts.get("search_results") or getattr(state, "_search_results", {})
    lifestyle = state.artifacts.get("lifestyle_places") or getattr(state, "_lifestyle_places", {"foods": [], "hotels": []})
    selected_names = [place.get("name") for place in selected if place.get("name")]
    candidate_names = [place.get("name") for place in candidates[:8] if place.get("name")]
    return {
        "answer": "主推荐来自地图候选评分，并叠加网页搜索命中、当地热门度、用户偏好、预算、天气和路线顺序；不是只按网页搜索随机挑选。",
        "selected_places": selected_names,
        "top_scored_candidates": candidate_names,
        "web_sources_count": len((state.artifacts.get("travel_research") or {}).get("sources") or []),
        "web_query": search.get("query"),
        "web_results_count": len(search.get("results") or []),
        "food_candidates_count": len(lifestyle.get("foods") or []),
        "hotel_candidates_count": len(lifestyle.get("hotels") or []),
    }


def _recommendation_basis_message(basis: dict[str, Any]) -> str:
    if not basis:
        return ""
    selected = "、".join(str(item) for item in (basis.get("selected_places") or [])[:4])
    counts = (
        f"网页结果 {basis.get('web_results_count', 0)} 条、参考来源 {basis.get('web_sources_count', 0)} 条、"
        f"餐饮候选 {basis.get('food_candidates_count', 0)} 个、住宿候选 {basis.get('hotel_candidates_count', 0)} 个"
    )
    query = basis.get("web_query")
    query_text = f"；搜索词：{query}" if query else ""
    selected_text = f"；主线：{selected}" if selected else ""
    return f"**推荐依据**：{basis.get('answer', '已综合候选评分和外部来源排序')}（{counts}{query_text}{selected_text}）。"


def _research_plan_note(research: dict[str, Any]) -> str | None:
    if research.get("answer"):
        return f"**搜索结论**：{research['answer']}"
    sources = research.get("sources") or []
    if not sources:
        note = research.get("note")
        return f"**搜索状态**：{note}。这次主要依赖天气和地图地点数据，票价/营业时间会标为待确认。" if note else None
    activity_sources = research.get("activity_sources") or []
    if activity_sources:
        activity_text = "；".join(f"{item.get('title', '活动资料')}：{item.get('content', '')[:60]}" for item in activity_sources[:2])
        return "**搜索结论**：优先参考了与出行日期相关的近期活动/开放信息；" + activity_text
    highlights = []
    for source in sources[:3]:
        content = source.get("content") or ""
        title = source.get("title") or "网页资料"
        highlights.append(f"{title}：{content[:80]}")
    return "**搜索结论**：我把网页里提到的路线、景点和注意事项作为筛选依据；" + "；".join(highlights)


def _route_preview(route: dict[str, Any]) -> list[dict[str, Any]]:
    places = route.get("ordered_places") or []
    legs = route.get("legs") or []
    return [
        {
            "order": index + 1,
            "place": place.get("name"),
            "area": place.get("area"),
            "travel_from_previous": legs[index].get("minutes") if index < len(legs) else None,
        }
        for index, place in enumerate(places[:8])
    ]


def _route_scope(origin: dict[str, Any] | None, destination: dict[str, Any] | None, activity_area: dict[str, Any] | None) -> str:
    if destination and origin and (origin.get("city") != destination.get("city") or origin.get("location")):
        return "cross_city_trip"
    if destination and destination.get("type") in {"poi", "scenic_area"}:
        return "poi_trip"
    return "city_trip" if destination or activity_area else "unknown"


def _route_summary(route: dict[str, Any]) -> dict[str, Any]:
    access_route = route.get("access_route") or {}
    return {
        "provider": route.get("provider"),
        "places_count": len(route.get("ordered_places") or []),
        "legs_count": len(route.get("legs") or []),
        "travel_minutes": route.get("travel_minutes"),
        "access_route_provider": access_route.get("provider"),
        "access_route_summary": access_route.get("summary"),
    }


def _search_preview(search_data: dict[str, Any]) -> list[dict[str, Any]]:
    preview = []
    for item in (search_data.get("results") or [])[:5]:
        preview.append({
            "title": item.get("name") or item.get("title") or item.get("url") or "搜索结果",
            "url": item.get("url"),
            "content": (item.get("summary") or item.get("snippet") or item.get("content") or "")[:140],
            "site": item.get("siteName"),
            "date": item.get("datePublished"),
        })
    return preview


def _search_result_key(item: dict[str, Any]) -> str:
    return str(item.get("url") or item.get("name") or item.get("title") or "").strip()


def _search_summary(search_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": search_data.get("query"),
        "provider": search_data.get("provider"),
        "results_count": len(search_data.get("results") or []),
        "answer": search_data.get("answer"),
        "note": search_data.get("note"),
        "attempts": search_data.get("attempts") or [],
    }


def _selection_quality(item: dict[str, Any]) -> int:
    return (
        int(item.get("goal_match_score", 0) or 0) * 2
        + int(item.get("web_match_score", 0) or 0) * 2
        + int(item.get("popularity_score", 0) or 0)
        + int(item.get("event_score", 0) or 0)
        + len(item.get("evidence") or []) * 6
    )


def _summary(itinerary: list[dict], budget: dict, access_route: dict | None = None) -> str:
    names = " -> ".join(item["place"] for item in itinerary)
    access = ""
    if access_route and access_route.get("needed"):
        access = f"到达路线：{access_route.get('summary')}。"
    return (
        f"{access}目的地内路线：{names}。"
        f"活动费 {budget.get('activity_cost', 0)} 元，"
        f"餐饮 {budget.get('meal_budget', 0)} 元，"
        f"交通 {budget.get('transport_budget', 0)} 元，"
        f"已计总额 {budget.get('total', 0)} 元。"
    )


def _time_label(total_minutes: int) -> str:
    hour = total_minutes // 60
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"


def _weather_advice(weather: dict[str, Any]) -> str:
    risk = weather.get("outdoor_risk")
    condition = weather.get("condition", "")
    if risk == "medium" or any(word in condition for word in ["雨", "雪", "雾"]):
        return "室外体验可能受影响，路线里要保留室内/可撤退选项。"
    return "整体适合户外走动，但仍建议带水、防晒或薄外套。"


def _weather_summary(weather: dict[str, Any]) -> dict[str, Any]:
    return {
        "city": weather.get("city"),
        "date": weather.get("date"),
        "condition": weather.get("condition"),
        "temperature": weather.get("temperature"),
        "precipitation_probability": weather.get("precipitation_probability"),
        "outdoor_risk": weather.get("outdoor_risk"),
        "provider": weather.get("provider"),
        "provider_warning": weather.get("provider_warning"),
    }


def _with_quality_warning(message: str, warnings: list[str]) -> str:
    warning_lines = "\n".join(f"- {warning}" for warning in warnings[:5])
    prefix = "当前方案未完全满足你的要求，需要先确认这些问题：\n" + warning_lines
    if not message:
        return prefix
    return prefix + "\n\n下面是目前仍可参考的行程：\n\n" + message
