from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.graph import run_lifeops
from agent.nodes import load_memory
from agent.state import AgentState


class ReplanContextTest(unittest.TestCase):
    def test_budget_followup_keeps_travel_intent(self) -> None:
        first = run_lifeops("周六杭州玩一天，预算 500，喜欢展览和夜景。")

        second = run_lifeops("太贵了，控制在 300。", previous_result=first)

        self.assertEqual(second["constraints"]["task_type"], "travel")
        self.assertEqual(second["final_plan"]["task_type"], "travel")
        self.assertEqual(
            [item["type"] for item in second["final_plan"]["intent_contract"]["sub_tasks"]],
            ["travel"],
        )
        self.assertLessEqual(second["final_plan"]["budget"]["total"], 300)

    def test_add_meal_followup_keeps_travel_and_adds_meal(self) -> None:
        first = run_lifeops("周六杭州玩一天，预算 500，喜欢展览。")

        second = run_lifeops("再加一顿火锅。", previous_result=first)

        task_types = {
            item["type"]
            for item in second["final_plan"]["intent_contract"]["sub_tasks"]
        }
        self.assertEqual(task_types, {"travel", "meal"})

    def test_explicit_todo_followup_can_switch_task_type(self) -> None:
        first = run_lifeops("周六杭州玩一天，预算 500。")

        second = run_lifeops("改成待办清单。", previous_result=first)

        self.assertEqual(second["constraints"]["task_type"], "todo")
        self.assertEqual(second["final_plan"]["task_type"], "todo")

    def test_memory_overrides_disable_profile_values_for_current_run(self) -> None:
        state = AgentState(user_input="帮我安排今天", user_id="alice")
        state.constraints = {
            "task_type": "todo",
            "memory_overrides": {
                "disabled_likes": ["咖啡"],
                "disabled_dislikes": ["排队"],
                "session_likes": ["书店"],
                "session_dislikes": ["太赶"],
            },
        }

        with patch(
            "agent.nodes.load_user_profile",
            return_value={
                "user_id": "alice",
                "likes": ["咖啡", "展览"],
                "dislikes": ["排队"],
                "pace": "轻松",
                "budget_style": "中等",
            },
        ):
            result = load_memory(state)

        self.assertEqual(result.constraints["preferences"], ["展览", "书店"])
        self.assertEqual(result.constraints["avoid"], ["太赶"])
        self.assertEqual(result.memory_resolution["applied_likes"], ["展览", "书店"])
        self.assertEqual(result.memory_resolution["applied_dislikes"], ["太赶"])


if __name__ == "__main__":
    unittest.main()
