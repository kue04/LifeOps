from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.multi_agent import (
    build_rule_supervisor_decision,
    supervisor_node,
    validate_supervisor_decision,
)
from agent.state import AgentState


def mixed_state() -> AgentState:
    state = AgentState(user_input="周六杭州玩一天，晚上吃火锅")
    state.constraints = {"task_type": "travel", "city": "杭州", "budget": 500}
    state.intent_contract = {
        "goal": "杭州游玩并吃火锅",
        "primary_task_type": "travel",
        "sub_tasks": [
            {"type": "travel", "label": "出行"},
            {"type": "meal", "label": "餐饮"},
        ],
        "required_outputs": ["itinerary", "route", "budget", "meal_candidates"],
    }
    return state


class SupervisorTest(unittest.TestCase):
    def test_rule_supervisor_delegates_each_intent_once(self) -> None:
        decision = build_rule_supervisor_decision(mixed_state())

        self.assertEqual([item.agent for item in decision.tasks], ["travel", "meal"])
        self.assertEqual(len({item.task_id for item in decision.tasks}), 2)

    def test_validation_rejects_missing_intent_agent(self) -> None:
        state = mixed_state()
        decision = build_rule_supervisor_decision(state)
        decision.tasks = [decision.tasks[0]]

        errors = validate_supervisor_decision(decision, state)

        self.assertTrue(any("meal" in item for item in errors))

    def test_validation_rejects_dependency_cycle(self) -> None:
        state = mixed_state()
        decision = build_rule_supervisor_decision(state)
        decision.tasks[0].depends_on = [decision.tasks[1].task_id]
        decision.tasks[1].depends_on = [decision.tasks[0].task_id]

        errors = validate_supervisor_decision(decision, state)

        self.assertTrue(any("循环" in item for item in errors))

    def test_invalid_llm_decision_falls_back_to_rule_supervisor(self) -> None:
        state = mixed_state()
        invalid = {
            "primary_task_type": "meal",
            "tasks": [
                {
                    "task_id": "task_meal",
                    "agent": "meal",
                    "objective": "只安排火锅",
                    "depends_on": [],
                    "required_outputs": ["meal_candidates"],
                    "context": {},
                }
            ],
            "strategy": "忽略旅行",
        }

        with patch("agent.multi_agent._llm_enabled", return_value=True), patch(
            "agent.multi_agent.llm_client.json_complete", return_value=invalid
        ):
            result = supervisor_node(state)

        self.assertEqual(result.planner_meta["source"], "rule_fallback")
        self.assertEqual([item["agent"] for item in result.agent_tasks], ["travel", "meal"])
        self.assertTrue(result.planner_meta["validation_errors"])

    def test_valid_llm_decision_is_used(self) -> None:
        state = mixed_state()
        valid = {
            "primary_task_type": "travel",
            "tasks": [
                {
                    "task_id": "task_travel",
                    "agent": "travel",
                    "objective": "安排杭州游玩",
                    "depends_on": [],
                    "required_outputs": ["itinerary", "route", "budget"],
                    "context": {},
                },
                {
                    "task_id": "task_meal",
                    "agent": "meal",
                    "objective": "安排火锅",
                    "depends_on": ["task_travel"],
                    "required_outputs": ["meal_candidates"],
                    "context": {},
                },
            ],
            "strategy": "先旅行后用餐",
        }

        with patch("agent.multi_agent._llm_enabled", return_value=True), patch(
            "agent.multi_agent.llm_client.json_complete", return_value=valid
        ):
            result = supervisor_node(state)

        self.assertEqual(result.planner_meta["source"], "llm")
        self.assertEqual(result.planner_meta["strategy"], "先旅行后用餐")
        self.assertEqual([item["agent"] for item in result.agent_tasks], ["travel", "meal"])


if __name__ == "__main__":
    unittest.main()
