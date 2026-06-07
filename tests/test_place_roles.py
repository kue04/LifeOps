from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.graph import _replan_nodes, run_lifeops


KUNMING_AMAP_PLACES = [
    {
        "name": "洛龙公园",
        "city": "昆明",
        "area": "呈贡区",
        "address": "昆明呈贡区洛龙公园",
        "tags": ["散步", "室外"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 90,
        "play_points": ["呈贡区普通公园"],
        "location": "102.83,24.88",
        "provider": "amap",
    },
    {
        "name": "青方豆腐博物馆",
        "city": "昆明",
        "area": "呈贡区",
        "address": "昆明呈贡区青方豆腐博物馆",
        "tags": ["展览", "博物馆", "室内"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 90,
        "play_points": ["呈贡区小众博物馆"],
        "location": "102.84,24.89",
        "provider": "amap",
    },
]

KUNMING_WEB_PLACES = [
    {
        "name": "滇池",
        "city": "昆明",
        "area": "西山区",
        "address": "昆明市西山区滇池",
        "tags": ["景点", "散步", "室外"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 100,
        "play_points": ["湖景和海埂片区城市风光"],
        "location": "102.65,24.87",
        "provider": "amap",
    },
    {
        "name": "斗南花市",
        "city": "昆明",
        "area": "呈贡区",
        "address": "昆明市呈贡区斗南花市",
        "tags": ["景点", "散步", "室内"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 90,
        "play_points": ["鲜花交易和夜间花市氛围"],
        "location": "102.80,24.88",
        "provider": "amap",
    },
    {
        "name": "西山风景区",
        "city": "昆明",
        "area": "西山区",
        "address": "昆明市西山区西山风景区",
        "tags": ["景点", "爬山", "徒步", "室外"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 150,
        "play_points": ["登高看滇池和城市轮廓"],
        "location": "102.62,24.96",
        "provider": "amap",
    },
    {
        "name": "金马碧鸡坊",
        "city": "昆明",
        "area": "西山区",
        "address": "昆明市西山区金马碧鸡坊",
        "tags": ["景点", "散步", "夜景", "室外"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 60,
        "play_points": ["市中心地标和夜景"],
        "location": "102.71,25.03",
        "provider": "amap",
    },
    {
        "name": "云南省博物馆",
        "city": "昆明",
        "area": "官渡区",
        "address": "昆明市官渡区云南省博物馆",
        "tags": ["景点", "展览", "博物馆", "室内"],
        "estimated_cost": 0,
        "cost_known": False,
        "duration_minutes": 120,
        "play_points": ["云南历史文化展陈"],
        "location": "102.76,24.96",
        "provider": "amap",
    },
]


def kunming_search_places(city: str, preferences: list[str], avoid: list[str] | None = None, hotel_brand: str | None = None) -> list[dict]:
    wanted = " ".join(preferences)
    if any(place["name"] in wanted for place in KUNMING_WEB_PLACES):
        return [place for place in KUNMING_WEB_PLACES if place["name"] in wanted]
    return KUNMING_AMAP_PLACES


def fast_weather(city: str, date: str | None = None) -> dict:
    return {"city": city, "date": date, "condition": "晴", "outdoor_risk": "low", "provider": "mock"}


class PlaceRolePlanningTest(unittest.TestCase):
    def test_huashan_from_current_location_uses_destination_not_origin_city(self) -> None:
        result = run_lifeops(
            "下周六想去爬华山 有什么推荐的路线吗 从我现在这个地方出发",
            request_context={"origin_location": "119.1051,25.4667", "default_city": "莆田"},
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["constraints"]["destination"]["name"], "华山风景名胜区")
        self.assertEqual(result["constraints"]["origin"]["city"], "莆田")
        self.assertEqual(result["constraints"]["route_scope"], "cross_city_trip")
        joined = " ".join(item["place"] for item in result["final_plan"]["itinerary"])
        self.assertIn("华山", joined)
        self.assertNotIn("莆田", joined)
        self.assertIn("access_route", result["final_plan"])
        queries = [
            item.get("input", {}).get("query", "")
            for item in result["tool_results"]
            if item.get("tool_name") == "web_search_tool"
        ]
        queries.extend(
            item.get("details", {}).get("search_query", "")
            for item in result["execution_log"]
            if item.get("node") == "tool_router"
        )
        self.assertTrue(any("华山" in query for query in queries))
        self.assertFalse(any(query.startswith("莆田 ") for query in queries))

    def test_huangshan_text_targets_scenic_area_without_city_clarification(self) -> None:
        result = run_lifeops("明天去黄山旅游 有什么好的计划吗")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["constraints"]["destination"]["name"], "黄山风景区")
        joined = " ".join(item["place"] for item in result["final_plan"]["itinerary"])
        self.assertIn("黄山", joined)

    def test_nearby_walk_uses_activity_area_when_no_destination(self) -> None:
        result = run_lifeops(
            "周六就在我附近找个适合散步的地方",
            request_context={"origin_location": "119.1051,25.4667", "default_city": "莆田"},
        )

        self.assertEqual(result["status"], "success")
        self.assertIsNone(result["constraints"].get("destination"))
        self.assertEqual(result["constraints"]["activity_area"]["city"], "莆田")
        self.assertEqual(result["constraints"]["route_scope"], "city_trip")

    def test_putian_to_fuzhou_gushan_separates_origin_and_destination(self) -> None:
        result = run_lifeops("从莆田出发去福州鼓山爬山", request_context={"default_city": "莆田"})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["constraints"]["origin"]["city"], "莆田")
        self.assertEqual(result["constraints"]["destination"]["city"], "福州")
        self.assertEqual(result["constraints"]["destination"]["name"], "鼓山")
        joined = " ".join(item["place"] for item in result["final_plan"]["itinerary"])
        self.assertIn("鼓山", joined)
        self.assertNotIn("莆田", joined)

    def test_hangzhou_to_shanghai_exhibition_is_cross_city(self) -> None:
        result = run_lifeops("我在杭州，周末想去上海看展", request_context={"default_city": "莆田"})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["constraints"]["origin"]["city"], "杭州")
        self.assertEqual(result["constraints"]["destination"]["city"], "上海")
        self.assertIn("展览", result["constraints"]["preferences"])
        self.assertEqual(result["constraints"]["route_scope"], "cross_city_trip")

    def test_city_district_query_does_not_add_mountain_terms(self) -> None:
        result = run_lifeops("下周六我想去厦门思明区玩两天 预算700")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["constraints"]["destination"]["name"], "思明区")
        queries = [
            item.get("details", {}).get("search_query", "")
            for item in result["execution_log"]
            if item.get("node") == "tool_router"
        ]
        queries.extend(
            item.get("data", {}).get("query", "")
            for item in result.get("tool_results", [])
            if item.get("tool_name") == "web_search_tool"
        )
        joined = " ".join(queries)
        self.assertIn("厦门 思明区", joined)
        self.assertNotIn("索道", joined)
        self.assertNotIn("换乘中心", joined)

    def test_province_hint_with_city_targets_city_core_attractions(self) -> None:
        with (
            patch("agent.nodes.search_places", return_value=KUNMING_AMAP_PLACES),
            patch("agent.nodes.get_weather", side_effect=fast_weather),
            patch("agent.nodes.search_web", return_value={"provider": "mock", "query": "昆明 旅游", "results": [], "note": "mock"}),
        ):
            result = run_lifeops("明天去云南 查找昆明旅游景点推荐")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["constraints"]["destination"]["name"], "昆明")
        self.assertEqual(result["constraints"]["route_scope"], "city_trip")
        itinerary = [item["place"] for item in result["final_plan"]["itinerary"]]
        self.assertTrue({"滇池", "翠湖公园", "云南省博物馆", "斗南花市", "金马碧鸡坊", "西山风景区"}.intersection(itinerary))
        self.assertNotEqual(itinerary[0], "洛龙公园")

    def test_city_guide_filters_city_encyclopedia_and_limits_museums_parks(self) -> None:
        web_result = {
            "provider": "mock",
            "query": "昆明 旅游景点推荐",
            "results": [
                {
                    "name": "昆明 - 维基百科",
                    "url": "https://zh.wikipedia.org/wiki/%E6%98%86%E6%98%8E",
                    "summary": "昆明是云南省省会，介绍地理环境、历史沿革和行政区划。",
                },
                {
                    "name": "昆明市人民政府门户网站",
                    "url": "https://www.km.gov.cn/",
                    "summary": "昆明市情、行政区划、人口和政府信息公开。",
                },
                {
                    "name": "昆明旅游攻略：滇池、斗南花市、西山风景区",
                    "url": "https://example.com/kunming-guide",
                    "summary": "昆明必去景点推荐，包含滇池、斗南花市、西山风景区、金马碧鸡坊和一日游路线。",
                },
                {
                    "name": "昆明_百度百科",
                    "url": "https://baike.baidu.com/item/%E6%98%86%E6%98%8E",
                    "summary": "昆明城市百科，介绍地理、气候、历史和人口。",
                },
            ],
        }
        with (
            patch("agent.nodes.search_places", return_value=KUNMING_AMAP_PLACES),
            patch("agent.nodes.get_weather", side_effect=fast_weather),
            patch("agent.nodes.search_web", return_value=web_result),
        ):
            result = run_lifeops("明天去云南 查找昆明旅游景点推荐")

        sources = result["final_plan"]["travel_research"]["sources"]
        self.assertEqual([source["title"] for source in sources], ["昆明旅游攻略：滇池、斗南花市、西山风景区"])
        web_search = next(item for item in result["tool_results"] if item["tool_name"] == "web_search_tool")
        self.assertEqual(web_search["data"]["filtered_results_count"], 1)
        itinerary = [item["place"] for item in result["final_plan"]["itinerary"]]
        museum_or_park_count = sum(1 for name in itinerary if "博物馆" in name or "公园" in name)
        self.assertLessEqual(museum_or_park_count, 1)
        self.assertTrue({"滇池", "斗南花市", "金马碧鸡坊", "西山风景区"}.intersection(itinerary))

    def test_city_guide_supplements_to_five_sources_and_uses_web_places(self) -> None:
        primary_web = {
            "provider": "mock",
            "query": "昆明 旅游景点推荐",
            "results": [
                {
                    "name": "昆明_百度百科",
                    "url": "https://baike.baidu.com/item/%E6%98%86%E6%98%8E",
                    "summary": "昆明城市百科，介绍地理、气候、历史和人口。",
                },
                {
                    "name": "昆明必去景点攻略",
                    "url": "https://example.com/kunming-1",
                    "summary": "昆明必去景点推荐：滇池、斗南花市、西山风景区，适合一日游路线。",
                },
                {
                    "name": "昆明一日游路线",
                    "url": "https://example.com/kunming-2",
                    "summary": "昆明一日游路线可串联滇池、金马碧鸡坊和斗南花市。",
                },
            ],
        }
        supplemental_web = {
            "provider": "mock",
            "query": "昆明 必去景点 推荐 攻略",
            "results": [
                {
                    "name": "昆明热门景点榜单",
                    "url": "https://example.com/kunming-3",
                    "summary": "昆明热门景点包含滇池、西山风景区、云南民族村和金马碧鸡坊。",
                },
                {
                    "name": "昆明游玩攻略",
                    "url": "https://example.com/kunming-4",
                    "summary": "昆明游玩攻略推荐斗南花市、滇池、西山风景区，兼顾交通和美食。",
                },
                {
                    "name": "昆明景点路线攻略",
                    "url": "https://example.com/kunming-5",
                    "summary": "昆明景点路线建议：西山风景区看滇池，傍晚到金马碧鸡坊。",
                },
            ],
        }
        with (
            patch("agent.nodes.search_places", side_effect=kunming_search_places),
            patch("agent.nodes.get_weather", side_effect=fast_weather),
            patch("agent.nodes.search_web", side_effect=[primary_web, supplemental_web]) as search_web_mock,
        ):
            result = run_lifeops("明天去云南 查找昆明旅游景点推荐")

        sources = result["final_plan"]["travel_research"]["sources"]
        self.assertGreaterEqual(len(sources), 5)
        self.assertEqual(search_web_mock.call_count, 2)
        web_search = next(item for item in result["tool_results"] if item["tool_name"] == "web_search_tool")
        self.assertIn("supplemental_queries", web_search["data"])
        itinerary = [item["place"] for item in result["final_plan"]["itinerary"]]
        self.assertTrue({"滇池", "斗南花市", "西山风景区", "金马碧鸡坊"}.intersection(itinerary))
        self.assertLessEqual(sum(1 for name in itinerary if "博物馆" in name), 1)
        self.assertNotEqual(itinerary[:2], ["青方豆腐博物馆", "云南省博物馆"])

    def test_explicit_city_beats_default_city_for_beach_preference(self) -> None:
        result = run_lifeops(
            "这周六我想在宁波轻松玩一天，预算 500，喜欢去海边，不想太累。",
            request_context={"default_city": "杭州"},
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["constraints"]["city"], "宁波")
        self.assertIn("海边", result["constraints"]["preferences"])
        queries = [
            item.get("details", {}).get("search_query", "")
            for item in result["execution_log"]
            if item.get("node") == "tool_router"
        ]
        joined_query = " ".join(queries)
        self.assertIn("宁波", joined_query)
        self.assertNotIn("杭州", joined_query)

    def test_auto_replan_restarts_from_tool_router(self) -> None:
        self.assertEqual(_replan_nodes()[0][0], "travel_tool_router")


if __name__ == "__main__":
    unittest.main()
