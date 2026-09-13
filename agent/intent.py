"""意图与约束识别：判断任务类型、抽取约束、解析目标与地点角色。

从 agent/nodes.py 整组搬迁，闭包自洽，不依赖其他 Agent 节点。
"""

from __future__ import annotations

import re
from typing import Any

from agent.constants import (
    AVOID_WORDS,
    FAMOUS_DESTINATIONS,
    KNOWN_CITIES,
    PREFERENCE_WORDS,
)
from agent.intent_signals import (
    _activity_intent,
    _is_negated,
    _reflection_issues,
)
from agent.place_utils import (
    _city_in_text,
    _clean_place_text,
    _is_broad_region_hint,
    _is_origin_phrase,
    _mentions_current_area,
)
from agent.prompts import CONSTRAINT_EXTRACTOR_PROMPT
from agent.text_utils import (
    _errand_duration,
    _errand_success_criteria,
    _extract_current_location,
    _extract_famous_destination,
    _first_match,
    _llm_enabled,
    _looks_like_search_place_name,
    _route_scope,
    _time_label,
)
from services.llm_client import llm_client


def _has_hard_reflection_issue(reflection: dict[str, Any]) -> bool:
    issues = _reflection_issues(reflection)
    hard_words = ["超过用户限制", "没有生成", "目的地与用户目标不符", "缺少从出发地到目的地", "没有安排该目的地"]
    return any(any(word in issue for word in hard_words) for issue in issues)


def _extract_with_llm(text: str) -> dict[str, Any]:
    if not _llm_enabled():
        return {}
    try:
        result = llm_client.json_complete(CONSTRAINT_EXTRACTOR_PROMPT, text)
    except Exception:
        return {}
    if result.get("mode") == "mock":
        return {}
    result["_llm_used"] = True
    return result


def _extract_place_names_from_search(search: dict[str, Any]) -> list[str]:
    names: list[str] = []
    pattern = re.compile(r"[\u4e00-\u9fff]{2,12}(?:风景区|景区|博物馆|美术馆|公园|古镇|老街|花市|湿地|民族村|村|寺|祠|楼|塔|坊|湖|池|山|街|巷|园|林|城)")
    for result in search.get("results") or []:
        text = " ".join(str(result.get(key, "")) for key in ["name", "title", "summary", "snippet", "content"])
        for match in pattern.findall(text):
            name = match.strip(" ，。、：:；;（）()【】[]")
            if _looks_like_search_place_name(name):
                names.append(name)
    return list(dict.fromkeys(names))


def _extract_city_hint(text: str) -> str | None:
    known = _first_match(text, KNOWN_CITIES)
    if known:
        return known
    patterns = [
        r"(?:在|去|到|前往)([\u4e00-\u9fa5]{2,8})(?:轻松|玩|旅游|旅行|一日游|半日|看展|吃饭|办事|跑腿|散步|爬山)",
        r"([\u4e00-\u9fa5]{2,8})(?:轻松)?(?:玩|旅游|旅行|一日游|半日游|看展|吃饭|办事|跑腿|散步|爬山)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        city = _clean_city_hint(match.group(1))
        if city and city not in PREFERENCE_WORDS and city not in {"附近", "这里", "周边", "海边"}:
            return city
    return None


def _clean_city_hint(value: str) -> str:
    value = _clean_place_text(value)
    value = re.sub(r"^(今天|明天|后天|本周六|本周日|下周六|下周日|这周六|这周日|周六|周日|周末)", "", value)
    value = re.sub(r"(轻松|紧凑|中等|附近|周边)$", "", value)
    return value.strip()


def _extract_avoid(text: str) -> list[str]:
    avoid = [word for word in AVOID_WORDS if word in text]
    for word in PREFERENCE_WORDS:
        if word in text and _is_negated(text, word):
            avoid.append(word)
    return list(dict.fromkeys(avoid))


def _extract_errand_items(text: str) -> list[dict[str, Any]]:
    patterns = [
        ("取", r"(取|拿)(快递|外卖|文件|药|票|东西)"),
        ("买", r"买([^，、。,.；;]+)"),
        ("寄", r"(寄|邮)(快递|文件|包裹|东西)"),
        ("办", r"(办|办理)([^，、。,.；;]+)"),
        ("送", r"送([^，、。,.；;]+)"),
        ("吃饭", r"(吃饭|午饭|晚饭|早餐|早饭)"),
    ]
    items: list[dict[str, Any]] = []
    for action, pattern in patterns:
        for match in re.finditer(pattern, text):
            raw = match.group(0)
            label = raw if len(raw) <= 16 else raw[:16]
            items.append({
                "action": action,
                "title": label,
                "location_status": "待确认",
                "duration_minutes": _errand_duration(action),
                "success_criteria": _errand_success_criteria(action, label),
            })
    if not items:
        items.append({
            "action": "办",
            "title": "整理并执行跑腿事项",
            "location_status": "待确认",
            "duration_minutes": 45,
            "success_criteria": "事项完成，凭证/结果已保存",
        })
    deduped = []
    seen = set()
    for item in items:
        key = item["title"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:6]


def _parse_todo_goal(text: str) -> dict[str, Any]:
    goal = re.sub(r"(帮我|请|把|拆解|待办|任务列表|todo|to-do)", "", text, flags=re.IGNORECASE).strip(" ，。")
    goal = goal or "完成这个目标"
    parts = [part.strip() for part in re.split(r"[，、。；;,.]\s*", goal) if part.strip()]
    if len(parts) <= 1:
        tasks = [
            "明确目标和截止时间",
            "列出必需资料/资源",
            "完成第一版产出",
            "检查遗漏并提交/归档",
        ]
    else:
        tasks = parts[:6]
    todo_items = [
        {
            "title": task,
            "status": "todo",
            "duration_minutes": 45 if index else 30,
            "success_criteria": f"{task}有明确产出或可验证结果",
        }
        for index, task in enumerate(tasks)
    ]
    return {
        "goal": goal,
        "tasks": todo_items,
        "time_blocks": _todo_time_blocks(todo_items),
        "acceptance_criteria": [item["success_criteria"] for item in todo_items],
    }


def _todo_time_blocks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = 9 * 60
    blocks = []
    for task in tasks:
        start = _time_label(current)
        current += int(task.get("duration_minutes") or 45)
        blocks.append({"time": f"{start}-{_time_label(current)}", "title": task["title"]})
        current += 10
    return blocks


def _looks_like_travel_request(text: str) -> bool:
    return bool(_extract_famous_destination(text)) or any(
        word in text
        for word in ["玩", "好玩", "建议", "一日游", "打卡", "景点", "旅游", "路线", "爬山", "登山", "徒步", "看展", "展览", "散步", "前往"]
    )


def _extract_place_roles(text: str, llm_constraints: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    origin_raw = _extract_origin_text(text)
    destination_raw = _extract_destination_text(text)
    origin_location = _extract_current_location(text) or (context.get("origin_location") if _mentions_current_area(text) else None)
    default_city = context.get("default_city")
    origin_city = context.get("origin_city") or (origin_raw if origin_raw in KNOWN_CITIES else None)
    explicit_city = _first_match(text, KNOWN_CITIES)

    destination = _resolve_place_role(destination_raw, "destination") if destination_raw else None
    if destination and _is_broad_region_hint(destination_raw or "") and explicit_city:
        destination = _resolve_place_role(explicit_city, "destination")
    if not destination and explicit_city and not _mentions_current_area(text):
        destination = _resolve_place_role(explicit_city, "destination")
    if not destination and llm_constraints.get("city") and not _mentions_current_area(text):
        destination = _resolve_place_role(str(llm_constraints["city"]), "destination")

    origin = None
    if origin_location:
        origin = {
            "raw": origin_raw or "当前位置",
            "name": origin_raw or origin_city or default_city or "当前位置",
            "city": origin_city or default_city,
            "location": origin_location,
            "source": "browser_location" if context.get("origin_location") else "user_text",
        }
    elif origin_raw:
        origin = _resolve_place_role(origin_raw, "origin")

    activity_area = None
    if not destination and _mentions_current_area(text):
        activity_area = origin or ({"raw": default_city, "name": default_city, "city": default_city, "source": "default_city"} if default_city else None)

    route_scope = _route_scope(origin, destination, activity_area)
    return {
        "origin": origin,
        "destination": destination,
        "activity_area": activity_area,
        "via_points": [],
        "activity_intent": _activity_intent(text),
        "route_scope": route_scope,
    }


def _extract_origin_text(text: str) -> str | None:
    if any(word in text for word in ["当前位置", "现在这个地方", "我这里", "从这里", "从我这"]):
        return None
    patterns = [
        r"从([\u4e00-\u9fa5A-Za-z0-9·]{2,16})(?:出发|去|到|前往)",
        r"我在([\u4e00-\u9fa5A-Za-z0-9·]{2,16})(?:，|,|想|要|周|明|今|$)",
        r"出发地[:：]\s*([\u4e00-\u9fa5A-Za-z0-9·]{2,16})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean_place_text(match.group(1))
    return None


def _extract_destination_text(text: str) -> str | None:
    for keyword in FAMOUS_DESTINATIONS:
        if keyword in text:
            return keyword
    explicit_city = _first_match(text, KNOWN_CITIES)
    if explicit_city and any(word in text for word in ["旅游", "景点", "推荐", "攻略", "查找", "好玩"]):
        return explicit_city
    patterns = [
        r"(?:想去|要去|准备去|计划去|去|到|前往)([\u4e00-\u9fa5A-Za-z0-9·]{2,20})",
        r"(?:爬|游|逛)([\u4e00-\u9fa5A-Za-z0-9·]{2,16})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = _clean_place_text(match.group(1))
            if value in PREFERENCE_WORDS and _first_match(text, KNOWN_CITIES):
                continue
            if value and not _is_origin_phrase(value):
                return value
    return None


def _resolve_place_role(raw: str, role: str) -> dict[str, Any]:
    destination = _extract_famous_destination(raw)
    if destination:
        anchor = (destination.get("places") or [{}])[0]
        return {
            "raw": raw,
            "name": destination["place"],
            "city": destination["city"],
            "type": "scenic_area",
            "location": anchor.get("location"),
            "confidence": 0.95,
            "source": "destination_registry",
        }
    city = _city_in_text(raw)
    name = raw
    if city and raw != city and raw.startswith(city):
        name = raw[len(city):] or raw
    place_type = (
        "city"
        if raw == city
        else "district"
        if name.endswith(("区", "县"))
        else "scenic_area"
        if any(word in raw for word in ["山", "湖", "岛", "湾", "景区", "风景区"])
        else "poi"
    )
    return {
        "raw": raw,
        "name": name,
        "city": city or (raw if raw in KNOWN_CITIES else None),
        "type": place_type,
        "location": None,
        "confidence": 0.75 if city or place_type != "poi" else 0.55,
        "source": "rule",
    }
