from __future__ import annotations

import unittest

from agent.contracts import AgentTask
from agent.specialists import SPECIALIST_TOOLS, run_specialist
from agent.state import AgentState


def state_for(agent: str, text: str) -> AgentState:
    state = AgentState(user_input=text)
    state.goal = text
    state.constraints = {
        "task_type": agent,
        "city": "杭州",
        "budget": 500,
        "preferences": ["展览"] if agent == "travel" else ["美食"] if agent == "meal" else [],
        "avoid": [],
        "pace": "轻松",
    }
    state.intent_contract = {
        "goal": text,
        "primary_task_type": agent,
        "sub_tasks": [{"type": agent, "label": agent}],
        "required_outputs": [],
    }
    return state


class SpecialistAgentTest(unittest.TestCase):
    def test_tool_allowlists_match_domain_boundaries(self) -> None:
        self.assertEqual(
            SPECIALIST_TOOLS["travel"],
            ["weather", "place_search", "search", "route", "budget"],
        )
        self.assertNotIn("weather", SPECIALIST_TOOLS["meal"])
        self.assertNotIn("search", SPECIALIST_TOOLS["errand"])
        self.assertEqual(SPECIALIST_TOOLS["todo"], ["todo_decompose", "confirm_action"])

    def test_todo_agent_does_not_call_location_tools(self) -> None:
        state = state_for("todo", "把准备面试拆成待办")
        task = AgentTask(task_id="task_todo", agent="todo", objective="拆解待办")

        proposal, run = run_specialist(state, task)

        self.assertEqual(run.tools_used, ["todo_decompose", "confirm_action"])
        self.assertEqual(proposal.agent, "todo")
        self.assertTrue(proposal.plan_fragment["todo_items"])
        self.assertEqual(state.artifacts, {})
        self.assertEqual(state.tool_results, [])

    def test_travel_agent_returns_route_budget_and_tool_evidence(self) -> None:
        state = state_for("travel", "周六杭州轻松玩一天，喜欢展览")
        task = AgentTask(task_id="task_travel", agent="travel", objective="规划出行")

        proposal, run = run_specialist(state, task)

        self.assertEqual(run.tools_used, SPECIALIST_TOOLS["travel"])
        self.assertIn(proposal.status, {"success", "degraded"})
        self.assertTrue(proposal.plan_fragment["itinerary"])
        self.assertIn("budget", proposal.plan_fragment)
        self.assertTrue(proposal.tool_results)

    def test_meal_agent_skips_weather_and_web_search(self) -> None:
        state = state_for("meal", "杭州找一家餐厅吃饭")
        task = AgentTask(task_id="task_meal", agent="meal", objective="安排餐饮")

        proposal, run = run_specialist(state, task)

        self.assertNotIn("weather", run.tools_used)
        self.assertNotIn("search", run.tools_used)
        self.assertEqual(proposal.agent, "meal")


if __name__ == "__main__":
    unittest.main()
