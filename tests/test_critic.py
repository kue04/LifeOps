from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.critic import critic_node
from agent.state import AgentState


class CriticTest(unittest.TestCase):
    def test_meal_issue_targets_only_meal_agent(self) -> None:
        state = AgentState(user_input="杭州玩一天并吃火锅")
        state.agent_tasks = [
            {"task_id": "task_travel", "agent": "travel", "objective": "旅行"},
            {"task_id": "task_meal", "agent": "meal", "objective": "餐饮"},
        ]

        def failed_reflection(value: AgentState) -> AgentState:
            value.reflection = {
                "passed": False,
                "issues": ["没有生成有效餐饮候选"],
                "next_action": "replan",
                "review": "需要重新安排餐饮",
            }
            return value

        with patch("agent.critic.reflect", side_effect=failed_reflection):
            result = critic_node(state)

        self.assertEqual(result.critic_decision["next_action"], "revise")
        self.assertEqual(result.critic_decision["revision_targets"], ["meal"])


if __name__ == "__main__":
    unittest.main()
