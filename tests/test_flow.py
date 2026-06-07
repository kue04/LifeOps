from __future__ import annotations

import unittest

from agent.graph import run_lifeops


class LifeOpsFlowTest(unittest.TestCase):
    def test_complete_weekend_plan(self) -> None:
        result = run_lifeops("周六杭州玩一天，预算 500，喜欢咖啡和展览，不想太累。")

        self.assertEqual(result["status"], "success")
        self.assertLessEqual(result["final_plan"]["budget"]["total"], 500)
        self.assertRegex(result["constraints"]["date_iso"], r"\d{4}-\d{2}-\d{2}")
        self.assertGreaterEqual(len(result["tool_results"]), 4)
        self.assertTrue(result["execution_log"])
        self.assertTrue(result["assistant_message"])

    def test_missing_info_asks_clarification(self) -> None:
        result = run_lifeops("帮我安排周末。")

        self.assertEqual(result["status"], "need_clarification")
        self.assertIn("城市", result["question"])
        self.assertTrue(result["execution_log"])

    def test_avoid_coffee_outputs_clickable_places(self) -> None:
        result = run_lifeops("明天我要去杭州玩 有没有好的建议 并且我不想喝咖啡")

        self.assertEqual(result["status"], "success")
        self.assertIn("咖啡", result["constraints"]["avoid"])
        self.assertNotIn("咖啡", result["constraints"].get("preferences", []))
        self.assertEqual(result["tool_results"][1]["tool_name"], "place_search_tool")
        self.assertIn("weather", result["final_plan"])
        self.assertIn("travel_research", result["final_plan"])
        for item in result["final_plan"]["itinerary"]:
            self.assertNotIn("咖啡", item["tags"])
            self.assertIn("https://ditu.amap.com/search?query=", item["map_url"])
        self.assertIn("https://ditu.amap.com/search?query=", result["assistant_message"])

    def test_followup_replan_keeps_context(self) -> None:
        first = run_lifeops("周六杭州玩一天，预算 500，喜欢咖啡、展览和夜景，不想太累。")
        second = run_lifeops("太贵了，控制在 300。", previous_result=first)

        self.assertEqual(second["status"], "success")
        self.assertEqual(second["constraints"]["city"], "杭州")
        self.assertLessEqual(second["final_plan"]["budget"]["total"], 300)

    def test_xiamen_weather_does_not_crash(self) -> None:
        result = run_lifeops("周六厦门轻松玩一天，预算 500，喜欢咖啡和夜景，不想太累。")

        self.assertIn(result["status"], {"success", "need_clarification"})
        self.assertEqual(result["constraints"]["city"], "厦门")

    def test_fuzhou_hiking_prefers_mountain_routes(self) -> None:
        result = run_lifeops("明天去福州玩有没有推荐的 我喜欢运动量多的地方 喜欢爬山 预算9999")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["constraints"]["city"], "福州")
        self.assertIn("爬山", result["constraints"].get("preferences", []))
        joined = " ".join(item["place"] for item in result["final_plan"]["itinerary"])
        self.assertTrue(any(keyword in joined for keyword in ["鼓山", "福道", "森林公园", "登山"]))
        self.assertIn("活动费", result["assistant_message"])
        self.assertIn("餐饮", result["assistant_message"])
        self.assertIn("交通", result["assistant_message"])

    def test_not_too_relaxed_sets_medium_pace_and_dynamic_budget(self) -> None:
        result = run_lifeops("这周六我想在杭州轻松玩一天，预算 500，不想太轻松。")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["constraints"]["pace"], "中等")
        budget = result["final_plan"]["budget"]
        self.assertEqual(budget["budget_limit"], 500)
        self.assertNotEqual((budget["meal_budget"], budget["transport_budget"]), (90, 60))


if __name__ == "__main__":
    unittest.main()
