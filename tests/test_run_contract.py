from __future__ import annotations

import unittest
from unittest.mock import patch

import agent.graph as graph
from agent.state import AgentState


SUCCESS_KEYS = {
    "status",
    "trace_id",
    "constraints",
    "plan_steps",
    "tool_results",
    "candidates",
    "final_plan",
    "assistant_message",
    "quality_warnings",
    "risks",
    "fallbacks",
    "reflection",
    "llm_usage",
    "execution_log",
    "task_id",
    "trace",
}

CLARIFICATION_KEYS = {
    "status",
    "trace_id",
    "question",
    "constraints",
    "llm_usage",
    "execution_log",
    "trace",
}


class RunLifeOpsContractTest(unittest.TestCase):
    def test_success_response_shape_is_stable(self) -> None:
        def seed_success_state(state: AgentState) -> AgentState:
            state.constraints = {
                "city": "杭州",
                "date_iso": "2026-06-06",
                "budget": 500,
                "preferences": ["展览"],
            }
            state.plan_steps = [{"step": "生成计划", "tool": "llm"}]
            state.tool_results = [{"tool_name": "weather_tool", "status": "success", "data": {}}]
            state.candidates = [{"name": "浙江美术馆", "score": 90}]
            state.final_plan = {
                "title": "杭州一日计划",
                "goal": "杭州轻松玩一天",
                "date": "2026-06-06",
                "weather": {"condition": "多云"},
                "travel_research": {"sources": []},
                "itinerary": [
                    {
                        "time": "10:00-12:00",
                        "place": "浙江美术馆",
                        "address": "杭州",
                        "play_points": ["看展"],
                        "cost": 0,
                        "cost_known": True,
                    }
                ],
                "budget": {
                    "activity_cost": 0,
                    "meal_budget": 120,
                    "transport_budget": 60,
                    "total": 180,
                    "budget_limit": 500,
                    "unknown_activity_cost_items": [],
                },
                "risks": [],
                "fallbacks": [],
            }
            state.reflection = {"passed": True, "issues": [], "next_action": "final"}
            state.execution_log.append({"node": "contract_seed", "summary": "seed", "details": {}})
            return state

        with patch.object(graph, "NODES", [("contract_seed", seed_success_state)]), \
            patch.object(graph, "save_task_history", lambda *_args, **_kwargs: "task_contract"), \
            patch.object(graph, "load_trace", lambda _trace_id: []):
            result = graph.run_lifeops("周六杭州玩一天")

        self.assertTrue(SUCCESS_KEYS.issubset(set(result)))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], "task_contract")
        self.assertIsInstance(result["trace_id"], str)
        self.assertIsInstance(result["constraints"], dict)
        self.assertIsInstance(result["plan_steps"], list)
        self.assertIsInstance(result["tool_results"], list)
        self.assertIsInstance(result["candidates"], list)
        self.assertIsInstance(result["final_plan"], dict)
        self.assertIsInstance(result["assistant_message"], str)
        self.assertIsInstance(result["quality_warnings"], list)
        self.assertIsInstance(result["risks"], list)
        self.assertIsInstance(result["fallbacks"], list)
        self.assertIsInstance(result["reflection"], dict)
        self.assertIsInstance(result["llm_usage"], list)
        self.assertIsInstance(result["execution_log"], list)
        self.assertIsInstance(result["trace"], list)

    def test_clarification_response_shape_is_stable(self) -> None:
        def seed_clarification_state(state: AgentState) -> AgentState:
            state.constraints = {"date": "周末"}
            state.clarification_question = "还需要补充：城市"
            state.execution_log.append({"node": "contract_seed", "summary": "seed", "details": {}})
            return state

        with patch.object(graph, "NODES", [("contract_seed", seed_clarification_state)]), \
            patch.object(graph, "load_trace", lambda _trace_id: []):
            result = graph.run_lifeops("帮我安排周末")

        self.assertEqual(CLARIFICATION_KEYS, set(result))
        self.assertEqual(result["status"], "need_clarification")
        self.assertIsInstance(result["trace_id"], str)
        self.assertIsInstance(result["question"], str)
        self.assertIsInstance(result["constraints"], dict)
        self.assertIsInstance(result["llm_usage"], list)
        self.assertIsInstance(result["execution_log"], list)
        self.assertIsInstance(result["trace"], list)


if __name__ == "__main__":
    unittest.main()
