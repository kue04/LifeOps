from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.graph import run_lifeops


MOCK_PLACES = [
    {
        "name": "安静餐厅",
        "city": "杭州",
        "area": "湖滨",
        "address": "杭州湖滨",
        "tags": ["美食", "安静餐厅"],
        "estimated_cost": 80,
        "cost_known": True,
        "duration_minutes": 75,
        "play_points": ["安静用餐"],
        "location": "120.16,30.25",
    },
    {
        "name": "礼物店",
        "city": "杭州",
        "area": "湖滨",
        "address": "杭州湖滨商圈",
        "tags": ["书店", "室内"],
        "estimated_cost": 60,
        "cost_known": False,
        "duration_minutes": 35,
        "play_points": ["挑选礼物"],
        "location": "120.17,30.25",
    },
    {
        "name": "夜景步行街",
        "city": "杭州",
        "area": "湖滨",
        "address": "杭州湖滨步行街",
        "tags": ["夜景", "散步", "室外"],
        "estimated_cost": 0,
        "cost_known": True,
        "duration_minutes": 60,
        "play_points": ["看夜景"],
        "location": "120.18,30.25",
    },
]

CHENGDU_HOTPOT_PLACES = [
    {
        "name": "翠孃孃老火锅(春熙路老店)",
        "city": "成都",
        "area": "锦江区",
        "address": "成都春熙路",
        "tags": ["美食", "火锅", "室内"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 75,
        "play_points": ["火锅用餐"],
        "location": "104.078075,30.661312",
        "map_url": "https://ditu.amap.com/search?query=成都%20翠孃孃老火锅",
        "provider": "amap",
    }
]

CHENGDU_MAP_MATCHES = {
    "武侯祠": {
        "name": "成都武侯祠博物馆",
        "city": "成都",
        "area": "武侯区",
        "address": "武侯祠大街231号",
        "tags": ["展览", "博物馆", "室内"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 90,
        "play_points": ["三国文化展陈"],
        "location": "104.047992,30.646168",
        "map_url": "https://ditu.amap.com/search?query=成都%20武侯祠",
        "provider": "amap",
    },
    "杜甫草堂": {
        "name": "成都杜甫草堂博物馆",
        "city": "成都",
        "area": "青羊区",
        "address": "青华路37号",
        "tags": ["展览", "博物馆", "室内"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 90,
        "play_points": ["诗歌文化展陈"],
        "location": "104.028514,30.660153",
        "map_url": "https://ditu.amap.com/search?query=成都%20杜甫草堂",
        "provider": "amap",
    },
}


MEISHAN_SCENIC_PLACES = [
    {
        "name": "三苏祠",
        "city": "眉山",
        "area": "东坡区",
        "address": "纱縠行南段72号",
        "tags": ["散步", "室外"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 90,
        "play_points": ["东坡文化核心点"],
        "location": "103.830863,30.040704",
        "provider": "amap",
    },
    {
        "name": "东坡印象水街",
        "city": "眉山",
        "area": "东坡区",
        "address": "颍滨桥与颍滨路交汇处东南角",
        "tags": ["散步", "室外"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 90,
        "play_points": ["夜景和街区慢逛"],
        "location": "103.864073,30.061279",
        "provider": "amap",
    },
    {
        "name": "中国泡菜城",
        "city": "眉山",
        "area": "东坡区",
        "address": "顺江大道1号",
        "tags": ["展览", "博物馆", "室内"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 90,
        "play_points": ["地方饮食文化"],
        "location": "103.852949,30.027299",
        "provider": "amap",
    },
    {
        "name": "柳江古镇",
        "city": "眉山",
        "area": "洪雅县",
        "address": "柳江镇玉屏北街27号",
        "tags": ["散步", "室外"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 120,
        "play_points": ["古镇慢逛"],
        "location": "103.230000,29.910000",
        "provider": "amap",
    },
    {
        "name": "瓦屋山风景区",
        "city": "眉山",
        "area": "洪雅县",
        "address": "瓦屋山镇金花桥",
        "tags": ["爬山", "运动", "室外"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 180,
        "play_points": ["自然风光"],
        "location": "102.993424,29.676548",
        "provider": "amap",
    },
]

MEISHAN_HOTPOT_PLACES = [
    {
        "name": "海底捞火锅(眉山万达广场店)",
        "city": "眉山",
        "area": "东坡区",
        "address": "文忠街333号",
        "tags": ["美食", "火锅", "室内"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 75,
        "play_points": ["火锅用餐"],
        "location": "103.838882,30.071704",
        "provider": "amap",
    },
    {
        "name": "吴老四美蛙鲜鱼火锅(庭院店)",
        "city": "眉山",
        "area": "东坡区",
        "address": "一环东路201号",
        "tags": ["美食", "火锅", "室内"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 75,
        "play_points": ["本地火锅用餐"],
        "location": "103.843136,30.050417",
        "provider": "amap",
    },
]

HANGZHOU_TRAVEL_PLACES = [
    {
        "name": "浙江省博物馆",
        "city": "杭州",
        "area": "西湖区",
        "address": "孤山路",
        "tags": ["展览", "博物馆", "室内"],
        "estimated_cost": 0,
        "cost_known": True,
        "duration_minutes": 90,
        "play_points": ["看常设展"],
        "location": "120.145,30.253",
        "provider": "amap",
    },
    {
        "name": "杭州工艺美术博物馆",
        "city": "杭州",
        "area": "拱墅区",
        "address": "小河路",
        "tags": ["展览", "博物馆", "室内"],
        "estimated_cost": 0,
        "cost_known": True,
        "duration_minutes": 90,
        "play_points": ["看工艺展"],
        "location": "120.139,30.305",
        "provider": "amap",
    },
    {
        "name": "西湖风景区",
        "city": "杭州",
        "area": "西湖区",
        "address": "西湖",
        "tags": ["景点", "散步", "室外"],
        "estimated_cost": 0,
        "cost_known": True,
        "duration_minutes": 120,
        "play_points": ["湖边散步"],
        "location": "120.143,30.246",
        "provider": "amap",
    },
    {
        "name": "河坊街",
        "city": "杭州",
        "area": "上城区",
        "address": "河坊街",
        "tags": ["散步", "美食", "室外"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 75,
        "play_points": ["街区闲逛"],
        "location": "120.174,30.244",
        "provider": "amap",
    },
]

HANGZHOU_FOOD_PLACES = [
    {
        "name": "知味观味庄",
        "city": "杭州",
        "area": "西湖区",
        "address": "杨公堤",
        "tags": ["美食", "餐厅"],
        "estimated_cost": 90,
        "cost_known": False,
        "duration_minutes": 75,
        "play_points": ["杭帮菜正餐"],
        "location": "120.135,30.239",
        "provider": "amap",
    }
]

HANGZHOU_HOTEL_PLACES = [
    {
        "name": "汉庭酒店(杭州西湖店)",
        "city": "杭州",
        "area": "上城区",
        "address": "延安路",
        "tags": ["酒店", "住宿"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 0,
        "play_points": ["住西湖周边少绕路"],
        "location": "120.168,30.251",
        "provider": "amap",
    }
]


def chengdu_search_places(city: str, preferences: list[str], avoid: list[str] | None = None, hotel_brand: str | None = None) -> list[dict]:
    if city != "成都":
        return []
    if set(preferences).intersection({"景点", "旅游景点", "博物馆", "公园"}):
        return list(CHENGDU_MAP_MATCHES.values())
    for preference in preferences:
        if preference == "火锅":
            return CHENGDU_HOTPOT_PLACES
        if preference in CHENGDU_MAP_MATCHES:
            return [CHENGDU_MAP_MATCHES[preference]]
    return []


def meishan_search_places(city: str, preferences: list[str], avoid: list[str] | None = None, hotel_brand: str | None = None) -> list[dict]:
    if city != "眉山":
        return []
    preference_set = set(preferences)
    by_name = {place["name"]: place for place in MEISHAN_SCENIC_PLACES}
    exact = [by_name[preference] for preference in preferences if preference in by_name]
    if exact:
        return exact
    if "火锅" in preference_set:
        return MEISHAN_HOTPOT_PLACES
    if preference_set.intersection({"景点", "旅游景点", "博物馆", "公园"}):
        return MEISHAN_SCENIC_PLACES
    return []


def hangzhou_search_places(city: str, preferences: list[str], avoid: list[str] | None = None, hotel_brand: str | None = None) -> list[dict]:
    if city != "杭州":
        return []
    preference_set = set(preferences)
    if preference_set.intersection({"美食", "特色餐厅", "小吃"}):
        return HANGZHOU_FOOD_PLACES
    if preference_set.intersection({"酒店", "住宿"}) or hotel_brand:
        return HANGZHOU_HOTEL_PLACES
    if preference_set.intersection({"景点", "旅游景点", "古镇", "博物馆"}):
        return HANGZHOU_TRAVEL_PLACES
    return HANGZHOU_TRAVEL_PLACES


def fast_weather(city: str, date: str | None = None) -> dict:
    return {"city": city, "date": date, "condition": "晴", "outdoor_risk": "low", "provider": "mock"}


class DynamicIntentTest(unittest.TestCase):
    def test_mixed_errand_meal_uses_dynamic_plan(self) -> None:
        with patch("agent.nodes.search_places", return_value=MOCK_PLACES):
            result = run_lifeops(
                "明天下午在杭州取快递、买生日礼物，晚上找一家安静餐厅吃饭，预算300",
                request_context={"default_city": "杭州"},
            )

        plan = result["final_plan"]
        contract = plan["intent_contract"]
        execution_plan = plan["execution_plan"]
        self.assertEqual(result["status"], "success")
        self.assertEqual(plan["task_type"], "mixed")
        self.assertEqual(
            [item["type"] for item in contract["sub_tasks"]],
            ["errand", "meal"],
        )
        self.assertIn("errand_items", contract["required_outputs"])
        self.assertIn("meal_candidates", contract["required_outputs"])
        self.assertTrue(plan["errand_items"])
        self.assertTrue(plan["meal_candidates"])
        self.assertTrue(plan["itinerary"])
        self.assertNotIn("search", [item["tool"] for item in execution_plan])

    def test_todo_dynamic_plan_skips_map_weather_search(self) -> None:
        result = run_lifeops("帮我把准备产品发布拆成待办、时间块和完成标准")

        self.assertEqual(result["final_plan"]["task_type"], "todo")
        tools = [item["tool"] for item in result["final_plan"]["execution_plan"]]
        self.assertEqual(tools, ["todo_decompose", "confirm_action"])
        tool_names = {item["tool_name"] for item in result["tool_results"]}
        self.assertNotIn("weather_tool", tool_names)
        self.assertNotIn("place_search_tool", tool_names)

    def test_travel_dynamic_plan_keeps_travel_tools(self) -> None:
        with (
            patch("agent.nodes.search_places", return_value=MOCK_PLACES),
            patch("agent.nodes.get_weather", side_effect=fast_weather),
            patch("agent.nodes.search_web", return_value={"provider": "mock", "results": [], "note": "mock"}),
        ):
            result = run_lifeops("周六杭州轻松玩一天，预算500，想看展和夜景")

        tools = [item["tool"] for item in result["final_plan"]["execution_plan"]]
        self.assertIn("weather", tools)
        self.assertIn("place_search", tools)
        self.assertIn("search", tools)
        self.assertIn("route", tools)
        self.assertIn("budget", tools)
        self.assertTrue(result["final_plan"]["itinerary"])

    def test_travel_outputs_lifestyle_candidates_basis_and_diverse_alternatives(self) -> None:
        web_result = {
            "provider": "mock",
            "query": "杭州旅游攻略",
            "results": [
                {
                    "name": "杭州一日游攻略",
                    "url": "https://example.com/hangzhou",
                    "summary": "杭州热门景点推荐西湖风景区、河坊街，也可以安排浙江省博物馆，周边有杭帮菜和住宿选择。",
                }
            ],
        }
        with (
            patch("agent.nodes._llm_enabled", return_value=False),
            patch("agent.nodes.search_places", side_effect=hangzhou_search_places),
            patch("agent.nodes.get_weather", side_effect=fast_weather),
            patch("agent.nodes.search_web", return_value=web_result),
        ):
            result = run_lifeops("明天杭州轻松玩一天，预算500，要看看美食和住宿")

        plan = result["final_plan"]
        lifestyle = plan["lifestyle_places"]
        basis = plan["recommendation_basis"]
        alternatives = plan["alternatives"]

        self.assertTrue(lifestyle["foods"])
        self.assertTrue(lifestyle["hotels"])
        self.assertGreaterEqual(basis["food_candidates_count"], 1)
        self.assertGreaterEqual(basis["hotel_candidates_count"], 1)
        self.assertIn("推荐依据", result["assistant_message"])
        self.assertLessEqual(sum(1 for item in alternatives if "博物馆" in item["name"]), 1)

    def test_travel_with_hotpot_keeps_meal_and_completed_steps(self) -> None:
        with (
            patch("agent.nodes._llm_enabled", return_value=False),
            patch("agent.nodes.search_places", side_effect=chengdu_search_places),
            patch("agent.nodes.get_weather", side_effect=fast_weather),
            patch("agent.nodes.search_web", return_value={"provider": "mock", "query": "成都 火锅", "results": [], "note": "mock"}),
        ):
            result = run_lifeops("明天我想要去成都玩 有没有好玩的地方 我还想吃火锅")

        plan = result["final_plan"]
        self.assertEqual(plan["task_type"], "mixed")
        self.assertEqual({item["type"] for item in plan["intent_contract"]["sub_tasks"]}, {"travel", "meal"})
        self.assertTrue(all(item["status"] == "completed" for item in plan["execution_plan"]))
        self.assertTrue(any("火锅" in item.get("tags", []) and item.get("location") for item in plan["itinerary"]))
        self.assertTrue(any(item.get("cost", 0) > 0 for item in plan["itinerary"]))

    def test_meishan_travel_hotpot_uses_live_city_search_shape(self) -> None:
        with (
            patch("agent.nodes._llm_enabled", return_value=False),
            patch("agent.nodes.search_places", side_effect=meishan_search_places),
            patch("agent.nodes.get_weather", side_effect=fast_weather),
            patch("agent.nodes.search_web", return_value={"provider": "mock", "query": "眉山 火锅", "results": [], "note": "mock"}),
        ):
            result = run_lifeops("想去眉山旅游，吃火锅")

        plan = result["final_plan"]
        itinerary_names = [item["place"] for item in plan["itinerary"]]
        meal_names = [item["name"] for item in plan["meal_candidates"]]
        providers = {item.get("provider") for item in plan["local_route"]["ordered_places"]}

        self.assertEqual(result["constraints"]["destination"]["type"], "city")
        self.assertNotIn("眉山", itinerary_names)
        self.assertIn("三苏祠", itinerary_names)
        self.assertIn("东坡印象水街", itinerary_names)
        self.assertLess(meal_names.index("吴老四美蛙鲜鱼火锅(庭院店)"), meal_names.index("海底捞火锅(眉山万达广场店)"))
        self.assertNotIn("city_seed", providers)
        self.assertNotIn("已把餐饮安排", plan["summary"])
        message = result["assistant_message"]
        self.assertIn("必打卡景点", message)
        self.assertIn("火锅精选推荐", message)
        self.assertIn("风味美食", message)
        self.assertIn("精选行程规划", message)
        self.assertIn("三苏祠", message)
        self.assertIn("东坡印象水街", message)
        self.assertIn("中国泡菜城", message)
        self.assertNotIn("**[海底捞火锅", message)
        from api import _frontend_response

        frontend = _frontend_response(result)
        self.assertEqual(frontend["final_plan"]["summary"], frontend["assistant_message"])
        self.assertIn("必打卡景点", frontend["final_plan"]["summary"])
        self.assertIn("recommendation_basis", frontend["final_plan"])
        self.assertIn("lifestyle_places", frontend["final_plan"])

    def test_meishan_guide_uses_web_popular_places(self) -> None:
        web_result = {
            "provider": "mock",
            "query": "眉山旅游攻略",
            "results": [
                {
                    "name": "眉山热门景点攻略",
                    "url": "https://example.com/meishan",
                    "summary": "三苏祠、东坡印象水街、瓦屋山、柳江古镇、中国泡菜城都是眉山热门景点，适合结合火锅和本地美食安排。",
                }
            ],
        }
        with (
            patch("agent.nodes._llm_enabled", return_value=False),
            patch("agent.nodes.search_places", side_effect=meishan_search_places),
            patch("agent.nodes.get_weather", side_effect=fast_weather),
            patch("agent.nodes.search_web", return_value=web_result),
        ):
            result = run_lifeops("想去眉山旅游，吃火锅")

        message = result["assistant_message"]
        for place in ["三苏祠", "东坡印象水街", "瓦屋山", "柳江古镇", "中国泡菜城"]:
            self.assertIn(place, message)
        self.assertNotIn("泡菜广场", message)


if __name__ == "__main__":
    unittest.main()
