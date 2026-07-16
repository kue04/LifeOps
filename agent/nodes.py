from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlparse

from agent.prompts import CONSTRAINT_EXTRACTOR_PROMPT, PLAN_GENERATOR_PROMPT, PLANNER_PROMPT, REFLECTION_PROMPT
from agent.state import AgentState
from config import settings
from services.date_resolver import resolve_date_text
from services.llm_client import llm_client
from services.risk_checker import check_risks
from services.scorer import score_candidates
from services.geocoder import geocode_city, geocode_place
from tools.budget import estimate_budget
from tools.memory import load_user_profile
from tools.places import search_places
from tools.route import estimate_access_route, estimate_route
from tools.web_search import search_web
from tools.weather import get_weather


PREFERENCE_WORDS = ["咖啡", "展览", "夜景", "美食", "火锅", "川菜", "小吃", "茶馆", "书店", "公园", "博物馆", "散步", "爬山", "徒步", "登山", "海边"]
AVOID_WORDS = ["太累", "太赶", "排队", "室外", "太贵"]
TASK_TYPES = {"travel", "errand", "meal", "todo", "replan", "unknown"}
KNOWN_CITIES = ["杭州", "上海", "北京", "南京", "苏州", "福州", "厦门", "泉州", "广州", "深圳", "成都", "长沙", "宁波", "黄山"]
KNOWN_CITIES.extend(["莆田", "三明", "西安", "渭南", "华阴", "武汉", "天津", "重庆", "青岛", "郑州", "合肥", "昆明", "眉山", "洛阳", "开封", "扬州", "无锡", "济南", "大连"])
MEAL_INTENT_WORDS = ["吃饭", "午饭", "晚饭", "早餐", "早饭", "餐厅", "外食", "聚餐", "吃什么", "找家店", "火锅", "川菜", "小吃", "茶馆", "烧烤", "夜宵", "甜品", "美食"]
REFERENCE_TICKET_PRICES = {
    "成都": {
        "武侯祠": 50,
        "杜甫草堂": 50,
        "都江堰": 80,
        "青城山": 80,
    },
}
PROVINCE_HINTS = {
    "云南", "浙江", "江苏", "福建", "广东", "四川", "湖南", "湖北", "河南", "河北",
    "山东", "山西", "陕西", "安徽", "江西", "贵州", "甘肃", "青海", "辽宁", "吉林",
    "黑龙江", "海南", "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
}
NEGATION_WORDS = ["不想", "不要", "不喝", "不去", "别", "讨厌", "不喜欢"]
FAMOUS_DESTINATIONS = {
    "华山": {
        "city": "渭南",
        "place": "华山风景名胜区",
        "tags": ["爬山", "徒步", "景点", "室外"],
        "places": [
            {
                "name": "华山游客中心",
                "area": "华山风景名胜区",
                "address": "渭南市华阴市华山游客中心",
                "play_points": ["进山换乘和索道票务入口，先在这里确认开放和末班时间"],
                "duration_minutes": 45,
                "intensity": "低",
                "location": "110.085,34.532",
            },
            {
                "name": "北峰索道",
                "area": "华山风景名胜区",
                "address": "渭南市华阴市华山风景名胜区北峰索道",
                "play_points": ["适合一日爬山路线快速上山，降低体力消耗"],
                "duration_minutes": 80,
                "intensity": "中",
                "location": "110.083,34.505",
            },
            {
                "name": "苍龙岭",
                "area": "华山风景名胜区",
                "address": "渭南市华阴市华山风景名胜区苍龙岭",
                "play_points": ["华山经典险峻山脊路段，雨雪大风时要保守取舍"],
                "duration_minutes": 90,
                "intensity": "高",
                "location": "110.087,34.497",
            },
            {
                "name": "西峰索道",
                "area": "华山风景名胜区",
                "address": "渭南市华阴市华山风景名胜区西峰索道",
                "play_points": ["适合下山或西上北下路线，减少回头路"],
                "duration_minutes": 80,
                "intensity": "中",
                "location": "110.071,34.488",
            },
        ],
    },
    "黄山": {
        "city": "黄山",
        "place": "黄山风景区",
        "tags": ["爬山", "徒步", "景点", "室外"],
        "places": [
            {
                "name": "黄山风景区云谷寺索道",
                "area": "黄山风景区",
                "address": "黄山市黄山区汤口镇黄山风景区云谷寺",
                "play_points": ["后山上山入口，适合一日游节省体力", "雨天优先坐索道，减少湿滑路段"],
                "duration_minutes": 90,
                "intensity": "中",
                "location": "118.198,30.144",
            },
            {
                "name": "始信峰",
                "area": "黄山风景区",
                "address": "黄山市黄山区黄山风景区北海景区",
                "play_points": ["看奇松和山景，是黄山精华观景点之一", "雨后有机会遇到云雾景观"],
                "duration_minutes": 90,
                "intensity": "中",
                "location": "118.179,30.152",
            },
            {
                "name": "光明顶",
                "area": "黄山风景区",
                "address": "黄山市黄山区黄山风景区光明顶",
                "play_points": ["黄山核心高点，适合看云海和开阔山景", "天气差时控制停留，注意防风保暖"],
                "duration_minutes": 100,
                "intensity": "高",
                "location": "118.164,30.133",
            },
            {
                "name": "迎客松",
                "area": "黄山风景区",
                "address": "黄山市黄山区黄山风景区玉屏楼",
                "play_points": ["黄山标志性打卡点", "可衔接玉屏索道下山"],
                "duration_minutes": 80,
                "intensity": "中",
                "location": "118.156,30.124",
            },
        ],
    },
}
RECENT_ACTIVITY_WORDS = ["近期", "活动", "展览", "演出", "市集", "音乐节", "节庆", "预约", "开放", "营业"]
CITY_GUIDE_INTROS = {
    "眉山": "眉山是苏东坡的故乡，适合把东坡文化、城市夜景和本地烟火气串成一趟轻松小旅行。",
}
LOCAL_FOOD_TIPS_BY_CITY = {
    "眉山": [
        "东坡肘子：眉山代表性风味，适合和东坡肉、东坡泡菜一起尝。",
        "东坡泡菜：酸辣爽脆，适合解腻，也适合作为伴手礼。",
        "彭山甜皮鸭：咸甜交织，适合想换换口味时安排。",
        "丹棱冻粑：软糯小吃，适合做轻量补给或伴手礼。",
    ],
}
CITY_GUIDE_POI_QUERY_TERMS = {
    "眉山": ["三苏祠", "东坡印象水街", "瓦屋山风景区", "柳江古镇", "中国泡菜城", "中国泡菜博物馆"],
}
CITY_SEARCH_CONTEXT_TERMS = {
    "眉山": ["四川", "眉山市", "东坡", "三苏祠"],
}
NATIONAL_CHAIN_MEAL_WORDS = ["海底捞", "呷哺", "凑凑", "巴奴"]
POPULAR_PLACE_KEYWORDS_BY_CITY = {
    "杭州": ["西湖", "灵隐", "雷峰塔", "断桥", "苏堤", "良渚", "京杭大运河", "中国丝绸博物馆"],
    "上海": ["外滩", "陆家嘴", "豫园", "武康路", "上海博物馆", "迪士尼"],
    "北京": ["故宫", "天安门", "颐和园", "圆明园", "长城", "南锣鼓巷"],
    "南京": ["中山陵", "夫子庙", "秦淮河", "玄武湖", "南京博物院"],
    "苏州": ["拙政园", "平江路", "虎丘", "苏州博物馆", "金鸡湖"],
    "福州": ["鼓山", "三坊七巷", "烟台山", "福道", "西湖公园", "闽江"],
    "厦门": ["鼓浪屿", "环岛路", "厦门大学", "植物园", "中山路"],
    "广州": ["广州塔", "沙面", "陈家祠", "白云山", "珠江"],
    "深圳": ["深圳湾", "莲花山", "华侨城", "大梅沙", "南头古城"],
    "成都": ["宽窄巷子", "武侯祠", "杜甫草堂", "青城山", "都江堰"],
    "长沙": ["橘子洲", "岳麓山", "湖南博物院", "五一广场"],
    "宁波": ["天一阁", "老外滩", "东钱湖", "月湖", "东钱湖小普陀", "象山松兰山"],
    "黄山": ["黄山风景区", "云谷寺", "始信峰", "光明顶", "迎客松", "西海大峡谷"],
    "莆田": ["绶溪公园", "木兰陂公园", "凤凰山公园", "湄洲岛", "南山广化寺"],
    "三明": ["麒麟山公园", "三明市博物馆", "沙县小吃文化城", "泰宁大金湖", "玉华洞", "瑞云山"],
    "武汉": ["黄鹤楼", "东湖听涛景区", "湖北省博物馆", "江汉路步行街", "昙华林", "汉口江滩"],
    "西安": ["西安城墙", "陕西历史博物馆", "大雁塔", "大唐不夜城", "钟鼓楼", "华清宫"],
    "重庆": ["解放碑", "洪崖洞", "山城步道", "鹅岭二厂", "磁器口", "长江索道"],
    "天津": ["五大道", "意式风情区", "天津之眼", "古文化街", "海河", "滨江道"],
    "青岛": ["栈桥", "八大关", "小麦岛", "青岛啤酒博物馆", "五四广场", "奥帆中心"],
    "郑州": ["河南博物院", "二七纪念塔", "郑州博物馆", "只有河南戏剧幻城", "郑州黄河文化公园"],
    "合肥": ["安徽博物院", "逍遥津公园", "包公园", "合柴1972", "天鹅湖", "淮河路步行街"],
    "昆明": ["滇池", "翠湖公园", "云南省博物馆", "斗南花市", "金马碧鸡坊", "西山风景区"],
    "洛阳": ["龙门石窟", "洛阳博物馆", "白马寺", "隋唐洛阳城应天门遗址", "丽景门", "洛邑古城"],
    "开封": ["清明上河园", "开封府", "大相国寺", "龙亭公园", "鼓楼夜市", "中国翰园碑林"],
    "扬州": ["瘦西湖", "个园", "何园", "东关街", "大明寺", "中国大运河博物馆"],
    "无锡": ["鼋头渚", "惠山古镇", "南长街", "灵山胜境", "拈花湾", "无锡博物院"],
    "济南": ["趵突泉", "大明湖", "千佛山", "山东博物馆", "曲水亭街", "宽厚里"],
    "大连": ["星海广场", "棒棰岛", "老虎滩海洋公园", "东港音乐喷泉广场", "俄罗斯风情街", "滨海路"],
}
PREFERENCE_PLACE_KEYWORDS_BY_CITY = {
    "武汉": {
        "咖啡": ("昙华林", ["咖啡", "散步", "室外"], "街区内有咖啡店和小店，适合作为中途休息段"),
        "美食": ("户部巷", ["美食", "散步", "室外"], "小吃和正餐选择集中，适合作为餐饮补给段"),
        "书店": ("卓尔书店", ["书店", "室内"], "适合作为室内慢逛和休息点"),
    },
    "洛阳": {
        "咖啡": ("洛邑古城", ["咖啡", "夜景", "散步", "室外"], "古城街区内有休息点，适合傍晚慢逛和中途补给"),
        "美食": ("老城十字街", ["美食", "夜景", "散步", "室外"], "小吃和夜间氛围集中，适合作为晚餐或夜游段"),
        "书店": ("洛阳城市书房", ["书店", "室内"], "适合作为室内慢逛和休息点"),
    },
}


def extract_constraints(state: AgentState) -> AgentState:
    text = state.user_input
    llm_constraints = _extract_with_llm(text)
    if llm_constraints.pop("_llm_used", False):
        state.llm_usage.append({"node": "constraint_extractor", "status": "success", "model": _llm_model_name()})

    budget_match = re.search(r"预算\s*(\d+)|(\d+)\s*元|控制在\s*(\d+)", text)
    budget = next((int(item) for item in budget_match.groups() if item), None) if budget_match else None
    place_roles = _extract_place_roles(text, llm_constraints, state.constraints)
    destination_role = place_roles.get("destination")
    origin_role = place_roles.get("origin")
    activity_area = place_roles.get("activity_area") or {}
    text_city = _extract_city_hint(text)
    city = (
        (destination_role or {}).get("city")
        or activity_area.get("city")
        or text_city
        or (origin_role or {}).get("city")
        or state.constraints.get("default_city")
    )
    date = _first_match(text, ["今天", "明天", "后天", "本周六", "本周日", "下周六", "下周日", "周六", "周日", "周末"])
    pace = _extract_pace(text)
    avoid = _extract_avoid(text)
    current_location = _extract_current_location(text) or (
        state.constraints.get("origin_location") if _mentions_current_area(text) else None
    )
    llm_avoid = llm_constraints.get("avoid") or []
    avoid = list(dict.fromkeys(avoid + llm_avoid))
    explicit_preferences = [word for word in PREFERENCE_WORDS if word in text and word not in avoid]
    if "看展" in text and "展览" not in explicit_preferences and "展览" not in avoid:
        explicit_preferences.append("展览")
    raw_preferences = explicit_preferences or ([] if _looks_like_travel_request(text) else llm_constraints.get("preferences") or [])
    preferences = _remove_avoided_preferences(raw_preferences, avoid)

    task_type = _infer_task_type(text, llm_constraints, state.constraints)
    if task_type == "meal" and "美食" not in preferences and "美食" not in avoid:
        preferences = list(dict.fromkeys(preferences + ["美食"]))
    state.goal = llm_constraints.get("goal") or _infer_goal_from_roles(text, city, place_roles)
    hotel_brand = "汉庭" if "汉庭" in text else None
    updates = {
        "task_type": task_type,
        "city": city or llm_constraints.get("city"),
        "origin": origin_role,
        "destination": destination_role,
        "activity_area": place_roles.get("activity_area"),
        "via_points": place_roles.get("via_points"),
        "route_scope": place_roles.get("route_scope") if place_roles.get("route_scope") != "unknown" else ("city_trip" if city else None),
        "activity_intent": place_roles.get("activity_intent"),
        "destination_city": (destination_role or {}).get("city"),
        "destination_place": (destination_role or {}).get("name"),
        "destination_type": (destination_role or {}).get("type"),
        "origin_city": (origin_role or {}).get("city") or state.constraints.get("origin_city"),
        "origin_location": current_location,
        "date": date or llm_constraints.get("date"),
        "time_window": llm_constraints.get("time_window") or ("全天" if any(word in text for word in ["一天", "全天"]) else None),
        "budget": budget or llm_constraints.get("budget"),
        "pace": pace or llm_constraints.get("pace"),
        "preferences": preferences,
        "avoid": avoid,
        "hotel_brand": llm_constraints.get("hotel_brand") or hotel_brand,
        "trip_days": llm_constraints.get("trip_days") or _extract_trip_days(text),
    }
    for key, value in updates.items():
        if value not in (None, [], ""):
            state.constraints[key] = value
    state.intent_contract = _build_intent_contract(state, llm_constraints)

    _log(state, "intent_extraction", f"识别到任务：{state.goal or '生活规划'}", {
        "task_type": task_type,
        "missing_fields": llm_constraints.get("missing_fields", []),
        "confidence": llm_constraints.get("confidence", 0),
    })
    return state


def normalize_dates(state: AgentState) -> AgentState:
    resolved = resolve_date_text(state.constraints.get("date"))
    for key, value in resolved.items():
        if value:
            state.constraints[key] = value
    _log(state, "date_resolver", "将相对日期转换为具体日期", {
        "input": state.constraints.get("date"),
        "date_iso": state.constraints.get("date_iso"),
        "date_weekday": state.constraints.get("date_weekday"),
    })
    return state


def load_memory(state: AgentState) -> AgentState:
    state.user_profile = load_user_profile(state.user_id)
    overrides = state.constraints.get("memory_overrides") or {}
    disabled_likes = set(overrides.get("disabled_likes") or [])
    disabled_dislikes = set(overrides.get("disabled_dislikes") or [])
    session_likes = list(overrides.get("session_likes") or [])
    session_dislikes = list(overrides.get("session_dislikes") or [])
    explicit_likes = list(state.constraints.get("preferences") or [])
    explicit_dislikes = list(state.constraints.get("avoid") or [])
    explicit_like_set = set(explicit_likes)
    explicit_dislike_set = set(explicit_dislikes)
    profile_likes = [
        item for item in state.user_profile.get("likes", [])
        if item not in disabled_likes and item not in explicit_dislike_set
    ]
    profile_dislikes = [
        item for item in state.user_profile.get("dislikes", [])
        if item not in disabled_dislikes and item not in explicit_like_set
    ]
    session_likes = [item for item in session_likes if item not in explicit_dislike_set]
    session_dislikes = [item for item in session_dislikes if item not in explicit_like_set]
    applied_dislikes = list(dict.fromkeys(explicit_dislikes + session_dislikes + profile_dislikes))
    applied_likes = [
        item for item in dict.fromkeys(explicit_likes + profile_likes + session_likes)
        if item not in set(applied_dislikes)
    ]
    state.constraints["preferences"] = applied_likes
    state.constraints["avoid"] = applied_dislikes
    if not state.constraints.get("pace"):
        state.constraints["pace"] = state.user_profile.get("pace")
    if not state.constraints.get("budget_style"):
        state.constraints["budget_style"] = state.user_profile.get("budget_style")
    state.memory_resolution = {
        "applied_likes": applied_likes,
        "applied_dislikes": applied_dislikes,
        "suppressed_likes": [
            {"value": item, "reason": "本轮已禁用"}
            for item in state.user_profile.get("likes", [])
            if item in disabled_likes
        ],
        "suppressed_dislikes": [
            {"value": item, "reason": "本轮已禁用"}
            for item in state.user_profile.get("dislikes", [])
            if item in disabled_dislikes
        ],
        "pace": state.constraints.get("pace"),
        "budget_style": state.constraints.get("budget_style"),
    }
    _log(state, "memory_lookup", "读取长期偏好补全当前约束", state.user_profile)
    return state


def check_clarification(state: AgentState) -> AgentState:
    missing = []
    task_type = state.constraints.get("task_type") or "travel"
    has_destination = bool(
        state.constraints.get("destination")
        or state.constraints.get("destination_place")
        or state.constraints.get("activity_area")
        or state.constraints.get("city")
    )
    is_travel_request = _looks_like_travel_request(state.user_input)
    if task_type == "todo":
        required = []
    elif task_type in {"errand", "meal"}:
        required = []
    else:
        required = [] if is_travel_request else [("date", "日期")]
    if task_type != "todo" and not has_destination:
        required.insert(0, ("city", "城市/目的地"))
    if task_type == "unknown" and not is_travel_request:
        required.append(("preferences", "偏好"))
    for key, label in required:
        if key == "city" and has_destination:
            continue
        if not state.constraints.get(key):
            missing.append(label)
    if missing:
        state.need_human_confirm = True
        state.clarification_question = "还需要补充：" + "、".join(missing)
        _log(state, "clarification", "当前信息不足，需要用户补充", {"missing": missing})
    else:
        _log(state, "clarification", "信息足够，继续执行规划", {"missing": []})
    return state


def plan_steps(state: AgentState) -> AgentState:
    state.execution_plan = _build_execution_plan(state)
    state.plan_steps = _execution_plan_to_steps(state.execution_plan)
    _log(state, "planner", "生成本轮动态执行计划", {
        "intent_contract": state.intent_contract,
        "execution_plan": state.execution_plan,
        "steps": state.plan_steps,
    })
    return state


def execute_plan(state: AgentState) -> AgentState:
    state.artifacts = {}
    for step in state.execution_plan or _build_execution_plan(state):
        tool = step.get("tool")
        if tool not in _allowed_dynamic_tools():
            step["status"] = "skipped"
            continue
        step["status"] = "running"
        try:
            _execute_dynamic_step(state, step)
        except Exception:
            step["status"] = "failed"
            state.plan_steps = _execution_plan_to_steps(state.execution_plan)
            raise
        step["status"] = "completed"
    state.plan_steps = _execution_plan_to_steps(state.execution_plan)
    _log(state, "execute_plan", "按意图执行动态工具计划", {
        "execution_plan": state.execution_plan,
        "artifacts": _artifact_summary(state.artifacts),
    })
    return state


def synthesize_plan(state: AgentState) -> AgentState:
    state.final_plan = _build_dynamic_plan(state)
    if state.final_plan is not None:
        state.final_plan.setdefault("intent_contract", state.intent_contract)
        state.final_plan.setdefault("execution_plan", state.execution_plan)
    _log(state, "synthesize_plan", "根据意图合同和工具结果生成计划", {
        "intent_contract": state.intent_contract,
        "result_types": (state.intent_contract or {}).get("required_outputs", []),
        "plan_task_type": state.final_plan.get("task_type") if state.final_plan else None,
        "itinerary_count": len((state.final_plan or {}).get("itinerary") or []),
    })
    return state


def route_task(state: AgentState) -> AgentState:
    task_type = state.constraints.get("task_type") or "travel"
    if task_type not in {"travel", "errand", "meal", "todo"}:
        task_type = "travel"
    state.constraints["task_type"] = task_type
    _log(state, "task_router", "按任务类型选择执行分支", {"task_type": task_type})
    return state


def call_tools(state: AgentState) -> AgentState:
    if state.constraints.get("task_type") == "todo":
        return todo_decomposer(state)
    if state.constraints.get("task_type") in {"errand", "meal"}:
        return _call_life_task_tools(state)
    return travel_tool_router(state)


def todo_decomposer(state: AgentState) -> AgentState:
    parsed = _parse_todo_goal(state.user_input)
    state.tool_results.append(_tool_result("todo_rule_parser", parsed))
    state._weather = {}  # type: ignore[attr-defined]
    state._places = []  # type: ignore[attr-defined]
    state._lifestyle_places = {"foods": [], "hotels": []}  # type: ignore[attr-defined]
    state._search_results = {"provider": "none", "results": [], "note": "todo 场景不调用地图/天气/网页搜索"}  # type: ignore[attr-defined]
    state._travel_research = {"provider": "none", "sources": [], "note": "todo 场景使用规则拆解，不调用外部工具"}  # type: ignore[attr-defined]
    state._todo_parse = parsed  # type: ignore[attr-defined]
    _log(state, "todo_decomposer", "todo 场景跳过地图、天气和搜索工具", {"task_type": "todo", "items_count": len(parsed.get("tasks", []))})
    return state


def errand_tool_router(state: AgentState) -> AgentState:
    return _call_life_task_tools(state)


def meal_tool_router(state: AgentState) -> AgentState:
    return _call_life_task_tools(state)


def travel_tool_router(state: AgentState) -> AgentState:
    destination = state.constraints.get("destination") or {}
    origin = state.constraints.get("origin") or {}
    city = state.constraints.get("destination_city") or destination.get("city") or state.constraints.get("city")
    preferences = state.constraints.get("preferences") or []
    avoid = state.constraints.get("avoid") or []
    date_for_tools = state.constraints.get("date_iso") or state.constraints.get("date")

    _emit_tool_event(
        state,
        "tool_router",
        "weather_tool",
        "正在查询天气",
        "running",
        input_data={"city": city, "date": date_for_tools, "destination": destination.get("name")},
        progress=45,
    )
    weather = _tool_result("weather_tool", get_weather(city, date_for_tools))
    _emit_tool_event(
        state,
        "tool_router",
        "weather_tool",
        "天气查询完成",
        "done",
        input_data={"city": city, "date": date_for_tools, "destination": destination.get("name")},
        output_summary=_weather_summary(weather["data"]),
        preview_items=[_weather_summary(weather["data"])],
        progress=49,
    )

    _emit_tool_event(
        state,
        "tool_router",
        "place_search_tool",
        "正在搜索候选地点",
        "running",
        input_data={"city": city, "destination": destination, "origin": origin, "preferences": preferences, "avoid": avoid, "hotel_brand": state.constraints.get("hotel_brand")},
        progress=52,
    )
    places_raw = search_places(city, preferences, avoid, state.constraints.get("hotel_brand"))
    places_raw = _prepend_destination_places(places_raw, state)
    city_places = _filter_places_by_city(places_raw, city)
    if city_places:
        city_places = _ensure_city_trip_places(city_places, state, city)
    _emit_tool_event(
        state,
        "tool_router",
        "place_search_tool",
        "候选地点搜索完成",
        "done",
        input_data={"city": city, "destination": destination, "preferences": preferences, "avoid": avoid, "hotel_brand": state.constraints.get("hotel_brand")},
        output_summary={
            "provider": _first_place_provider(places_raw),
            "raw_places_count": len(places_raw),
            "city_places_count": len(city_places),
        },
        preview_items=_places_preview(city_places),
        progress=58,
    )

    if not city_places:
        search_data = {
            "provider": "skipped",
            "query": None,
            "results": [],
            "note": "地点搜索未返回真实候选，跳过网页补证据并等待用户补充区域/偏好",
        }
        search = _tool_result("web_search_tool", search_data, input_data={"query": None})
        places: list[dict[str, Any]] = []
        travel_places: list[dict[str, Any]] = []
        lifestyle_places = {"foods": [], "hotels": []}
        places_result = _tool_result("place_search_tool", places)
        state.need_human_confirm = True
        state.clarification_question = f"没有查到 {city} 的真实候选地点。请补充更具体的区域/偏好后再试。"
        state.tool_results.extend([weather, places_result, search])
        state._weather = weather["data"]  # type: ignore[attr-defined]
        state._places = travel_places  # type: ignore[attr-defined]
        state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
        state._search_results = search_data  # type: ignore[attr-defined]
        state._travel_research = _build_travel_research(search_data)  # type: ignore[attr-defined]
        _log(state, "tool_router", "地点搜索未返回真实候选，停止生成正式行程", {
            "weather": weather["data"],
            "places_count": 0,
            "travel_places_count": 0,
            "raw_places_count": len(places_raw),
            "avoid": avoid,
            "origin": origin,
            "destination": destination,
            "route_scope": state.constraints.get("route_scope"),
            "search_provider": search_data.get("provider"),
        })
        return state

    search_query = _build_search_query(state)
    _emit_tool_event(
        state,
        "tool_router",
        "web_search_tool",
        "正在补充网页证据",
        "running",
        input_data={"query": search_query, "max_results": 3},
        progress=60,
    )
    search = _tool_result("web_search_tool", _search_web_for_travel(state, search_query, max_results=10), input_data={"query": search_query, "max_results": 10})
    _emit_tool_event(
        state,
        "tool_router",
        "web_search_tool",
        "网页证据补充完成",
        "done",
        input_data={"query": search_query, "max_results": 3},
        output_summary=_search_summary(search["data"]),
        preview_items=_search_preview(search["data"]),
        progress=64,
    )

    _emit_tool_event(
        state,
        "tool_router",
        "place_evidence_merge",
        "正在把网页证据合并到地点",
        "running",
        input_data={"places_count": len(city_places), "search_results_count": len(search["data"].get("results", []))},
        progress=66,
    )
    places = _annotate_places_for_goal(
        _enrich_places_with_search_evidence(city_places, search["data"]),
        state,
    )
    _emit_tool_event(
        state,
        "tool_router",
        "place_evidence_merge",
        "地点证据合并完成",
        "done",
        input_data={"places_count": len(city_places), "search_results_count": len(search["data"].get("results", []))},
        output_summary={
            "matched_places_count": sum(1 for place in places if place.get("evidence")),
            "sources_count": len(_build_travel_research(search["data"]).get("sources", [])),
        },
        preview_items=_evidence_preview(places),
        progress=68,
    )

    travel_places = _filter_travel_places(places, state.constraints.get("preferences", []))
    lifestyle_places = _extract_lifestyle_places(places)
    places_result = _tool_result("place_search_tool", places)
    _emit_tool_event(
        state,
        "tool_router",
        "place_filter",
        "地点分类和过滤完成",
        "done",
        input_data={"places_count": len(places), "avoid": avoid},
        output_summary={
            "travel_places_count": len(travel_places),
            "food_places_count": len(lifestyle_places.get("foods", [])),
            "hotel_places_count": len(lifestyle_places.get("hotels", [])),
        },
        preview_items=_places_preview(travel_places),
        progress=70,
    )

    state.tool_results.extend([weather, places_result, search])
    state._weather = weather["data"]  # type: ignore[attr-defined]
    state._places = travel_places  # type: ignore[attr-defined]
    state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
    state._search_results = search["data"]  # type: ignore[attr-defined]
    state._travel_research = _build_travel_research(search["data"])  # type: ignore[attr-defined]

    _log(state, "tool_router", "完成天气、地点和实时信息查询", {
        "weather": weather["data"],
        "places_count": len(places),
        "travel_places_count": len(travel_places),
        "raw_places_count": len(places_raw),
        "avoid": avoid,
        "origin": origin,
        "destination": destination,
        "route_scope": state.constraints.get("route_scope"),
        "search_query": search_query,
        "search_provider": search["data"].get("provider"),
        "search_results_count": len(search["data"].get("results", [])),
        "research_sources": len(state._travel_research.get("sources", [])),  # type: ignore[attr-defined]
    })
    return state


def score_candidates_node(state: AgentState) -> AgentState:
    if state.constraints.get("task_type") == "todo":
        state.candidates = []
        _log(state, "candidate_scorer", "todo 场景无需地点候选评分", {"task_type": "todo"})
        return state
    state.candidates = sorted(score_candidates(
        state._places,  # type: ignore[attr-defined]
        state.constraints.get("preferences", []),
        state.constraints.get("budget"),
        state.constraints.get("pace"),
        state._weather,  # type: ignore[attr-defined]
    ), key=_travel_priority, reverse=True)
    _log(state, "candidate_scorer", "对候选地点进行排序", {
        "top_candidates": [item["name"] for item in state.candidates[:5]]
    })
    return state


def travel_candidate_scorer(state: AgentState) -> AgentState:
    return score_candidates_node(state)


def errand_candidate_scorer(state: AgentState) -> AgentState:
    state.candidates = list(getattr(state, "_places", []))
    _log(state, "errand_candidate_scorer", "跑腿场景保留地点候选用于顺路安排", {"candidates_count": len(state.candidates)})
    return state


def meal_candidate_scorer(state: AgentState) -> AgentState:
    foods = (getattr(state, "_lifestyle_places", {}) or {}).get("foods", [])
    state.candidates = _meal_candidates(foods or getattr(state, "_places", []), state.constraints)
    _log(state, "meal_candidate_scorer", "餐饮场景整理餐厅候选", {"candidates_count": len(state.candidates)})
    return state


def _call_life_task_tools(state: AgentState) -> AgentState:
    task_type = state.constraints.get("task_type")
    node_name = f"{task_type}_tool_router" if task_type in {"errand", "meal"} else "tool_router"
    city = state.constraints.get("city") or state.constraints.get("default_city")
    preferences = state.constraints.get("preferences") or (["美食"] if task_type == "meal" else [])
    avoid = state.constraints.get("avoid") or []
    places = search_places(city, preferences, avoid, state.constraints.get("hotel_brand")) if city else []
    lifestyle_places = _extract_lifestyle_places(places)
    if task_type == "meal" and not lifestyle_places.get("foods"):
        lifestyle_places["foods"] = _meal_candidates(places, state.constraints)
    places_result = _tool_result("place_search_tool", places)
    state.tool_results.append(places_result)
    state._weather = {}  # type: ignore[attr-defined]
    state._places = places  # type: ignore[attr-defined]
    state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
    state._search_results = {"provider": "none", "results": [], "note": f"{task_type} 场景跳过网页搜索"}  # type: ignore[attr-defined]
    state._travel_research = {"provider": "none", "sources": [], "note": f"{task_type} 场景使用规则和地点候选生成 MVP"}  # type: ignore[attr-defined]
    _log(state, node_name, "完成生活任务轻量工具准备", {
        "task_type": task_type,
        "city": city,
        "places_count": len(places),
        "food_places_count": len(lifestyle_places.get("foods", [])),
        "skipped_tools": ["weather_tool", "web_search_tool"],
    })
    return state


def generate_plan(state: AgentState) -> AgentState:
    task_type = state.constraints.get("task_type") or "travel"
    if task_type == "todo":
        state.final_plan = _build_todo_plan(state)
        _log(state, "plan_generator", "生成待办拆解计划", {
            "task_type": "todo",
            "tasks_count": len(state.final_plan.get("todo_items", [])) if state.final_plan else 0,
        })
        return state
    if task_type == "errand":
        state.final_plan = _build_errand_plan(state)
        _log(state, "plan_generator", "生成跑腿顺路计划", {
            "task_type": "errand",
            "items_count": len(state.final_plan.get("errand_items", [])) if state.final_plan else 0,
        })
        return state
    if task_type == "meal":
        state.final_plan = _build_meal_plan(state)
        _log(state, "plan_generator", "生成餐饮计划", {
            "task_type": "meal",
            "candidates_count": len(state.final_plan.get("meal_candidates", [])) if state.final_plan else 0,
        })
        return state

    selected = _select_places(state.candidates, state.constraints, state.replan_context)
    selected = _ensure_place_locations(selected)
    access_route_data = _estimate_access_route_if_needed(state)
    _emit_tool_event(
        state,
        "plan_generator",
        "route_tool",
        "正在估算到达路线和目的地内路线",
        "running",
        input_data={
            "origin": state.constraints.get("origin"),
            "destination": state.constraints.get("destination"),
            "selected_places": [item.get("name") for item in selected],
        },
        progress=73,
    )
    route = _tool_result("route_tool", estimate_route(selected))
    route["data"]["access_route"] = access_route_data
    _emit_tool_event(
        state,
        "plan_generator",
        "route_tool",
        "路线估算完成",
        "done",
        input_data={
            "origin": state.constraints.get("origin"),
            "destination": state.constraints.get("destination"),
            "selected_places": [item.get("name") for item in selected],
        },
        output_summary=_route_summary(route["data"]),
        preview_items=_route_preview(route["data"]),
        progress=76,
    )
    _emit_tool_event(
        state,
        "plan_generator",
        "budget_tool",
        "正在计算预算",
        "running",
        input_data={"budget_limit": state.constraints.get("budget"), "pace": state.constraints.get("pace")},
        progress=78,
    )
    budget = _tool_result(
        "budget_tool",
        estimate_budget(route["data"]["ordered_places"], state.constraints.get("budget"), state.constraints.get("pace")),
    )
    _emit_tool_event(
        state,
        "plan_generator",
        "budget_tool",
        "预算计算完成",
        "done",
        input_data={"budget_limit": state.constraints.get("budget"), "pace": state.constraints.get("pace")},
        output_summary=_budget_summary(budget["data"]),
        preview_items=_budget_preview(budget["data"]),
        progress=80,
    )
    state.tool_results.extend([route, budget])

    base_plan = _build_rule_based_plan(state, route["data"], budget["data"])
    llm_plan = _generate_plan_with_llm(state, route["data"], budget["data"], base_plan)
    if llm_plan and _plan_uses_candidate_places(llm_plan, selected) and _plan_has_enough_city_items(llm_plan, state):
        llm_plan.setdefault("weather", base_plan.get("weather"))
        llm_plan.setdefault("travel_research", base_plan.get("travel_research"))
        llm_plan.setdefault("alternatives", base_plan.get("alternatives", []))
        llm_plan.setdefault("access_route", base_plan.get("access_route"))
        llm_plan.setdefault("local_route", base_plan.get("local_route"))
        llm_plan.setdefault("destination_validation", base_plan.get("destination_validation"))
        llm_plan["budget"] = base_plan.get("budget", llm_plan.get("budget", {}))
        llm_plan["summary"] = base_plan.get("summary", llm_plan.get("summary", ""))
        state.final_plan = _enrich_plan_items(llm_plan, selected)
    else:
        if llm_plan:
            state.llm_usage.append({"node": "plan_generator", "status": "rejected", "reason": "plan_contains_places_not_returned_by_tools"})
        state.final_plan = base_plan

    _log(state, "plan_generator", "生成最终计划", {
        "selected_places": [item["name"] for item in selected],
        "covered_preferences": sorted(_covered_preferences(selected, state.constraints.get("preferences", []))),
        "budget_total": state.final_plan["budget"]["total"] if state.final_plan else None,
    })
    return state


def travel_plan_generator(state: AgentState) -> AgentState:
    return generate_plan(state)


def _plan_has_enough_city_items(plan: dict[str, Any], state: AgentState) -> bool:
    destination = state.constraints.get("destination") or {}
    if state.constraints.get("route_scope") != "city_trip" and destination.get("type") != "city":
        return True
    if state.constraints.get("preferences"):
        return True
    return len(plan.get("itinerary") or []) >= 3


def errand_plan_generator(state: AgentState) -> AgentState:
    state.final_plan = _build_errand_plan(state)
    _log(state, "errand_plan_generator", "生成跑腿顺路计划", {
        "task_type": "errand",
        "items_count": len(state.final_plan.get("errand_items", [])) if state.final_plan else 0,
    })
    return state


def meal_plan_generator(state: AgentState) -> AgentState:
    state.final_plan = _build_meal_plan(state)
    _log(state, "meal_plan_generator", "生成餐饮计划", {
        "task_type": "meal",
        "candidates_count": len(state.final_plan.get("meal_candidates", [])) if state.final_plan else 0,
    })
    return state


def todo_plan_generator(state: AgentState) -> AgentState:
    state.final_plan = _build_todo_plan(state)
    _log(state, "todo_plan_generator", "生成待办拆解计划", {
        "task_type": "todo",
        "tasks_count": len(state.final_plan.get("todo_items", [])) if state.final_plan else 0,
    })
    return state


def check_risks_node(state: AgentState) -> AgentState:
    result = check_risks(state.final_plan or {}, state.constraints, getattr(state, "_weather", {}))
    coverage_issue = _coverage_issue(state)
    if coverage_issue:
        result["risks"].append(coverage_issue)
    destination_issue = _destination_issue(state)
    if destination_issue:
        result["risks"].append(destination_issue)
    for issue in _intent_contract_issues(state):
        if issue not in result["risks"]:
            result["risks"].append(issue)
    state.risks = result["risks"]
    state.fallbacks = result["fallbacks"]
    state.need_human_confirm = result["need_human_confirm"]
    _log(state, "risk_checker", "检查预算、天气、节奏和偏好覆盖", result)
    return state


def reflect(state: AgentState) -> AgentState:
    issues = list(state.risks)
    if not state.final_plan or not _plan_has_executable_items(state.final_plan):
        issues.append("没有生成有效行程")
    replan_needed = any(_issue_requires_replan(issue) for issue in issues)
    passed = not any("超过用户限制" in issue or "没有生成" in issue for issue in issues) and not replan_needed
    rule_reflection = {
        "passed": passed,
        "issues": issues,
        "next_action": "final" if passed else "replan" if replan_needed else "ask_user",
        "review": "计划满足核心约束" if passed else "计划仍有未满足约束",
    }
    if state.constraints.get("task_type") in {"errand", "meal", "todo"} or _uses_fallback_places(state.final_plan or {}):
        state.reflection = rule_reflection
    else:
        llm_reflection = _reflect_with_llm(state, rule_reflection) or rule_reflection
        if rule_reflection["passed"] and not _has_hard_reflection_issue(llm_reflection):
            llm_reflection["passed"] = True
            llm_reflection["next_action"] = "final"
            llm_reflection["issues"] = []
        state.reflection = llm_reflection
    state.reflection["replan_count"] = state.replan_count
    _log(state, "reflection", "评估当前计划是否可直接输出", state.reflection)
    return state


def final_response(state: AgentState) -> dict[str, Any]:
    if state.clarification_question:
        return {
            "status": "need_clarification",
            "trace_id": state.trace_id,
            "question": state.clarification_question,
            "constraints": state.constraints,
            "llm_usage": state.llm_usage,
            "execution_log": state.execution_log,
        }

    is_final = _reflection_is_final(state.reflection)
    quality_warnings = [] if is_final else _reflection_issues(state.reflection)
    assistant_message = _build_assistant_message(state)
    if quality_warnings:
        assistant_message = _with_quality_warning(assistant_message, quality_warnings)
    if state.final_plan and _is_travel_guide_plan(state.final_plan):
        state.final_plan["assistant_message"] = assistant_message
        state.final_plan["overview"] = assistant_message
        state.final_plan["summary"] = assistant_message
    _log(state, "final_response", "组装给用户的自然语言回复", {"assistant_message": assistant_message})
    return {
        "status": "success" if is_final else "partial_success",
        "trace_id": state.trace_id,
        "constraints": state.constraints,
        "plan_steps": state.plan_steps,
        "tool_results": state.tool_results,
        "candidates": state.candidates,
        "final_plan": state.final_plan,
        "assistant_message": assistant_message,
        "quality_warnings": quality_warnings,
        "risks": state.risks,
        "fallbacks": state.fallbacks,
        "reflection": state.reflection,
        "llm_usage": state.llm_usage,
        "execution_log": state.execution_log,
    }


def _reflection_is_final(reflection: dict[str, Any] | None) -> bool:
    if not reflection:
        return True
    return reflection.get("passed") is True and reflection.get("next_action") == "final"


def _reflection_issues(reflection: dict[str, Any] | None) -> list[str]:
    if not reflection:
        return []
    issues = reflection.get("issues") or []
    if isinstance(issues, str):
        return [issues]
    return [str(issue) for issue in issues if issue]


def _has_hard_reflection_issue(reflection: dict[str, Any]) -> bool:
    issues = _reflection_issues(reflection)
    hard_words = ["超过用户限制", "没有生成", "目的地与用户目标不符", "缺少从出发地到目的地", "没有安排该目的地"]
    return any(any(word in issue for word in hard_words) for issue in issues)


def _with_quality_warning(message: str, warnings: list[str]) -> str:
    warning_lines = "\n".join(f"- {warning}" for warning in warnings[:5])
    prefix = "当前方案未完全满足你的要求，需要先确认这些问题：\n" + warning_lines
    if not message:
        return prefix
    return prefix + "\n\n下面是目前仍可参考的行程：\n\n" + message


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


def _generate_plan_with_llm(state: AgentState, route: dict, budget: dict, base_plan: dict[str, Any]) -> dict[str, Any] | None:
    if not _llm_enabled():
        return None
    payload = {
        "user_input": state.user_input,
        "constraints": state.constraints,
        "weather": state._weather,  # type: ignore[attr-defined]
        "web_search": state._search_results,  # type: ignore[attr-defined]
        "travel_research": state._travel_research,  # type: ignore[attr-defined]
        "lifestyle_places": state._lifestyle_places,  # type: ignore[attr-defined]
        "candidates": state.candidates[:8],
        "route": route,
        "budget": budget,
        "base_plan": base_plan,
        "reflection": state.replan_context or state.reflection,
        "instruction": "先基于 web_search/travel_research 总结天气、近期活动、景点攻略等依据；选点必须先满足用户目标和偏好，其次优先当地热门/标志性景点和有近期活动证据的地点，再只使用 candidates/base_plan 中已有地点生成路线；必须遵守 avoid，不要编造来源。",
    }
    try:
        plan = llm_client.json_complete(PLAN_GENERATOR_PROMPT, json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        state.llm_usage.append({"node": "plan_generator", "status": "error", "error": str(exc)})
        return None
    if not plan.get("itinerary") or not plan.get("budget"):
        state.llm_usage.append({"node": "plan_generator", "status": "ignored", "reason": "invalid_json_shape"})
        return None
    plan.setdefault("assistant_message", _build_assistant_message_from_plan(plan))
    state.llm_usage.append({"node": "plan_generator", "status": "success", "model": _llm_model_name()})
    return plan


def _reflect_with_llm(state: AgentState, rule_reflection: dict[str, Any]) -> dict[str, Any] | None:
    if not _llm_enabled():
        return None
    payload = {
        "intent_contract": state.intent_contract,
        "execution_plan": state.execution_plan,
        "constraints": state.constraints,
        "final_plan": state.final_plan,
        "risks": state.risks,
        "fallbacks": state.fallbacks,
        "rule_reflection": rule_reflection,
    }
    try:
        reflection = llm_client.json_complete(REFLECTION_PROMPT, json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        state.llm_usage.append({"node": "reflection", "status": "error", "error": str(exc)})
        return None
    if "passed" not in reflection or "next_action" not in reflection:
        state.llm_usage.append({"node": "reflection", "status": "ignored", "reason": "invalid_json_shape"})
        return None
    state.llm_usage.append({"node": "reflection", "status": "success", "model": _llm_model_name()})
    return reflection


def _build_intent_contract(state: AgentState, llm_constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    text = state.user_input
    llm_constraints = llm_constraints or {}
    sub_tasks = _infer_sub_tasks(text, state.constraints)
    if state.is_followup and state.previous_intent_contract and not _is_explicit_task_switch(text):
        sub_tasks = _dedupe_sub_tasks(
            list(state.previous_intent_contract.get("sub_tasks") or []) + sub_tasks
        )
    hard_constraints = {
        key: state.constraints.get(key)
        for key in ["city", "destination", "origin", "date", "date_iso", "time_window", "budget", "pace", "route_scope"]
        if state.constraints.get(key) not in (None, "", [])
    }
    soft_preferences = {
        "preferences": state.constraints.get("preferences", []),
        "avoid": state.constraints.get("avoid", []),
        "companions": llm_constraints.get("companions"),
    }
    required_outputs = _required_outputs_for_subtasks(sub_tasks)
    missing_fields = list(llm_constraints.get("missing_fields") or [])
    return {
        "goal": state.goal or llm_constraints.get("goal") or _infer_goal(text, state.constraints.get("city")),
        "primary_task_type": state.constraints.get("task_type") or "unknown",
        "sub_tasks": sub_tasks,
        "hard_constraints": hard_constraints,
        "soft_preferences": soft_preferences,
        "required_outputs": required_outputs,
        "missing_fields": missing_fields,
    }


def _infer_sub_tasks(text: str, constraints: dict[str, Any]) -> list[dict[str, Any]]:
    sub_tasks: list[dict[str, Any]] = []
    if _has_errand_intent(text):
        sub_tasks.append({"type": "errand", "label": "跑腿/顺路事项", "source": "rule"})
    if _has_meal_intent(text):
        sub_tasks.append({"type": "meal", "label": "餐饮安排", "source": "rule"})
    if _has_todo_intent(text):
        sub_tasks.append({"type": "todo", "label": "待办拆解", "source": "rule"})
    has_non_travel_life_task = any(item.get("type") in {"errand", "meal", "todo"} for item in sub_tasks)
    destination = constraints.get("destination") or {}
    has_specific_destination = bool(destination and destination.get("type") not in {"city", "district"})
    if _looks_like_travel_request(text) or has_specific_destination or (constraints.get("activity_area") and not has_non_travel_life_task):
        sub_tasks.append({"type": "travel", "label": "出行/游玩路线", "source": "rule"})
    if not sub_tasks:
        task_type = constraints.get("task_type") if constraints.get("task_type") in {"travel", "errand", "meal", "todo"} else "todo"
        sub_tasks.append({"type": task_type, "label": "生活任务规划", "source": "fallback"})
    return _dedupe_sub_tasks(sub_tasks)


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


def _required_outputs_for_subtasks(sub_tasks: list[dict[str, Any]]) -> list[str]:
    outputs = {"summary", "budget", "risks", "confirm_actions"}
    task_types = {item.get("type") for item in sub_tasks}
    if task_types.intersection({"travel", "errand", "meal"}):
        outputs.update({"itinerary", "route"})
    if "errand" in task_types:
        outputs.add("errand_items")
    if "meal" in task_types:
        outputs.add("meal_candidates")
    if "todo" in task_types:
        outputs.update({"todo_items", "time_blocks", "acceptance_criteria"})
    return sorted(outputs)


def _build_execution_plan(state: AgentState) -> list[dict[str, Any]]:
    contract = state.intent_contract or _build_intent_contract(state)
    task_types = {item.get("type") for item in contract.get("sub_tasks", [])}
    steps: list[dict[str, Any]] = []
    if "todo" in task_types:
        steps.append({"tool": "todo_decompose", "purpose": "拆解待办和完成标准"})
    if task_types.intersection({"travel", "errand", "meal"}):
        if "travel" in task_types:
            steps.append({"tool": "weather", "purpose": "判断天气和室内外风险"})
        steps.append({"tool": "place_search", "purpose": "查找可导航地点候选"})
        if "travel" in task_types:
            steps.append({"tool": "search", "purpose": "补充网页来源和近期信息"})
        if "meal" in task_types:
            steps.append({"tool": "meal_pick", "purpose": "筛选餐饮候选"})
        if "errand" in task_types:
            steps.append({"tool": "errand_parse", "purpose": "整理跑腿事项"})
        steps.append({"tool": "route", "purpose": "估算路线和顺路顺序"})
        steps.append({"tool": "budget", "purpose": "估算预算"})
    steps.append({"tool": "confirm_action", "purpose": "列出需要用户确认的外部动作"})
    return _dedupe_execution_steps(steps)


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


def _execution_plan_to_steps(execution_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "step": item.get("purpose") or item.get("tool"),
            "tool": _legacy_tool_name(item.get("tool")),
            "status": item.get("status", "pending"),
        }
        for item in execution_plan
    ]


def _legacy_tool_name(tool: Any) -> str:
    return {
        "todo_decompose": "todo_decomposer",
        "weather": "weather_tool",
        "place_search": "place_search_tool",
        "search": "web_search_tool",
        "meal_pick": "meal_candidate_scorer",
        "errand_parse": "errand_candidate_scorer",
        "route": "route_tool",
        "budget": "budget_tool",
        "confirm_action": "confirm_action_builder",
    }.get(str(tool or ""), str(tool or "unknown_tool"))


def _allowed_dynamic_tools() -> set[str]:
    return {"todo_decompose", "weather", "place_search", "search", "meal_pick", "errand_parse", "route", "budget", "confirm_action"}


def _execute_dynamic_step(state: AgentState, step: dict[str, Any]) -> None:
    tool = str(step.get("tool"))
    if tool == "todo_decompose":
        _dynamic_todo_decompose(state)
    elif tool == "weather":
        _dynamic_weather(state)
    elif tool == "place_search":
        _dynamic_place_search(state)
    elif tool == "search":
        _dynamic_search(state)
    elif tool == "meal_pick":
        _dynamic_meal_pick(state)
    elif tool == "errand_parse":
        _dynamic_errand_parse(state)
    elif tool == "route":
        _dynamic_route(state)
    elif tool == "budget":
        _dynamic_budget(state)
    elif tool == "confirm_action":
        _dynamic_confirm_actions(state)


def _dynamic_todo_decompose(state: AgentState) -> None:
    parsed = _parse_todo_goal(state.user_input)
    state.artifacts["todo"] = parsed
    state._todo_parse = parsed  # type: ignore[attr-defined]
    state.tool_results.append(_tool_result("todo_rule_parser", parsed))
    _emit_tool_event(state, "execute_plan", "todo_decompose", "拆解待办任务", "done", output_summary={"tasks": len(parsed.get("tasks", []))})


def _dynamic_weather(state: AgentState) -> None:
    city = _dynamic_city(state)
    weather = get_weather(city, state.constraints.get("date_iso") or state.constraints.get("date")) if city else {}
    state.artifacts["weather"] = weather
    state._weather = weather  # type: ignore[attr-defined]
    state.tool_results.append(_tool_result("weather_tool", weather))
    _emit_tool_event(state, "execute_plan", "weather_tool", "获取天气", "done", input_data={"city": city}, output_summary=_weather_summary(weather or {}))


def _dynamic_place_search(state: AgentState) -> None:
    city = _dynamic_city(state)
    preferences = state.constraints.get("preferences") or []
    if _intent_has(state, "meal") and "美食" not in preferences:
        preferences = list(dict.fromkeys(preferences + ["美食"]))
    places: list[dict[str, Any]] = []
    search_batches = _place_search_batches(state, preferences)
    if city and _intent_has(state, "travel"):
        search_batches.extend(_city_guide_search_batches(city))
    if city:
        for batch in search_batches:
            places = _dedupe_places(places + search_places(city, batch, state.constraints.get("avoid") or [], state.constraints.get("hotel_brand")))
        if _intent_has(state, "travel"):
            for batch in _lifestyle_search_batches(state):
                places = _dedupe_places(places + search_places(city, batch, state.constraints.get("avoid") or [], state.constraints.get("hotel_brand")))
    places = _prepend_destination_places(places, state)
    if city:
        places = _filter_places_by_city(places, city)
        if _intent_has(state, "travel"):
            places = _ensure_city_trip_places(places, state, city)
    places = _annotate_places_for_goal(places, state)
    lifestyle_places = _extract_lifestyle_places(places)
    state.artifacts["places"] = places
    state.artifacts["lifestyle_places"] = lifestyle_places
    state._places = places  # type: ignore[attr-defined]
    state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
    state.tool_results.append(_tool_result("place_search_tool", places))
    _emit_tool_event(state, "execute_plan", "place_search_tool", "查找地点候选", "done", input_data={"city": city, "preferences": preferences, "search_batches": search_batches + (_lifestyle_search_batches(state) if city and _intent_has(state, "travel") else [])}, output_summary={"places_count": len(places), "food_places_count": len(lifestyle_places.get("foods", [])), "hotel_places_count": len(lifestyle_places.get("hotels", []))}, preview_items=_places_preview(places))


def _place_search_batches(state: AgentState, preferences: list[str]) -> list[list[str]]:
    cleaned = [preference for preference in preferences if preference != "缇庨"]
    if not _intent_has(state, "travel"):
        return [cleaned]
    food_preferences = [preference for preference in cleaned if preference in _meal_search_words()]
    travel_preferences = _travel_preferences(cleaned)
    if _intent_has(state, "meal"):
        return [
            _city_travel_search_preferences(state, travel_preferences),
            food_preferences or ["美食"],
        ]
    if _is_broad_city_sightseeing_request(state):
        return [_city_travel_search_preferences(state, travel_preferences)]
    return [cleaned]


def _lifestyle_search_batches(state: AgentState) -> list[list[str]]:
    hotel_brand = state.constraints.get("hotel_brand")
    return [
        ["美食", "特色餐厅", "小吃"],
        [hotel_brand, "酒店", "住宿"] if hotel_brand else ["酒店", "住宿"],
    ]


def _city_travel_search_preferences(state: AgentState, preferences: list[str] | None = None) -> list[str]:
    preferences = preferences or []
    activity = state.constraints.get("activity_intent")
    if activity in {"爬山", "登山", "徒步"}:
        base = [activity, "景区", "森林公园", "山"]
    else:
        base = ["景点", "旅游景点", "古镇", "博物馆"]
    return list(dict.fromkeys(preferences + base))


def _city_guide_search_batches(city: str) -> list[list[str]]:
    terms = CITY_GUIDE_POI_QUERY_TERMS.get(city) or []
    return [terms[index:index + 4] for index in range(0, len(terms), 4) if terms[index:index + 4]]


def _travel_preferences(preferences: list[str]) -> list[str]:
    return [preference for preference in preferences if preference not in _meal_search_words() and preference != "缇庨"]


def _meal_search_words() -> set[str]:
    return set(MEAL_INTENT_WORDS) | {"咖啡", "茶馆", "甜品", "烧烤", "夜宵", "餐厅", "小吃", "火锅", "川菜", "美食"}


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


def _search_result_key(item: dict[str, Any]) -> str:
    return str(item.get("url") or item.get("name") or item.get("title") or "").strip()


def _dynamic_search(state: AgentState) -> None:
    query = _build_search_query(state)
    search = _search_web_for_travel(state, query) if query else {"provider": "none", "results": [], "note": "no query"}
    research = _build_travel_research(search)
    places = _enrich_places_with_search_evidence(state.artifacts.get("places", []), search)
    places = _expand_places_from_search_results(places, search, state)
    lifestyle_places = _extract_lifestyle_places(places)
    state.artifacts["search_results"] = search
    state.artifacts["travel_research"] = research
    state.artifacts["places"] = places
    state.artifacts["lifestyle_places"] = lifestyle_places
    state._search_results = search  # type: ignore[attr-defined]
    state._travel_research = research  # type: ignore[attr-defined]
    state._places = places  # type: ignore[attr-defined]
    state._lifestyle_places = lifestyle_places  # type: ignore[attr-defined]
    state.tool_results.append(_tool_result("web_search_tool", search, input_data={"query": query, "max_results": 10}))
    _log(state, "tool_router", "完成网页信息查询", {
        "search_query": query,
        "search_provider": search.get("provider"),
        "search_results_count": len(search.get("results") or []),
        "research_sources": len(research.get("sources") or []),
    })
    _emit_tool_event(state, "execute_plan", "web_search_tool", "补充网页来源", "done", input_data={"query": query}, output_summary={"sources_count": len(research.get("sources", [])), "web_expanded_places_count": len(places), "food_places_count": len(lifestyle_places.get("foods", [])), "hotel_places_count": len(lifestyle_places.get("hotels", []))})


def _expand_places_from_search_results(places: list[dict[str, Any]], search: dict[str, Any], state: AgentState) -> list[dict[str, Any]]:
    city = _dynamic_city(state)
    if not city or not _intent_has(state, "travel"):
        return places
    names = [
        name for name in _extract_place_names_from_search(search)
        if name not in {place.get("name") for place in places}
    ]
    if not names:
        return places
    try:
        lookup_names = names[:8]
        discovered = search_places(city, lookup_names, state.constraints.get("avoid") or [], state.constraints.get("hotel_brand"))
    except Exception:
        return places
    discovered = [
        place for place in _filter_places_by_city(discovered, city)
        if any(_is_relevant_to_place(name, str(place.get("name", ""))) for name in lookup_names)
    ]
    return _dedupe_places(places + _enrich_places_with_search_evidence(discovered, search))


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


def _looks_like_search_place_name(name: str) -> bool:
    if len(name) < 2 or len(name) > 14:
        return False
    blocked = ["中华人民共和国", "云南省", "四川省", "旅游景点", "观光景点", "热门景点", "必去景点", "推荐景点"]
    return not any(word in name for word in blocked)


def _dynamic_meal_pick(state: AgentState) -> None:
    lifestyle = state.artifacts.get("lifestyle_places") or getattr(state, "_lifestyle_places", {"foods": []})
    foods = lifestyle.get("foods") or state.artifacts.get("places", [])
    candidates = _meal_candidates(foods, state.constraints)
    state.artifacts["meal_candidates"] = candidates
    state.candidates = candidates if not state.candidates else state.candidates
    _emit_tool_event(state, "execute_plan", "meal_pick", "筛选餐饮候选", "done", output_summary={"meal_candidates": len(candidates)}, preview_items=_places_preview(candidates))


def _dynamic_errand_parse(state: AgentState) -> None:
    items = _extract_errand_items(state.user_input)
    state.artifacts["errand_items"] = items
    _emit_tool_event(state, "execute_plan", "errand_parse", "整理跑腿事项", "done", output_summary={"items_count": len(items)})


def _dynamic_route(state: AgentState) -> None:
    places = _dynamic_route_places(state)
    route_data = estimate_route(places) if places else {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    if _intent_has(state, "travel"):
        route_data["access_route"] = _estimate_access_route_if_needed(state)
    state.artifacts["route"] = route_data
    state.tool_results.append(_tool_result("route_tool", route_data))
    _emit_tool_event(state, "execute_plan", "route_tool", "估算路线", "done", output_summary=_route_summary(route_data), preview_items=_route_preview(route_data))


def _dynamic_budget(state: AgentState) -> None:
    route_data = state.artifacts.get("route") or {}
    places = route_data.get("ordered_places") or _dynamic_route_places(state)
    budget = estimate_budget(places, state.constraints.get("budget"), state.constraints.get("pace"))
    if _is_mixed_intent(state):
        budget = _constrain_mixed_budget(budget, state.constraints.get("budget"))
    state.artifacts["budget"] = budget
    state.tool_results.append(_tool_result("budget_tool", budget))
    _emit_tool_event(state, "execute_plan", "budget_tool", "估算预算", "done", output_summary=_budget_summary(budget), preview_items=_budget_preview(budget))


def _dynamic_confirm_actions(state: AgentState) -> None:
    actions = []
    if _intent_has(state, "todo"):
        actions.extend(_confirm_actions_for("todo", (state.artifacts.get("todo") or {}).get("tasks", [])))
    if _intent_has(state, "meal"):
        actions.extend(_confirm_actions_for("meal", (state.artifacts.get("meal_candidates") or [])[:1]))
    if _intent_has(state, "errand"):
        actions.extend(_confirm_actions_for("errand", state.artifacts.get("errand_items") or []))
    state.artifacts["confirm_actions"] = actions
    _emit_tool_event(state, "execute_plan", "confirm_action", "生成待确认动作", "done", output_summary={"actions_count": len(actions)})


def _dynamic_city(state: AgentState) -> str | None:
    destination = state.constraints.get("destination") or {}
    return state.constraints.get("destination_city") or destination.get("city") or state.constraints.get("city") or state.constraints.get("default_city")


def _intent_has(state: AgentState, task_type: str) -> bool:
    return any(item.get("type") == task_type for item in (state.intent_contract or {}).get("sub_tasks", []))


def _dynamic_route_places(state: AgentState) -> list[dict[str, Any]]:
    places = state.artifacts.get("places") or getattr(state, "_places", [])
    result: list[dict[str, Any]] = []
    if _intent_has(state, "errand"):
        result.extend(_errand_candidate_places(state.artifacts.get("errand_items") or _extract_errand_items(state.user_input), places))
    if _intent_has(state, "travel"):
        travel_preferences = _travel_preferences(state.constraints.get("preferences", []))
        travel_places = _filter_travel_places(places, travel_preferences)
        if _intent_has(state, "meal"):
            travel_places = [
                place for place in travel_places
                if not set(place.get("tags") or []).intersection({"美食", "火锅", "川菜", "小吃", "茶馆"})
            ]
        scored = sorted(score_candidates(travel_places, travel_preferences, state.constraints.get("budget"), state.constraints.get("pace"), state.artifacts.get("weather") or {}), key=_travel_priority, reverse=True)
        state.candidates = scored
        route_constraints = dict(state.constraints)
        route_constraints["preferences"] = travel_preferences
        result.extend(_select_places(scored, route_constraints, state.replan_context))
    if _intent_has(state, "meal"):
        meal_candidates = state.artifacts.get("meal_candidates") or _meal_candidates((state.artifacts.get("lifestyle_places") or {}).get("foods", []), state.constraints)
        result.extend(meal_candidates[:1])
    return _dedupe_places([_ensure_place_locations([item])[0] for item in result if item])


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


def _is_mixed_intent(state: AgentState) -> bool:
    return len({item.get("type") for item in (state.intent_contract or {}).get("sub_tasks", [])}) > 1


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


def _build_plan_steps(state: AgentState) -> list[dict[str, Any]]:
    task_type = state.constraints.get("task_type") or "travel"
    if task_type == "todo":
        return [
            {"step": "识别目标和约束", "tool": "rule_parser"},
            {"step": "拆解待办任务", "tool": "todo_decomposer"},
            {"step": "安排时间块", "tool": "time_block_planner"},
            {"step": "生成完成标准", "tool": "acceptance_criteria"},
            {"step": "列出需要确认的提醒/日历动作", "tool": "confirm_action_builder"},
        ]
    if task_type == "errand":
        return [
            {"step": "识别跑腿事项", "tool": "rule_parser"},
            {"step": "查询可用地点候选", "tool": "place_search_tool"},
            {"step": "估算顺路路线", "tool": "route_tool"},
            {"step": "估算交通和餐饮预算", "tool": "budget_tool"},
            {"step": "生成顺路时间轴", "tool": "plan_generator"},
            {"step": "列出需要确认的外部动作", "tool": "confirm_action_builder"},
        ]
    if task_type == "meal":
        return [
            {"step": "识别餐饮预算、口味和距离偏好", "tool": "rule_parser"},
            {"step": "查询餐饮地点候选", "tool": "place_search_tool"},
            {"step": "估算路线和预算", "tool": "route_tool/budget_tool"},
            {"step": "生成餐饮候选和推荐理由", "tool": "plan_generator"},
            {"step": "列出需要确认的订座/排队动作", "tool": "confirm_action_builder"},
        ]
    fallback_steps = [
        {"step": "读取用户偏好（旅行请求仅作辅助，不覆盖当次约束）", "tool": "memory_tool"},
        {"step": "查询天气", "tool": "weather_tool"},
        {"step": "用地图工具查询真实地点、地址和可跳转链接", "tool": "place_search_tool"},
        {"step": "网页搜索目的地天气、景点、近期活动、免费玩法和攻略", "tool": "web_search_tool"},
        {"step": "估算路线", "tool": "route_tool"},
        {"step": "估算预算", "tool": "budget_tool"},
        {"step": "生成一日计划", "tool": "plan_generator"},
        {"step": "检查风险", "tool": "risk_checker"},
        {"step": "反思计划质量", "tool": "reflection"},
    ]
    if not _llm_enabled():
        return fallback_steps
    try:
        result = llm_client.json_complete(
            PLANNER_PROMPT,
            json.dumps({"constraints": state.constraints, "goal": state.goal, "user_input": state.user_input}, ensure_ascii=False),
        )
        if isinstance(result.get("steps"), list) and result["steps"]:
            return result["steps"]
    except Exception:
        pass
    return fallback_steps


def _build_search_query(state: AgentState) -> str:
    destination_obj = state.constraints.get("destination") or {}
    city = _search_query_city(state, destination_obj)
    destination = state.constraints.get("destination_place") or destination_obj.get("name") or ""
    date_iso = state.constraints.get("date_iso") or state.constraints.get("date") or ""
    weekday = state.constraints.get("date_weekday") or ""
    preferences = " ".join(state.constraints.get("preferences", []))
    avoid = " ".join(f"避开{item}" for item in state.constraints.get("avoid", []))
    goal = state.goal or ""
    try:
        days = int(state.constraints.get("trip_days") or 1)
    except (TypeError, ValueError):
        days = 1
    trip_text = f"{days}日游" if days > 1 else "一日游"
    parts = [
        city,
        *_city_search_context_terms(city),
        destination,
        date_iso,
        weekday,
        trip_text,
        goal,
        preferences,
        avoid,
        *_search_query_terms(state, destination_obj, days),
    ]
    return " ".join(part for part in _dedupe_text_parts(parts) if part).strip()


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


def _city_search_context_terms(city: str | None) -> list[str]:
    if not city:
        return []
    return CITY_SEARCH_CONTEXT_TERMS.get(str(city), [])


def _explicit_non_default_city(text: str, default_city: str) -> str | None:
    return next((city for city in KNOWN_CITIES if city != default_city and city in text), None)


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


def _is_mountain_or_hiking_trip(
    text: str,
    destination: dict[str, Any],
    preferences: set[str],
    activity_intent: str | None,
) -> bool:
    destination_text = f"{destination.get('name', '')} {destination.get('raw', '')}"
    return (
        bool({"爬山", "登山", "徒步"}.intersection(preferences))
        or activity_intent in {"爬山", "登山", "徒步"}
        or any(word in text for word in ["爬山", "登山", "徒步", "索道"])
        or any(word in destination_text for word in ["华山", "黄山", "泰山", "衡山", "山风景", "风景区"])
    )


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


def _build_rule_based_plan(state: AgentState, route: dict, budget: dict) -> dict[str, Any]:
    itinerary = []
    trip_days = int(state.constraints.get("trip_days") or 1)
    places_per_day = max(1, math.ceil(len(route["ordered_places"]) / max(trip_days, 1)))
    current_day = 1
    current_minutes = 9 * 60 + 30
    legs = route.get("legs", [])
    for index, place in enumerate(route["ordered_places"]):
        day = min(trip_days, index // places_per_day + 1)
        if day != current_day:
            current_day = day
            current_minutes = 9 * 60 + 30
        travel_minutes = legs[index]["minutes"] if index < len(legs) else 20
        current_minutes += max(10, int(travel_minutes))
        start = _time_label(current_minutes)
        current_minutes += place["duration_minutes"]
        end = _time_label(current_minutes)
        itinerary.append({
            "day": day,
            "time": f"{start}-{end}",
            "place": place["name"],
            "area": place["area"],
            "address": place.get("address"),
            "location": place.get("location"),
            "map_url": place.get("map_url"),
            "source_url": place.get("source_url"),
            "source_title": place.get("source_title"),
            "play_points": place.get("play_points", []),
            "cost_note": place.get("cost_note"),
            "cost_known": place.get("cost_known", False),
            "evidence": place.get("evidence", []),
            "reason": "；".join(place.get("score_reasons", [])[:2]) or "综合评分较高",
            "cost": place["estimated_cost"],
            "tags": place["tags"],
        })
    destination_name = (state.constraints.get("destination") or {}).get("name") or state.constraints.get("destination_place")
    title_place = destination_name or state.constraints.get("city", "本地")
    validation = _validate_destination_plan(state, itinerary)
    access_route = route.get("access_route") or {}
    return {
        "task_type": "travel",
        "title": f"{title_place}一日计划",
        "goal": state.goal,
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "trip_days": trip_days,
        "origin": state.constraints.get("origin"),
        "destination": state.constraints.get("destination"),
        "access_route": access_route,
        "local_route": {"ordered_places": route["ordered_places"], "legs": route["legs"], "travel_minutes": route.get("travel_minutes")},
        "destination_validation": validation,
        "weather": state._weather,  # type: ignore[attr-defined]
        "travel_research": state._travel_research,  # type: ignore[attr-defined]
        "lifestyle_places": state._lifestyle_places,  # type: ignore[attr-defined]
        "itinerary": itinerary,
        "alternatives": _build_alternatives(state.candidates, route["ordered_places"]),
        "recommendation_basis": _recommendation_basis(state, route["ordered_places"], state.candidates),
        "guide_places": _guide_place_candidates(state.artifacts.get("places") or getattr(state, "_places", [])),
        "route": route["legs"],
        "budget": budget,
        "summary": _summary(itinerary, budget, access_route),
    }


def _build_dynamic_plan(state: AgentState) -> dict[str, Any]:
    if not state.intent_contract:
        state.intent_contract = _build_intent_contract(state)
    task_types = {item.get("type") for item in state.intent_contract.get("sub_tasks", [])}
    if task_types == {"todo"}:
        return _build_todo_plan(state)
    if task_types == {"meal"}:
        return _build_meal_plan(state)
    if task_types == {"errand"}:
        return _build_errand_plan(state)
    if task_types == {"travel"}:
        return _build_dynamic_travel_plan(state)
    return _build_mixed_plan(state, task_types)


def _build_dynamic_travel_plan(state: AgentState) -> dict[str, Any]:
    route = state.artifacts.get("route") or {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    budget = state.artifacts.get("budget") or estimate_budget(route.get("ordered_places", []), state.constraints.get("budget"), state.constraints.get("pace"))
    if route.get("ordered_places"):
        plan = _build_rule_based_plan(state, route, budget)
    else:
        plan = _build_errand_plan(state) if _has_errand_intent(state.user_input) else _build_todo_plan(state)
        plan["task_type"] = "travel"
    plan["intent_contract"] = state.intent_contract
    plan["execution_plan"] = state.execution_plan
    return plan


def _build_mixed_plan(state: AgentState, task_types: set[str]) -> dict[str, Any]:
    route = state.artifacts.get("route") or {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    budget = state.artifacts.get("budget") or estimate_budget(route.get("ordered_places", []), state.constraints.get("budget"), state.constraints.get("pace"))
    itinerary = _mixed_itinerary_from_artifacts(state, route)
    errand_items = state.artifacts.get("errand_items") or (_extract_errand_items(state.user_input) if "errand" in task_types else [])
    meal_candidates = state.artifacts.get("meal_candidates") or []
    todo_parse = state.artifacts.get("todo") or (_parse_todo_goal(state.user_input) if "todo" in task_types else {})
    travel_research = state.artifacts.get("travel_research") or getattr(state, "_travel_research", {"provider": "none", "sources": [], "note": "动态计划未调用网页搜索"})
    weather = state.artifacts.get("weather") or getattr(state, "_weather", {})
    actions = state.artifacts.get("confirm_actions") or []
    title_city = _dynamic_city(state) or "本地"
    plan = {
        "task_type": "mixed",
        "title": f"{title_city}综合生活计划",
        "goal": state.intent_contract.get("goal") or state.goal,
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "weather": weather,
        "travel_research": travel_research,
        "itinerary": itinerary,
        "errand_items": errand_items,
        "meal_candidates": meal_candidates,
        "todo_items": todo_parse.get("tasks", []),
        "time_blocks": todo_parse.get("time_blocks", []),
        "acceptance_criteria": todo_parse.get("acceptance_criteria", []),
        "lifestyle_places": state.artifacts.get("lifestyle_places") or getattr(state, "_lifestyle_places", {"foods": meal_candidates, "hotels": []}),
        "route": route.get("legs", []),
        "local_route": route,
        "access_route": route.get("access_route"),
        "budget": budget,
        "confirm_actions": actions,
        "alternatives": _build_alternatives(state.candidates, route.get("ordered_places", [])) if state.candidates else [],
        "recommendation_basis": _recommendation_basis(state, route.get("ordered_places", []), state.candidates) if state.candidates else {},
        "guide_places": _guide_place_candidates(state.artifacts.get("places") or getattr(state, "_places", [])),
        "summary": _mixed_summary(state, task_types, itinerary, budget),
        "intent_contract": state.intent_contract,
        "execution_plan": state.execution_plan,
    }
    return plan


def _mixed_itinerary_from_artifacts(state: AgentState, route: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = route.get("ordered_places") or []
    legs = route.get("legs") or []
    if ordered:
        timeline = []
        current = 9 * 60
        for index, place in enumerate(ordered):
            travel = legs[index].get("minutes", 15) if index < len(legs) else 15
            current += int(travel)
            start = _time_label(current)
            current += int(place.get("duration_minutes") or 45)
            timeline.append({
                "time": f"{start}-{_time_label(current)}",
                "place": place.get("name"),
                "area": place.get("area"),
                "address": place.get("address"),
                "location": place.get("location"),
                "map_url": place.get("map_url"),
                "play_points": place.get("play_points") or ["按顺路顺序执行"],
                "reason": _mixed_item_reason(place),
                "cost": place.get("estimated_cost", 0),
                "cost_known": place.get("cost_known", False),
                "cost_note": place.get("cost_note"),
                "tags": place.get("tags", []),
            })
        return timeline
    if _intent_has(state, "todo"):
        return _timeline_from_todos((state.artifacts.get("todo") or {}).get("tasks", []))
    return []


def _mixed_item_reason(place: dict[str, Any]) -> str:
    tags = set(place.get("tags") or [])
    if "缇庨" in tags or "美食" in tags:
        return "餐饮节点，和其他事项按顺路顺序合并"
    if "璺戣吙" in tags:
        return "跑腿事项，外部动作只记录为待确认"
    return "出行/游玩节点，按地点候选和路线估算纳入"


def _mixed_summary(state: AgentState, task_types: set[str], itinerary: list[dict[str, Any]], budget: dict[str, Any]) -> str:
    city = _dynamic_city(state) or "本地"
    food_tags = {"美食", "火锅", "川菜", "小吃", "茶馆"}
    travel_names = _dedupe_text_parts(
        item.get("place")
        for item in itinerary
        if not set(item.get("tags") or []).intersection(food_tags)
    )
    meal_names = _dedupe_text_parts(
        item.get("name")
        for item in (state.artifacts.get("meal_candidates") or [])
    )
    total = budget.get("total")
    budget_text = f"，预计 {total} 元" if isinstance(total, (int, float)) else ""
    if "travel" in task_types and "meal" in task_types:
        route_text = "、".join(travel_names[:3]) if travel_names else f"{city}核心景点"
        meal_text = "、".join(meal_names[:2]) if meal_names else f"{city}本地餐饮"
        return f"这是一条{city}游玩加用餐路线：先逛{route_text}，再把{meal_text}作为用餐候选{budget_text}；订座、付款和提醒只生成待确认动作。"
    if "errand" in task_types or "todo" in task_types:
        names = _dedupe_text_parts(item.get("place") for item in itinerary)
        task_text = "、".join(names[:3]) if names else "这些事项"
        return f"这是一条{city}综合执行路线：按顺路顺序处理{task_text}{budget_text}；外部动作只生成待确认项。"
    return f"这是一条{city}综合计划，共 {len(itinerary)} 个时间节点{budget_text}；外部动作只生成待确认项。"


def _build_errand_plan(state: AgentState) -> dict[str, Any]:
    items = _extract_errand_items(state.user_input)
    city = state.constraints.get("city") or state.constraints.get("default_city") or "本地"
    candidate_places = _errand_candidate_places(items, getattr(state, "_places", []))
    route_data = estimate_route(candidate_places) if candidate_places else {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    budget = estimate_budget(route_data.get("ordered_places", []), state.constraints.get("budget"), state.constraints.get("pace"))
    itinerary = _timeline_from_errands(items, route_data.get("ordered_places", []), route_data.get("legs", []))
    return {
        "task_type": "errand",
        "title": f"{city}跑腿顺路计划",
        "goal": state.goal or "安排生活跑腿",
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "weather": getattr(state, "_weather", {}),
        "travel_research": getattr(state, "_travel_research", {"sources": []}),
        "errand_items": items,
        "itinerary": itinerary,
        "route": route_data.get("legs", []),
        "local_route": route_data,
        "budget": budget,
        "confirm_actions": _confirm_actions_for("errand", items),
        "summary": "已按取、买、寄、办、送、用餐等事项生成顺路时间轴；具体店铺、营业时间和寄送/支付动作需要你确认后再执行。",
    }


def _build_meal_plan(state: AgentState) -> dict[str, Any]:
    city = state.constraints.get("city") or state.constraints.get("default_city") or "本地"
    lifestyle = getattr(state, "_lifestyle_places", {"foods": [], "hotels": []})
    foods = lifestyle.get("foods") or [
        place for place in getattr(state, "_places", []) if "美食" in place.get("tags", [])
    ]
    meal_candidates = _meal_candidates(foods, state.constraints)
    selected = meal_candidates[:3]
    route_data = estimate_route(selected) if selected else {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    budget = estimate_budget(selected, state.constraints.get("budget"), state.constraints.get("pace"))
    itinerary = _timeline_from_meals(selected, route_data.get("legs", []))
    return {
        "task_type": "meal",
        "title": f"{city}餐饮计划",
        "goal": state.goal or "安排餐饮选择",
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "weather": getattr(state, "_weather", {}),
        "travel_research": getattr(state, "_travel_research", {"sources": []}),
        "meal_candidates": meal_candidates,
        "lifestyle_places": {"foods": meal_candidates, "hotels": lifestyle.get("hotels", [])},
        "itinerary": itinerary,
        "route": route_data.get("legs", []),
        "local_route": route_data,
        "budget": budget,
        "confirm_actions": _confirm_actions_for("meal", meal_candidates[:1]),
        "summary": "已按预算、口味和距离优先给出餐饮候选；订座、排队取号、支付和发送消息都只作为待确认动作。",
    }


def _build_todo_plan(state: AgentState) -> dict[str, Any]:
    parsed = getattr(state, "_todo_parse", _parse_todo_goal(state.user_input))
    tasks = parsed.get("tasks", [])
    return {
        "task_type": "todo",
        "title": "待办拆解计划",
        "goal": parsed.get("goal") or state.goal or "拆解目标",
        "date": state.constraints.get("date_iso") or state.constraints.get("date"),
        "travel_research": {"provider": "none", "sources": [], "note": "todo 场景不调用地图/天气"},
        "itinerary": _timeline_from_todos(tasks),
        "todo_items": tasks,
        "time_blocks": parsed.get("time_blocks", []),
        "acceptance_criteria": parsed.get("acceptance_criteria", []),
        "budget": {"activity_cost": 0, "meal_budget": 0, "transport_budget": 0, "total": 0, "budget_limit": state.constraints.get("budget"), "budget_usage": 0},
        "confirm_actions": _confirm_actions_for("todo", tasks),
        "summary": "已拆成可执行任务、时间块和完成标准；提醒和日历写入只生成待确认动作，不会自动执行。",
    }


def _select_places(candidates: list[dict], constraints: dict, replan_context: dict[str, Any] | None = None) -> list[dict]:
    candidates = _filter_reflection_blocked_places(candidates, replan_context or {})
    budget = constraints.get("budget") or 500
    avoid = set(constraints.get("avoid", []))
    preferences = constraints.get("preferences", [])
    target_count = _target_place_count(constraints, replan_context or {})
    if not preferences:
        return _select_compact_places(candidates, budget, avoid, target_count)
    selected = []
    cost = 150
    for preference in preferences:
        match = next(
            (
                candidate
                for candidate in candidates
                if preference in candidate.get("tags", [])
                and avoid.isdisjoint(candidate.get("tags", []))
                and candidate["name"] not in {item["name"] for item in selected}
                and cost + candidate["estimated_cost"] <= budget
            ),
            None,
        )
        if match and len(selected) < target_count:
            selected.append(match)
            cost += match["estimated_cost"]
    selected_tags = set().union(*(set(item.get("tags", [])) for item in selected)) if selected else set()
    for candidate in candidates:
        if len(selected) >= target_count:
            break
        if candidate["name"] in {item["name"] for item in selected}:
            continue
        if not avoid.isdisjoint(candidate.get("tags", [])):
            continue
        if set(candidate.get("tags", [])).issubset(selected_tags) and len(selected) >= 2:
            continue
        if cost + candidate["estimated_cost"] <= budget:
            selected.append(candidate)
            selected_tags.update(candidate.get("tags", []))
            cost += candidate["estimated_cost"]
    return _improve_budget_fit(selected, candidates, constraints, avoid)


def _filter_reflection_blocked_places(candidates: list[dict], replan_context: dict[str, Any]) -> list[dict]:
    issues = _reflection_issues(replan_context)
    if not issues:
        return candidates
    blocked_text = "\n".join(
        issue for issue in issues if any(word in issue for word in ["暂停开放", "不能安排", "不可安排", "不适合安排"])
    )
    if not blocked_text:
        return candidates
    blocked_names = set()
    for issue in blocked_text.splitlines():
        prefix = re.split(r"[（(]", issue, maxsplit=1)[0].strip()
        prefix = re.sub(r"^(问题|风险|提醒)[:：]\s*", "", prefix).strip()
        if prefix:
            blocked_names.add(prefix)
    return [
        candidate
        for candidate in candidates
        if not any(
            name and (name in str(candidate.get("name", "")) or str(candidate.get("name", "")) in name)
            for name in blocked_names
        )
        and not any(str(candidate.get("name", "")) and str(candidate.get("name", "")) in issue for issue in blocked_text.splitlines())
    ]


def _ensure_place_locations(places: list[dict]) -> list[dict]:
    allow_external_geocode = settings.place_provider != "mock"
    for place in places:
        if place.get("provider") == "city_seed":
            _hydrate_place_from_map_search(place)
        _apply_reference_ticket_price(place)
        if place.get("location"):
            continue
        if not allow_external_geocode:
            continue
        if _is_unconfirmed_task_place(place):
            continue
        query = " ".join(
            str(part)
            for part in [place.get("city"), place.get("name"), place.get("address") or place.get("area")]
            if part
        ).strip()
        if not query:
            continue
        try:
            location = geocode_place(query)
        except Exception:
            continue
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
            place["location"] = f"{longitude},{latitude}"
    return places


def _hydrate_place_from_map_search(place: dict[str, Any]) -> None:
    city = place.get("city")
    name = place.get("name")
    if not city or not name:
        return
    try:
        matches = search_places(str(city), [str(name)], [])
    except Exception:
        return
    match = _best_map_match(str(name), matches)
    if not match:
        return
    for key in ["area", "address", "location", "map_url", "source_url"]:
        if match.get(key):
            place[key] = match[key]
    place["source_title"] = match.get("source_title") or "高德地图地点搜索"
    place["provider"] = "city_seed+amap"
    place["tags"] = list(dict.fromkeys((place.get("tags") or []) + (match.get("tags") or [])))
    if match.get("estimated_cost"):
        place["estimated_cost"] = match["estimated_cost"]
        place["cost_known"] = bool(match.get("cost_known"))
        place["cost_note"] = match.get("cost_note") or place.get("cost_note")


def _best_map_match(place_name: str, matches: list[dict]) -> dict[str, Any] | None:
    filtered = [item for item in matches if _is_relevant_to_place(place_name, item.get("name", ""))]
    if not filtered:
        return None
    bad_words = ["地铁站", "公交站", "大街", "停车场", "售票处", "游客中心"]
    return max(
        filtered,
        key=lambda item: (
            int(bool(item.get("location"))) * 8
            + int(place_name in item.get("name", "")) * 6
            + int(bool(item.get("estimated_cost"))) * 3
            - sum(8 for word in bad_words if word in item.get("name", "")),
        ),
    )


def _apply_reference_ticket_price(place: dict[str, Any]) -> None:
    if int(place.get("estimated_cost") or 0) > 0:
        return
    city = place.get("city")
    name = place.get("name") or ""
    city_prices = REFERENCE_TICKET_PRICES.get(str(city), {})
    for keyword, price in city_prices.items():
        if keyword in name:
            place["estimated_cost"] = price
            place["cost_known"] = False
            place["cost_note"] = f"常见门票参考约 {price} 元，出发前以官方购票页为准"
            return


def _is_unconfirmed_task_place(place: dict[str, Any]) -> bool:
    text = " ".join(str(place.get(key, "")) for key in ["name", "area", "address", "cost_note"])
    return "待确认" in text or "璺戣吙" in set(place.get("tags") or [])


def _select_compact_places(candidates: list[dict], budget: int, avoid: set[str], target_count: int = 3) -> list[dict]:
    usable = [
        candidate
        for candidate in candidates
        if avoid.isdisjoint(candidate.get("tags", [])) and 150 + candidate["estimated_cost"] <= budget
    ]
    usable = sorted(usable, key=_travel_priority, reverse=True)
    if len(usable) <= target_count:
        return usable
    anchor = usable[0]
    selected = [anchor]
    cost = 150 + anchor["estimated_cost"]
    for candidate in sorted(usable[1:], key=lambda item: (_similarity_penalty(selected, item), -_selection_quality(item), _distance_between(anchor, item), -item.get("score", 0))):
        if len(selected) >= target_count:
            break
        if cost + candidate["estimated_cost"] > budget:
            continue
        if _is_too_similar(selected, candidate):
            continue
        if _exceeds_default_city_mix(selected, candidate, target_count):
            continue
        selected.append(candidate)
        cost += candidate["estimated_cost"]
    for candidate in usable:
        if len(selected) >= target_count:
            break
        if candidate["name"] in {item["name"] for item in selected}:
            continue
        if _exceeds_default_city_mix(selected, candidate, target_count):
            continue
        if cost + candidate["estimated_cost"] <= budget:
            selected.append(candidate)
            cost += candidate["estimated_cost"]
    if len(selected) < min(2, target_count):
        for candidate in usable:
            if len(selected) >= min(2, target_count):
                break
            if candidate["name"] in {item["name"] for item in selected}:
                continue
            if cost + candidate["estimated_cost"] <= budget:
                selected.append(candidate)
                cost += candidate["estimated_cost"]
    return selected


def _selection_quality(item: dict[str, Any]) -> int:
    return (
        int(item.get("goal_match_score", 0) or 0) * 2
        + int(item.get("web_match_score", 0) or 0) * 2
        + int(item.get("popularity_score", 0) or 0)
        + int(item.get("event_score", 0) or 0)
        + len(item.get("evidence") or []) * 6
    )


def _exceeds_default_city_mix(selected: list[dict], candidate: dict, target_count: int) -> bool:
    category = _place_mix_category(candidate)
    if category not in {"museum", "park"}:
        return False
    current_limited = sum(1 for item in selected if _place_mix_category(item) in {"museum", "park"})
    limited_cap = 2 if target_count >= 5 else 1
    return current_limited >= limited_cap


def _place_mix_category(place: dict[str, Any]) -> str:
    name = str(place.get("name") or place.get("place") or "")
    tags = set(place.get("tags") or [])
    if "博物馆" in name or "美术馆" in name or tags.intersection({"博物馆", "展览"}):
        return "museum"
    if any(word in name for word in ["公园", "湿地", "广场"]):
        return "park"
    if any(word in name for word in ["山", "风景区", "索道"]) or tags.intersection({"爬山", "徒步", "登山", "运动"}):
        return "mountain"
    if any(word in name for word in ["花市", "市场", "夜市", "街", "巷", "古镇", "水街"]):
        return "street_market"
    if any(word in name for word in ["楼", "塔", "坊", "祠", "寺", "故居", "城墙"]):
        return "culture_view"
    if any(word in name for word in ["湖", "池", "江", "河", "海", "岛", "湾"]):
        return "waterfront"
    return "other"


def _target_place_count(constraints: dict, replan_context: dict[str, Any]) -> int:
    explicit_preferences = constraints.get("preferences") or []
    preference_count = len(set(explicit_preferences))
    trip_days = constraints.get("trip_days")
    if isinstance(trip_days, int) and trip_days >= 2:
        return max(4, min(6, trip_days * 2 + 1, max(4, preference_count + 2)))
    issues = " ".join(
        str(replan_context.get(key, ""))
        for key in ["review", "issues", "next_action"]
    )
    if any(word in issues for word in ["一天", "一日", "第二天", "覆盖不足", "过短", "太少"]):
        return max(5, preference_count)
    return max(3, preference_count)


def _travel_priority(candidate: dict) -> tuple[int, int, int, int, int, int, int]:
    goal_bonus = int(candidate.get("goal_match_score", 0) or 0)
    event_bonus = int(candidate.get("event_score", 0) or 0)
    web_bonus = int(candidate.get("web_match_score", 0) or 0)
    iconic_bonus = 1 if _is_iconic_place(candidate) else 0
    popularity_bonus = int(candidate.get("popularity_score", 0) or 0)
    evidence_bonus = len(candidate.get("evidence") or [])
    return goal_bonus, event_bonus, web_bonus, iconic_bonus, popularity_bonus, evidence_bonus, int(candidate.get("score", 0))


def _is_too_similar(selected: list[dict], candidate: dict) -> bool:
    if not selected:
        return False
    if candidate.get("provider") == "destination":
        return False
    candidate_tags = set(candidate.get("tags", []))
    for item in selected:
        if item.get("provider") == "destination":
            continue
        same_area = item.get("area") == candidate.get("area")
        overlap_tags = set(item.get("tags", [])).intersection(candidate_tags)
        specific_overlap = overlap_tags - {"散步", "室外", "室内", "景点"}
        if len(overlap_tags.intersection({"展览", "博物馆"})) >= 2:
            return True
        if same_area and (specific_overlap or len(overlap_tags) >= 3):
            return True
    return False


def _similarity_penalty(selected: list[dict], candidate: dict) -> int:
    return 1 if _is_too_similar(selected, candidate) else 0


def _improve_budget_fit(selected: list[dict], candidates: list[dict], constraints: dict, avoid: set[str]) -> list[dict]:
    budget = constraints.get("budget")
    if not budget or budget < 300 or len(selected) >= 4:
        return selected
    target_activity = max(0, int(budget * 0.35))
    current = sum(int(item.get("estimated_cost", 0)) for item in selected)
    requested = set(constraints.get("preferences") or [])
    covered = set().union(*(set(item.get("tags", [])) for item in selected)) if selected else set()
    if requested and requested.issubset(covered):
        return selected
    if current >= target_activity * 0.6:
        return selected
    selected_names = {item["name"] for item in selected}
    paid_candidates = [
        item
        for item in candidates
        if item["name"] not in selected_names
        and int(item.get("estimated_cost", 0)) > 0
        and avoid.isdisjoint(item.get("tags", []))
    ]
    if not paid_candidates:
        return selected
    replacement = max(paid_candidates, key=lambda item: (item.get("score", 0), item.get("estimated_cost", 0)))
    if len(selected) < 3:
        return selected + [replacement]
    replaceable_indexes = [
        index
        for index, item in enumerate(selected)
        if not _uniquely_covers_preference(item, selected, requested)
    ]
    if not replaceable_indexes:
        return selected
    cheapest_index = min(replaceable_indexes, key=lambda index: int(selected[index].get("estimated_cost", 0)))
    improved = selected[:]
    improved[cheapest_index] = replacement
    return improved


def _uniquely_covers_preference(item: dict, selected: list[dict], requested: set[str]) -> bool:
    item_matches = requested.intersection(item.get("tags", []))
    if not item_matches:
        return False
    for preference in item_matches:
        other_matches = [
            other for other in selected
            if other is not item and preference in other.get("tags", [])
        ]
        if not other_matches:
            return True
    return False


def _coverage_issue(state: AgentState) -> str | None:
    if state.constraints.get("task_type") in {"errand", "meal", "todo"}:
        return None
    requested = set(state.constraints.get("preferences", []))
    if not requested or not state.final_plan:
        return None
    covered = set()
    for item in state.final_plan.get("itinerary", []):
        covered.update(item.get("tags", []))
    missing = requested - covered
    if missing:
        return "计划未覆盖偏好：" + "、".join(sorted(missing))
    return None


def _destination_issue(state: AgentState) -> str | None:
    if state.constraints.get("task_type") in {"errand", "meal", "todo"}:
        return None
    validation = (state.final_plan or {}).get("destination_validation") or _validate_destination_plan(
        state,
        (state.final_plan or {}).get("itinerary") or [],
    )
    if validation.get("passed") is False:
        return validation.get("reason") or "计划目的地与用户目标不符"
    if state.constraints.get("route_scope") == "cross_city_trip":
        access_route = (state.final_plan or {}).get("access_route") or {}
        if not access_route.get("needed"):
            return "缺少从出发地到目的地的到达路线"
    return None


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


def _validate_destination_plan(state: AgentState, itinerary: list[dict]) -> dict[str, Any]:
    destination = state.constraints.get("destination") or {}
    destination_name = destination.get("name") or state.constraints.get("destination_place")
    if not destination_name:
        return {"passed": True, "matched": []}
    if destination.get("type") == "city":
        city = destination.get("city") or destination_name
        if city in {state.constraints.get("city"), state.constraints.get("destination_city")} and itinerary:
            matched = [item.get("place") for item in itinerary if item.get("place") and not _is_city_name(str(item.get("place")), str(city))]
            if matched:
                return {"passed": True, "matched": list(dict.fromkeys(matched))}
    aliases = _place_aliases(destination_name)
    if destination.get("raw"):
        aliases.extend(_place_aliases(str(destination["raw"])))
    if destination.get("city"):
        aliases.append(str(destination["city"]))
    matched = []
    for item in itinerary:
        text = " ".join(str(item.get(key, "")) for key in ["place", "area", "address"])
        if any(alias and alias in text for alias in aliases):
            matched.append(item.get("place"))
    if matched:
        return {"passed": True, "matched": list(dict.fromkeys(matched))}
    return {
        "passed": False,
        "matched": [],
        "reason": f"计划目的地与用户目标不符：用户想去{destination_name}，但行程没有安排该目的地或其周边点位",
    }


def _is_city_name(name: str, city: str) -> bool:
    normalize = lambda value: value.replace("市", "").strip()
    return bool(name and city and normalize(name) == normalize(city))


def _issue_requires_replan(issue: str) -> bool:
    return any(word in issue for word in [
        "intent_missing_subtask",
        "intent_output_mismatch",
        "intent_hard_constraint_conflict",
        "目的地与用户目标不符",
        "缺少从出发地到目的地",
        "没有安排该目的地",
    ])


def _covered_preferences(selected: list[dict], preferences: list[str]) -> set[str]:
    covered = set()
    requested = set(preferences)
    for place in selected:
        covered.update(requested.intersection(place.get("tags", [])))
    return covered


def _build_alternatives(candidates: list[dict], selected: list[dict]) -> list[dict]:
    selected_names = {item["name"] for item in selected}
    alternatives = []
    category_counts: dict[str, int] = {}
    for candidate in candidates:
        if candidate["name"] in selected_names:
            continue
        category = _place_mix_category(candidate)
        if category in {"museum", "park"} and category_counts.get(category, 0) >= 1:
            continue
        if category_counts.get(category, 0) >= 2:
            continue
        alternatives.append({
            "name": candidate["name"],
            "address": candidate.get("address"),
            "map_url": candidate.get("map_url"),
            "play_points": candidate.get("play_points", []),
            "tags": candidate.get("tags", []),
            "evidence": candidate.get("evidence", []),
        })
        category_counts[category] = category_counts.get(category, 0) + 1
        if len(alternatives) >= 6:
            break
    return alternatives


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


def _filter_travel_places(places: list[dict], preferences: list[str] | None = None) -> list[dict]:
    requested = set(preferences or [])
    travel_places = []
    for place in places:
        if _is_city_placeholder_place(place):
            continue
        tags = set(place.get("tags", []))
        if tags.intersection({"酒店", "住宿", "閰掑簵", "浣忓"}):
            continue
        if tags.intersection({"美食", "缇庨"}) and not requested.intersection(tags):
            continue
        travel_places.append(place)
    return travel_places


def _ensure_city_trip_places(places: list[dict], state: AgentState, city: str | None) -> list[dict]:
    if not city:
        return places
    destination = state.constraints.get("destination") or {}
    is_city_trip = (
        state.constraints.get("route_scope") == "city_trip"
        or destination.get("type") in {"city", "district"}
        or (state.constraints.get("city") and not destination)
    )
    if not is_city_trip:
        return places
    travel_count = _city_trip_travel_count(places, state)
    if travel_count >= 3:
        return places
    live_places = _search_city_trip_places(city, state)
    if live_places:
        places = _dedupe_places(places + live_places)
        travel_count = _city_trip_travel_count(places, state)
    if travel_count >= 3 and not _broad_city_places_need_seed(places, state):
        return places
    seed_places = _city_seed_places(
        city,
        state.constraints.get("preferences") or [],
        state.constraints.get("activity_intent"),
    )
    if seed_places:
        return _dedupe_places(places + seed_places)
    return _dedupe_places(places + _generic_city_search_places(city, state.constraints.get("activity_intent")))


def _broad_city_places_need_seed(places: list[dict], state: AgentState) -> bool:
    if not _is_broad_city_sightseeing_request(state):
        return False
    travel_places = _filter_travel_places(places, state.constraints.get("preferences", []))
    if len(travel_places) < 4:
        return True
    return not any(_is_iconic_place(place) for place in travel_places)


def _city_trip_travel_count(places: list[dict], state: AgentState) -> int:
    food_tags = {"美食", "火锅", "川菜", "小吃", "茶馆"}
    return len([
        place for place in _filter_travel_places(places, state.constraints.get("preferences", []))
        if not set(place.get("tags") or []).intersection(food_tags)
    ])


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


def _is_city_placeholder_place(place: dict[str, Any]) -> bool:
    name = str(place.get("name") or "").strip()
    city = str(place.get("city") or "").strip()
    if not name or not city:
        return False
    return _is_city_name(name, city)


def _is_broad_city_sightseeing_request(state: AgentState) -> bool:
    destination = state.constraints.get("destination") or {}
    if destination.get("type") not in {"city", "district"} and not (state.constraints.get("city") and not destination):
        return False
    if _travel_preferences(state.constraints.get("preferences") or []):
        return False
    text = f"{state.user_input} {state.goal or ''}"
    return any(word in text for word in ["旅游", "景点", "推荐", "攻略", "好玩", "打卡"])


def _estimate_access_route_if_needed(state: AgentState) -> dict[str, Any]:
    origin = state.constraints.get("origin") or {}
    destination = state.constraints.get("destination") or {}
    if not origin or not destination:
        return estimate_access_route(origin or None, destination or None)
    origin_city = origin.get("city")
    destination_city = destination.get("city")
    origin_name = origin.get("name") or origin.get("raw")
    destination_name = destination.get("name") or destination.get("raw")
    same_city = origin_city and destination_city and origin_city == destination_city and not origin.get("location")
    same_place = origin_name and destination_name and origin_name == destination_name
    default_same_city = origin.get("source") == "default_city" and origin_city and origin_city in {destination_city, destination_name}
    if state.constraints.get("route_scope") != "cross_city_trip" or same_city or same_place or default_same_city:
        city = destination_city or origin_city or destination_name or origin_name or state.constraints.get("city")
        return {
            "needed": False,
            "from": origin_name,
            "to": destination_name,
            "provider": "same_city",
            "summary": f"{city}市内活动，无需生成跨城到达路线" if city else "市内活动，无需生成跨城到达路线",
            "mode": "local",
            "steps": [],
            "warnings": [],
        }
    return estimate_access_route(origin, destination)


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


def _is_travel_guide_plan(plan: dict[str, Any]) -> bool:
    return plan.get("task_type") in {"travel", "mixed"} and bool(plan.get("itinerary") or plan.get("meal_candidates"))


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


def _guide_city(plan: dict[str, Any]) -> str:
    title = str(plan.get("title") or "目的地")
    for suffix in ["综合生活计划", "轻松一日计划", "一日计划", "餐饮计划", "计划"]:
        if title.endswith(suffix):
            title = title[: -len(suffix)]
    return title or "目的地"


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


def _guide_place_key(name: str) -> str:
    return re.split(r"[-·（(]", name, maxsplit=1)[0].strip() or name


def _guide_meals(meals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    local_meals = [item for item in meals if not _is_national_chain_meal(item)]
    return local_meals if len(local_meals) >= 3 else meals


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
    name = item.get("name") or "餐饮候选"
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


def _access_route_message(access_route: dict[str, Any]) -> str:
    lines = [f"**怎么到达**：{access_route.get('summary') or '到达路线需出发前确认'}"]
    steps = access_route.get("steps") or []
    if steps:
        lines.append("；".join(str(step) for step in steps[:3]))
    warnings = access_route.get("warnings") or []
    if warnings:
        lines.append("提醒：" + "；".join(str(item) for item in warnings[:2]))
    return " ".join(lines)


def _weather_advice(weather: dict[str, Any]) -> str:
    risk = weather.get("outdoor_risk")
    condition = weather.get("condition", "")
    if risk == "medium" or any(word in condition for word in ["雨", "雪", "雾"]):
        return "室外体验可能受影响，路线里要保留室内/可撤退选项。"
    return "整体适合户外走动，但仍建议带水、防晒或薄外套。"


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


def _cost_text(item: dict[str, Any]) -> str:
    cost = int(item.get("cost", 0) or 0)
    if cost > 0:
        return f"约 {cost} 元，{item.get('cost_note', '实际以官方/现场为准')}"
    if item.get("cost_known"):
        return item.get("cost_note") or "免费/0 元，实际以官方/现场为准"
    return item.get("cost_note") or "未确认票价，暂不计入活动费"


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


def _linked_named_item(item: dict[str, Any]) -> str:
    name = item.get("name") or "地点"
    url = item.get("map_url")
    return f"[{name}]({url})" if url else name


def _log(state: AgentState, node: str, summary: str, details: Any) -> None:
    state.execution_log.append({"node": node, "summary": summary, "details": details})


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


def _first_match(text: str, words: list[str]) -> str | None:
    return next((word for word in words if word in text), None)


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


def _extract_pace(text: str) -> str | None:
    if any(word in text for word in ["不想太轻松", "不要太轻松", "别太轻松", "运动量多", "多走路"]):
        return "中等"
    if any(word in text for word in ["紧凑", "多安排", "多玩几个", "特种兵"]):
        return "紧凑"
    if any(word in text for word in ["轻松", "不想太累", "别太赶"]):
        return "轻松"
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


def _infer_task_type(text: str, llm_constraints: dict[str, Any], context: dict[str, Any]) -> str:
    if any(word in text.lower() for word in ["todo", "to-do"]) or any(word in text for word in ["待办", "拆解", "拆成", "任务列表", "完成标准", "里程碑", "时间块"]):
        return "todo"
    if any(word in text for word in ["取快递", "拿快递", "寄快递", "寄件", "办事", "办理", "跑腿", "顺路", "送到", "送去", "买药", "买菜", "买礼物"]):
        return "errand"
    if _looks_like_travel_request(text):
        return "travel"
    if _has_meal_intent(text):
        return "meal"
    if context.get("task_type") and any(word in text for word in ["太贵", "换", "改", "控制在", "轻松点", "重排"]):
        task_type = str(context.get("task_type"))
        return task_type if task_type in {"travel", "errand", "meal", "todo"} else "unknown"
    llm_type = str(llm_constraints.get("task_type") or "").strip()
    mapping = {
        "travel_plan": "travel",
        "errands": "errand",
        "meal_plan": "meal",
        "todo": "todo",
        "replan": "replan",
    }
    if llm_type in mapping:
        return mapping[llm_type]
    if llm_type in TASK_TYPES:
        return llm_type
    return "unknown"


def _is_explicit_task_switch(text: str) -> bool:
    switch_words = ["改成", "改为", "变成", "换成"]
    has_target = _has_todo_intent(text) or _has_errand_intent(text) or _has_meal_intent(text) or _looks_like_travel_request(text)
    return has_target and any(word in text for word in switch_words)


def _has_todo_intent(text: str) -> bool:
    return any(word in text.lower() for word in ["todo", "to-do"]) or any(word in text for word in ["待办", "拆解", "拆成", "任务列表", "完成标准", "里程碑", "时间块"])


def _has_errand_intent(text: str) -> bool:
    return any(word in text for word in ["取快递", "拿快递", "寄快递", "寄件", "办事", "办理", "跑腿", "顺路", "送到", "送去", "买药", "买菜", "买礼物"])


def _has_meal_intent(text: str) -> bool:
    return any(word in text for word in MEAL_INTENT_WORDS)


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


def _errand_candidate_places(items: list[dict[str, Any]], places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, item in enumerate(items):
        match = _match_place_for_errand(item, places)
        result.append(_normalize_task_place(match, item["title"], item.get("duration_minutes", 35), index))
    return result


def _match_place_for_errand(item: dict[str, Any], places: list[dict[str, Any]]) -> dict[str, Any] | None:
    action = item.get("action")
    wanted_tags = {
        "买": {"美食", "书店", "室内"},
        "吃饭": {"美食"},
    }.get(action, set())
    if not wanted_tags:
        return None
    return next((place for place in places if wanted_tags.intersection(place.get("tags", []))), None)


def _normalize_task_place(place: dict[str, Any] | None, title: str, duration: int, index: int) -> dict[str, Any]:
    if place:
        result = dict(place)
    else:
        result = {
            "name": title,
            "area": "地点待确认",
            "address": "地点待确认",
            "tags": ["跑腿"],
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "具体费用待确认",
            "play_points": ["先确认地址、营业时间和是否需要预约/排队"],
        }
    result.setdefault("area", result.get("address") or "地点待确认")
    result.setdefault("address", result.get("area") or "地点待确认")
    result.setdefault("tags", ["跑腿"])
    result.setdefault("estimated_cost", 0)
    result.setdefault("cost_known", False)
    result.setdefault("cost_note", "具体费用待确认")
    result["duration_minutes"] = int(result.get("duration_minutes") or duration)
    result["source_order"] = index
    return result


def _meal_candidates(foods: list[dict[str, Any]], constraints: dict[str, Any]) -> list[dict[str, Any]]:
    budget = constraints.get("budget")
    city = constraints.get("city") or constraints.get("destination_city") or constraints.get("default_city")
    result = []
    for index, food in enumerate(foods[:12]):
        item = _normalize_task_place(food, food.get("name") or "餐饮候选", int(food.get("duration_minutes") or 75), index)
        item["tags"] = list(dict.fromkeys((item.get("tags") or []) + ["美食"]))
        item["reason"] = _meal_reason(item, budget)
        result.append(item)
    return sorted(result, key=lambda item: _meal_priority(item, str(city or "")), reverse=True)[:8]


def _meal_reason(item: dict[str, Any], budget: int | None) -> str:
    if _is_national_chain_meal(item):
        return "标准连锁火锅候选，稳定但不作为本地特色优先推荐"
    if _meal_local_score(item) >= 6:
        return "更贴近本地火锅/特色餐饮体验，适合作为优先候选"
    price = int(item.get("estimated_cost") or 0)
    if budget and price and price <= max(80, budget * 0.5):
        return "预算内优先候选，适合作为本次正餐"
    return "餐饮地点候选，价格/排队需要出发前确认"


def _meal_priority(item: dict[str, Any], city: str) -> tuple[int, int, int, int]:
    text = _meal_text(item)
    tags = set(item.get("tags") or [])
    score = _meal_local_score(item)
    if city and city in text:
        score += 4
    if "火锅" in text or "火锅" in tags:
        score += 8
    if "美食" in tags:
        score += 2
    score -= sum(14 for word in NATIONAL_CHAIN_MEAL_WORDS if word in text)
    return score, int(bool(item.get("location"))), -int(item.get("estimated_cost") or 0), -int(item.get("source_order") or 0)


def _meal_local_score(item: dict[str, Any]) -> int:
    text = str(item.get("name") or "")
    score = 0
    for word in ["老火锅", "庭院", "社区", "茶壶", "鲜货", "鲜鱼", "美蛙", "老街坊", "苏家大院", "聚乐城", "淑华", "辣妹子", "369"]:
        if word in text:
            score += 6
    return score


def _is_national_chain_meal(item: dict[str, Any]) -> bool:
    text = _meal_text(item)
    return any(word in text for word in NATIONAL_CHAIN_MEAL_WORDS)


def _meal_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key, "")) for key in ["name", "area", "address"])


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


def _timeline_from_errands(items: list[dict[str, Any]], places: list[dict[str, Any]], legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = 9 * 60
    timeline = []
    for index, item in enumerate(items):
        travel = legs[index].get("minutes", 15) if index < len(legs) else 15
        current += int(travel)
        start = _time_label(current)
        current += int(item.get("duration_minutes") or 35)
        place = places[index] if index < len(places) else {}
        timeline.append({
            "time": f"{start}-{_time_label(current)}",
            "place": place.get("name") or item["title"],
            "area": place.get("area"),
            "address": place.get("address") or item.get("location_status"),
            "map_url": place.get("map_url"),
            "play_points": [item.get("success_criteria", "完成该事项")],
            "reason": "顺路执行，外部动作先等待确认",
            "cost": place.get("estimated_cost", 0),
            "cost_known": place.get("cost_known", False),
            "cost_note": place.get("cost_note", "费用待确认"),
        })
    return timeline


def _timeline_from_meals(places: list[dict[str, Any]], legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = 11 * 60 + 30
    timeline = []
    for index, place in enumerate(places):
        if index:
            current += int(legs[index].get("minutes", 15) if index < len(legs) else 15)
        start = _time_label(current)
        current += int(place.get("duration_minutes") or 75)
        timeline.append({
            "time": f"{start}-{_time_label(current)}",
            "place": place.get("name"),
            "area": place.get("area"),
            "address": place.get("address"),
            "map_url": place.get("map_url"),
            "play_points": place.get("play_points") or ["按预算、口味和距离作为餐饮候选"],
            "reason": place.get("reason"),
            "cost": place.get("estimated_cost", 0),
            "cost_known": place.get("cost_known", False),
            "cost_note": place.get("cost_note", "价格待确认"),
        })
    return timeline


def _timeline_from_todos(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "time": block["time"],
            "place": block["title"],
            "address": "无需地点",
            "play_points": [tasks[index].get("success_criteria", "完成该任务")],
            "cost": 0,
            "cost_known": True,
            "cost_note": "无地点/交通费用",
        }
        for index, block in enumerate(_todo_time_blocks(tasks))
    ]


def _confirm_actions_for(task_type: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if task_type == "todo":
        return [{"type": "calendar_or_reminder", "status": "requires_user_confirmation", "label": "是否写入日历/提醒", "items": [item.get("title") for item in items]}]
    if task_type == "meal":
        return [{"type": "reservation_or_message", "status": "requires_user_confirmation", "label": "是否订座、取号或发送聚餐消息", "items": [item.get("name") for item in items if item.get("name")]}]
    return [{"type": "external_side_effect", "status": "requires_user_confirmation", "label": "是否发送消息、支付、下单、预约或写入提醒", "items": [item.get("title") or item.get("name") for item in items]}]


def _plan_has_executable_items(plan: dict[str, Any]) -> bool:
    return bool(plan.get("itinerary") or plan.get("todo_items") or plan.get("meal_candidates") or plan.get("errand_items"))


def _uses_fallback_places(plan: dict[str, Any]) -> bool:
    for place in (plan.get("local_route") or {}).get("ordered_places") or []:
        if place.get("provider") in {"city_seed", "city_fallback"}:
            return True
    for item in plan.get("itinerary") or []:
        if item.get("provider") in {"city_seed", "city_fallback"}:
            return True
    return False


def _is_negated(text: str, word: str) -> bool:
    index = text.find(word)
    if index < 0:
        return False
    prefix = text[max(0, index - 4):index]
    return any(negation in prefix for negation in NEGATION_WORDS)


def _remove_avoided_preferences(preferences: list[str], avoid: list[str]) -> list[str]:
    avoid_set = set(avoid)
    return [item for item in preferences if item not in avoid_set]


def _infer_goal(text: str, city: str | None) -> str:
    destination = _extract_famous_destination(text)
    if destination:
        return f"规划{destination['place']}游玩路线"
    if any(word in text for word in ["玩", "一天", "周末"]):
        return f"规划{city or '目标城市'}生活出行"
    if any(word in text for word in ["取快递", "买", "办事", "跑腿"]):
        return "安排生活跑腿"
    return "规划生活任务"


def _infer_goal_from_roles(text: str, city: str | None, roles: dict[str, Any]) -> str:
    destination = roles.get("destination") or {}
    if destination.get("name"):
        return f"规划{destination['name']}游玩路线"
    return _infer_goal(text, city)


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


def _clean_place_text(value: str) -> str:
    value = re.split(r"[，。,；;？?\s]", value, maxsplit=1)[0]
    value = re.sub(r"^(爬|游|逛|去|到|前往)", "", value)
    value = re.sub(r"(玩)?[一二两三四五六七八九十\d]+天$", "", value)
    value = re.sub(r"[一二两三四五六七八九十\d]+日游$", "", value)
    value = re.sub(r"(出发|旅游|旅行|游玩|爬山|登山|徒步|看展|展览|玩|路线|推荐|计划)$", "", value)
    return value.strip("的了 ")


def _is_origin_phrase(value: str) -> bool:
    return any(word in value for word in ["当前位置", "现在这个地方", "我这里", "从这里", "从我这"])


def _is_broad_region_hint(value: str) -> bool:
    return value in PROVINCE_HINTS


def _mentions_current_area(text: str) -> bool:
    return any(word in text for word in ["附近", "周边", "当前位置", "我这里", "从这里", "现在这个地方"])


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


def _city_in_text(text: str) -> str | None:
    return next((city for city in KNOWN_CITIES if city in text), None)


def _safe_geocode_location(query: str) -> str | None:
    try:
        result = geocode_place(query)
    except Exception:
        return None
    lat = result.get("latitude")
    lon = result.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"{lon},{lat}"
    return None


def _activity_intent(text: str) -> str | None:
    for word in ["爬山", "徒步", "看展", "展览", "散步", "夜景", "咖啡", "美食"]:
        if word in text:
            return word
    if "爬" in text:
        return "爬山"
    return None


def _route_scope(origin: dict[str, Any] | None, destination: dict[str, Any] | None, activity_area: dict[str, Any] | None) -> str:
    if destination and origin and (origin.get("city") != destination.get("city") or origin.get("location")):
        return "cross_city_trip"
    if destination and destination.get("type") in {"poi", "scenic_area"}:
        return "poi_trip"
    return "city_trip" if destination or activity_area else "unknown"


def _extract_famous_destination(text: str) -> dict[str, Any] | None:
    for keyword, destination in FAMOUS_DESTINATIONS.items():
        if keyword in text:
            return destination
    return None


def _extract_current_location(text: str) -> str | None:
    match = re.search(r"当前位置坐标[:：]\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    lon = float(match.group(1))
    lat = float(match.group(2))
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        return f"{lon},{lat}"
    return None


def _prepend_destination_places(places: list[dict], state: AgentState) -> list[dict]:
    destination_obj = state.constraints.get("destination") or {}
    destination_place = state.constraints.get("destination_place") or destination_obj.get("name")
    if not destination_place:
        return places
    destination = next(
        (item for item in FAMOUS_DESTINATIONS.values() if item.get("place") == destination_place),
        None,
    )
    if not destination:
        if destination_obj.get("type") == "city":
            return places
        city = destination_obj.get("city") or state.constraints.get("destination_city") or state.constraints.get("city")
        anchor = {
            "name": destination_place,
            "city": city,
            "area": destination_place,
            "address": destination_obj.get("address") or destination_place,
            "tags": _destination_tags(destination_obj, state.constraints.get("activity_intent")),
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "目的地门票/交通费用需以官方平台为准，暂不计入活动费",
            "duration_minutes": 120,
            "intensity": "中",
            "map_url": f"https://ditu.amap.com/search?query={quote(' '.join(str(part) for part in [city, destination_place] if part))}",
            "source_url": f"https://ditu.amap.com/search?query={quote(' '.join(str(part) for part in [city, destination_place] if part))}",
            "source_title": "目的地识别",
            "play_points": ["围绕用户指定目的地安排，避免误用出发地附近景点"],
            "location": destination_obj.get("location"),
            "provider": "destination",
            "source_order": 0,
            "popularity_score": 24,
        }
        return _dedupe_places([anchor] + places)
    anchors = []
    for index, item in enumerate(destination.get("places", [])):
        anchors.append({
            "name": item["name"],
            "city": destination["city"],
            "area": item.get("area") or destination_place,
            "address": item.get("address") or destination_place,
            "tags": item.get("tags") or destination["tags"],
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "景区门票/索道/换乘费用需以官方预约平台为准，暂不计入活动费",
            "duration_minutes": item.get("duration_minutes", 90),
            "intensity": item.get("intensity", "中"),
            "map_url": f"https://ditu.amap.com/search?query={destination['city']}%20{item['name']}",
            "source_url": f"https://ditu.amap.com/search?query={destination['city']}%20{item['name']}",
            "source_title": "目的地景区识别",
            "play_points": item.get("play_points", []),
            "location": item.get("location"),
            "provider": "destination",
            "source_order": index,
            "popularity_score": 30,
        })
    return _dedupe_places(anchors + places)


def _destination_tags(destination: dict[str, Any], activity_intent: str | None) -> list[str]:
    tags = {"景点"}
    text = f"{destination.get('name', '')} {destination.get('raw', '')} {activity_intent or ''}"
    if any(word in text for word in ["山", "爬", "徒步", "登山"]):
        tags.update(["爬山", "徒步", "运动", "室外"])
    if any(word in text for word in ["展", "馆", "博物馆", "美术馆"]):
        tags.update(["展览", "室内"])
    if "散步" in text:
        tags.update(["散步", "室外"])
    return list(tags)


def _dedupe_places(places: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for place in places:
        name = place.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(place)
    return result


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


def _is_encyclopedia_host(host: str) -> bool:
    return any(domain in host for domain in ["wikipedia.org", "baike.baidu.com", "baike.sogou.com", "baike.so.com"])


def _text_has_travel_content_signal(text: str) -> bool:
    return any(word in text for word in [
        "景点", "旅游", "攻略", "游玩", "一日游", "两日游", "三日游", "必去", "必打卡", "路线",
        "门票", "开放时间", "预约", "交通", "美食", "住宿", "打卡", "榜单", "推荐",
    ])


def _text_has_attraction_or_guide_signal(text: str) -> bool:
    return any(word in text for word in ["景点", "攻略", "游玩", "路线", "门票", "开放时间", "预约", "必去", "打卡"])


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


def _enrich_places_with_search_evidence(places: list[dict], search_data: dict[str, Any]) -> list[dict]:
    results = search_data.get("results") or []
    for place in places:
        evidence = []
        match_count = 0
        popularity_score = max(int(place.get("popularity_score", 0) or 0), _local_popularity_score(place))
        event_score = 0
        for result in results:
            title = result.get("name") or result.get("title") or ""
            snippet = result.get("summary") or result.get("snippet") or ""
            text = f"{title} {snippet}"
            if not _is_relevant_to_place(place["name"], text):
                continue
            match_count += 1
            if title:
                evidence.append(title)
            popularity_score += 6
            if _text_has_recent_activity_signal(text):
                event_score += 1
            price = _extract_ticket_price(text)
            if price is not None:
                place["estimated_cost"] = price
                place["cost_known"] = True
                place["cost_note"] = (
                    "网页搜索结果显示免费/免门票，实际以官方/现场为准"
                    if price == 0
                    else f"从网页搜索结果识别到约 {price} 元，实际以官方/现场为准"
                )
                break
        if evidence:
            place["evidence"] = list(dict.fromkeys(evidence))[:3]
        else:
            place.setdefault("evidence", [])
            place.setdefault("cost_known", False)
            place.setdefault("cost_note", "未从搜索/地图数据确认票价，活动费暂不计入")
        place["popularity_score"] = min(popularity_score, 30)
        place["event_score"] = min(event_score, 3)
        place["web_match_score"] = min(match_count * 8, 32)
    return places


def _is_relevant_to_place(place_name: str, text: str) -> bool:
    compact_name = re.sub(r"[·\-（）()]", "", place_name)
    compact_text = re.sub(r"[·\-（）()]", "", text)
    if compact_name and compact_name in compact_text:
        return True
    keywords = _place_aliases(place_name)
    return any(keyword in compact_text for keyword in keywords)


def _annotate_places_for_goal(places: list[dict], state: AgentState) -> list[dict]:
    preferences = set(state.constraints.get("preferences") or [])
    goal_text = f"{state.goal or ''} {state.user_input}"
    active_requested = bool(preferences.intersection({"爬山", "徒步", "登山", "运动"})) or any(
        word in goal_text for word in ["爬山", "徒步", "登山", "运动量", "多走路"]
    )
    for place in places:
        tags = set(place.get("tags", []))
        score = 0
        if preferences.intersection(tags):
            score += min(14, len(preferences.intersection(tags)) * 7)
        if active_requested and tags.intersection({"爬山", "徒步", "登山", "运动"}):
            score += 10
        if _is_iconic_place(place):
            score += 6
        if place.get("event_score"):
            score += 4
        place["goal_match_score"] = score
    return places


def _text_has_recent_activity_signal(text: str) -> bool:
    return any(word in text for word in RECENT_ACTIVITY_WORDS)


def _place_aliases(place_name: str) -> list[str]:
    aliases = [part for part in re.split(r"[·\-（）()]", place_name) if len(part) >= 2]
    for keyword in _all_popular_keywords():
        if keyword in place_name:
            aliases.append(keyword)
    suffix_removed = re.sub(r"(风景区|旅游度假区|景区|公园|博物馆|美术馆|夜景|店)$", "", place_name)
    if len(suffix_removed) >= 2:
        aliases.append(suffix_removed)
    return list(dict.fromkeys(aliases))


def _is_iconic_place(place: dict[str, Any]) -> bool:
    name = place.get("name", "")
    city = place.get("city")
    keywords = POPULAR_PLACE_KEYWORDS_BY_CITY.get(city, []) + _all_popular_keywords()
    return any(keyword in name for keyword in keywords)


def _local_popularity_score(place: dict[str, Any]) -> int:
    score = 14 if _is_iconic_place(place) else 0
    rating = place.get("rating")
    try:
        rating_value = float(rating)
    except (TypeError, ValueError):
        rating_value = 0
    if rating_value >= 4.6:
        score += 8
    elif rating_value >= 4.2:
        score += 5
    return score


def _all_popular_keywords() -> list[str]:
    keywords = []
    for city_keywords in POPULAR_PLACE_KEYWORDS_BY_CITY.values():
        keywords.extend(city_keywords)
    return list(dict.fromkeys(keywords))


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


def _tool_result(tool_name: str, data: Any, input_data: Any = None) -> dict[str, Any]:
    result = {"tool_name": tool_name, "status": "success", "data": data, "error": None}
    if input_data is not None:
        result["input"] = _compact_payload(input_data)
    return result


def _emit_tool_event(
    state: AgentState,
    parent_node: str,
    tool_name: str,
    summary: str,
    status: str,
    input_data: Any = None,
    output_summary: Any = None,
    preview_items: list[Any] | None = None,
    progress: int | None = None,
) -> None:
    callback = getattr(state, "_progress_callback", None)
    if not callback:
        return
    event = {
        "trace_id": state.trace_id,
        "phase": "tool",
        "parent_node": parent_node,
        "node": tool_name,
        "tool_name": tool_name,
        "summary": summary,
        "status": status,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "input": _compact_payload(input_data),
        "output_summary": _compact_payload(output_summary),
        "preview_items": _compact_preview(preview_items),
    }
    if state.replan_context:
        event["details"] = {"round": "auto_replan"}
    if progress is not None:
        event["progress"] = progress
    callback(event)


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


def _compact_preview(items: list[Any] | None) -> list[Any]:
    return [_compact_payload(item) for item in (items or [])[:8]]


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


def _search_summary(search_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": search_data.get("query"),
        "provider": search_data.get("provider"),
        "results_count": len(search_data.get("results") or []),
        "answer": search_data.get("answer"),
        "note": search_data.get("note"),
        "attempts": search_data.get("attempts") or [],
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


def _first_place_provider(places: list[dict[str, Any]]) -> str | None:
    return next((place.get("provider") for place in places if place.get("provider")), None)


def _fallback_places_for_city(city: str, preferences: list[str] | None = None, activity_intent: str | None = None) -> list[dict[str, Any]]:
    names = POPULAR_PLACE_KEYWORDS_BY_CITY.get(city) or []
    result = []
    for index, name in enumerate(names[:6]):
        tags = _seed_place_tags(name, preferences or [], activity_intent)
        result.append({
            "name": name,
            "city": city,
            "area": city,
            "address": f"{city}{name}",
            "tags": tags,
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "地点来自城市热门地标兜底，票价/营业时间待确认",
            "duration_minutes": _seed_duration(tags),
            "intensity": "中" if "爬山" in tags or "散步" in tags else "低",
            "source_order": index,
            "map_url": f"https://ditu.amap.com/search?query={quote(f'{city} {name}')}",
            "source_url": f"https://ditu.amap.com/search?query={quote(f'{city} {name}')}",
            "source_title": "城市热门地标兜底",
            "play_points": _seed_play_points(name, tags),
            "provider": "city_seed",
            "popularity_score": 18,
        })
    if not result:
        return []
    result.extend(_preference_seed_places(city, preferences or [], result))
    return result


def _city_seed_places(city: str, preferences: list[str] | None = None, activity_intent: str | None = None) -> list[dict[str, Any]]:
    return _fallback_places_for_city(city, preferences, activity_intent)


def _generic_city_search_places(city: str, activity_intent: str | None = None) -> list[dict[str, Any]]:
    templates = [
        ("城市核心游玩区（地图搜索）", ["景点", "散步", "室外"], "用地图搜索当地核心景点/商圈，作为主线起点；具体地点和开放信息待确认"),
        ("展览/博物馆候选（地图搜索）", ["展览", "博物馆", "室内"], "用地图搜索当地展览、美术馆或博物馆，作为室内停留点；预约和开放信息待确认"),
        ("夜景/步行街候选（地图搜索）", ["夜景", "散步", "室外"], "用地图搜索夜景、江河湖岸或步行街，作为傍晚段；安全和交通信息待确认"),
    ]
    if activity_intent in {"爬山", "登山", "徒步"}:
        templates[0] = ("登山/徒步候选（地图搜索）", ["爬山", "徒步", "运动", "室外"], "用地图搜索当地登山、徒步或公园路线；开放和路况待确认")
    result = []
    for index, (name, tags, point) in enumerate(templates):
        query = name.replace("（地图搜索）", "").replace("/", " ")
        result.append({
            "name": name,
            "city": city,
            "area": city,
            "address": f"{city}{query}",
            "tags": tags,
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "地图服务降级后的类别型候选，票价/营业时间待确认",
            "duration_minutes": _seed_duration(tags),
            "intensity": "中" if any(tag in tags for tag in ["爬山", "徒步", "散步"]) else "低",
            "source_order": 200 + index,
            "map_url": f"https://ditu.amap.com/search?query={quote(f'{city} {query}')}",
            "source_url": f"https://ditu.amap.com/search?query={quote(f'{city} {query}')}",
            "source_title": "地图服务降级兜底",
            "play_points": [point],
            "provider": "city_fallback",
            "popularity_score": 6,
        })
    return result


def _preference_seed_places(city: str, preferences: list[str], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    covered = set().union(*(set(place.get("tags", [])) for place in existing)) if existing else set()
    result = []
    templates = PREFERENCE_PLACE_KEYWORDS_BY_CITY.get(city, {})
    for preference in preferences:
        if preference in covered or preference not in templates:
            continue
        name, tags, point = templates[preference]
        result.append({
            "name": name,
            "city": city,
            "area": city,
            "address": f"{city}{preference}地图搜索",
            "tags": tags,
            "estimated_cost": 0,
            "cost_known": False,
            "cost_note": "偏好地点来自城市真实地点兜底，消费待确认",
            "duration_minutes": 60,
            "intensity": "低",
            "source_order": 100 + len(result),
            "map_url": f"https://ditu.amap.com/search?query={quote(f'{city} {name}')}",
            "source_url": f"https://ditu.amap.com/search?query={quote(f'{city} {name}')}",
            "source_title": "城市偏好地点兜底",
            "play_points": [point],
            "provider": "city_seed",
            "popularity_score": 10,
        })
    return result


def _seed_place_tags(name: str, preferences: list[str], activity_intent: str | None) -> list[str]:
    tags = {"景点"}
    text = f"{name} {' '.join(preferences)} {activity_intent or ''}"
    if any(word in text for word in ["博物馆", "省博", "展", "馆"]):
        tags.update(["展览", "博物馆", "室内"])
    if any(word in text for word in ["湖", "桥", "街", "巷", "步行街", "散步", "夜景"]):
        tags.update(["散步", "室外"])
    if "夜景" in text or any(word in name for word in ["长江大桥", "江汉路", "外滩", "珠江"]):
        tags.update(["夜景", "室外"])
    if any(word in text for word in ["山", "爬山", "徒步", "登山"]):
        tags.update(["爬山", "徒步", "运动", "室外"])
    return list(tags)


def _seed_duration(tags: list[str]) -> int:
    if "爬山" in tags:
        return 150
    if "博物馆" in tags or "展览" in tags:
        return 120
    return 90


def _seed_play_points(name: str, tags: list[str]) -> list[str]:
    points = [f"作为{name}相关城市地标兜底候选，出发前确认开放和预约信息"]
    if "博物馆" in tags or "展览" in tags:
        points.append("适合安排为室内展览/馆藏段")
    if "夜景" in tags:
        points.append("适合傍晚或夜间作为观景段")
    if "散步" in tags:
        points.append("适合轻松步行串联")
    return points


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


def _budget_preview(budget: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"label": "活动费", "value": budget.get("activity_cost")},
        {"label": "餐饮", "value": budget.get("meal_budget")},
        {"label": "交通", "value": budget.get("transport_budget")},
        {"label": "合计", "value": budget.get("total")},
    ]


def _filter_places_by_city(places: list[dict], city: str) -> list[dict]:
    return [place for place in places if place.get("city") == city]


def _plan_uses_candidate_places(plan: dict[str, Any], selected: list[dict]) -> bool:
    allowed = {place["name"] for place in selected}
    return bool(allowed) and all(item.get("place") in allowed for item in plan.get("itinerary", []))


def _enrich_plan_items(plan: dict[str, Any], selected: list[dict]) -> dict[str, Any]:
    place_by_name = {place["name"]: place for place in selected}
    for item in plan.get("itinerary", []):
        place = place_by_name.get(item.get("place"))
        if not place:
            continue
        for key in ["address", "location", "map_url", "source_url", "source_title", "play_points", "cost_known", "cost_note", "evidence"]:
            if place.get(key) and not item.get(key):
                item[key] = place[key]
    plan["assistant_message"] = _build_assistant_message_from_plan(plan)
    return plan


def _time_label(total_minutes: int) -> str:
    hour = total_minutes // 60
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"


def _linked_place(item: dict[str, Any]) -> str:
    name = item.get("place", "地点")
    url = item.get("map_url")
    return f"[{name}]({url})" if url else name


def _linked_source(item: dict[str, Any]) -> str:
    title = item.get("title", "来源")
    url = item.get("url")
    return f"[{title}]({url})" if url else title


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


def _distance_between(a: dict, b: dict) -> float:
    coord_a = _coordinates(a)
    coord_b = _coordinates(b)
    if not coord_a or not coord_b:
        return math.inf
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
