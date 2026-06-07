from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.graph import run_lifeops
from agent.nodes import extract_constraints, plan_steps, travel_tool_router
from agent.state import AgentState


class TaskTypeTest(unittest.TestCase):
    def test_extracts_first_mvp_task_types(self) -> None:
        cases = [
            ("明天下午我要取快递、买生日礼物、顺便吃晚饭", "errand"),
            ("今晚在杭州找个预算 200 的餐厅吃饭", "meal"),
            ("帮我把上线 LifeOps MVP 拆成待办和完成标准", "todo"),
            ("周六杭州玩一天，预算 500", "travel"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                state = extract_constraints(AgentState(user_input=text))
                self.assertEqual(state.constraints["task_type"], expected)

    def test_plan_steps_follow_task_type(self) -> None:
        state = AgentState(user_input="帮我拆解目标")
        state.constraints["task_type"] = "todo"
        state = plan_steps(state)
        self.assertTrue(any(step["tool"] == "todo_decomposer" for step in state.plan_steps))

    def test_travel_plan_steps_run_place_search_before_web_evidence(self) -> None:
        state = AgentState(user_input="周六洛阳玩一天")
        state.constraints["task_type"] = "travel"
        with patch("agent.nodes._llm_enabled", return_value=False):
            state = plan_steps(state)
        tools = [step["tool"] for step in state.plan_steps]

        self.assertLess(tools.index("place_search_tool"), tools.index("web_search_tool"))

    def test_explicit_unknown_city_beats_default_city(self) -> None:
        state = AgentState(user_input="周六大连轻松玩一天，预算 500")
        state.constraints["default_city"] = "杭州"

        state = extract_constraints(state)

        self.assertEqual(state.constraints["city"], "大连")
        self.assertEqual(state.constraints["default_city"], "杭州")

    def test_empty_place_search_skips_web_and_asks_for_clarification(self) -> None:
        state = AgentState(user_input="周六洛阳玩一天")
        state.constraints.update({"task_type": "travel", "city": "洛阳"})

        with (
            patch("agent.nodes.get_weather", return_value={"city": "洛阳", "provider": "mock"}),
            patch("agent.nodes.search_places", return_value=[]),
            patch("agent.nodes.search_web") as search_web,
        ):
            result = travel_tool_router(state)

        search_web.assert_not_called()
        self.assertTrue(result.need_human_confirm)
        self.assertIn("真实候选地点", result.clarification_question)
        self.assertEqual(result._places, [])  # type: ignore[attr-defined]
        self.assertEqual([item["tool_name"] for item in result.tool_results], ["weather_tool", "place_search_tool", "web_search_tool"])

    def test_todo_run_does_not_call_weather_or_map_tools(self) -> None:
        result = run_lifeops("帮我把准备产品发布拆成待办、时间块和完成标准")

        self.assertEqual(result["constraints"]["task_type"], "todo")
        self.assertEqual(result["final_plan"]["task_type"], "todo")
        tool_names = {item["tool_name"] for item in result["tool_results"]}
        self.assertNotIn("weather_tool", tool_names)
        self.assertNotIn("place_search_tool", tool_names)
        self.assertIn("todo_rule_parser", tool_names)


if __name__ == "__main__":
    unittest.main()
