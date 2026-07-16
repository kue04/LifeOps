from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.contracts import AgentProposal, AgentRunRecord
from agent.graph import run_lifeops
from agent.multi_agent import agent_dispatch_node
from agent.state import AgentState


class MultiAgentFlowTest(unittest.TestCase):
    def test_mixed_request_runs_travel_and_meal_agents(self) -> None:
        result = run_lifeops("周六杭州轻松玩一天，预算 500，喜欢展览，晚上吃火锅。")

        self.assertEqual(result["planner_meta"]["source"], "rule_fallback")
        self.assertEqual({item["agent"] for item in result["agent_runs"]}, {"travel", "meal"})
        self.assertEqual(result["final_plan"]["task_type"], "mixed")
        self.assertIn("critic", result)
        self.assertTrue(result["final_plan"]["itinerary"])

    def test_budget_followup_preserves_agent_set(self) -> None:
        first = run_lifeops("周六杭州玩一天，晚上吃火锅，预算 500。")

        second = run_lifeops("太贵了，控制在 300。", previous_result=first)

        self.assertEqual({item["agent"] for item in second["agent_runs"]}, {"travel", "meal"})
        self.assertLessEqual(second["final_plan"]["budget"]["total"], 300)

    def test_todo_request_runs_only_todo_agent(self) -> None:
        result = run_lifeops("把准备面试拆成待办和时间块。")

        self.assertEqual([item["agent"] for item in result["agent_runs"]], ["todo"])
        self.assertEqual(result["final_plan"]["task_type"], "todo")
        self.assertTrue(result["final_plan"]["todo_items"])

    def test_internal_revision_reruns_only_target_agent(self) -> None:
        state = AgentState(user_input="杭州玩一天并吃火锅")
        state.revision_round = 1
        state.replan_context = {"revision_targets": ["meal"], "issues": ["餐饮候选不足"]}
        state.agent_tasks = [
            {"task_id": "task_travel", "agent": "travel", "objective": "规划旅行"},
            {"task_id": "task_meal", "agent": "meal", "objective": "规划餐饮"},
        ]
        travel_proposal = AgentProposal(
            task_id="task_travel",
            agent="travel",
            status="success",
            plan_fragment={"task_type": "travel", "itinerary": [{"place": "西湖"}]},
        ).model_dump()
        old_meal_proposal = AgentProposal(
            task_id="task_meal",
            agent="meal",
            status="blocked",
        ).model_dump()
        state.agent_proposals = [travel_proposal, old_meal_proposal]
        state.agent_runs = [
            AgentRunRecord(
                task_id="task_travel",
                agent="travel",
                objective="规划旅行",
                status="success",
                revision_round=0,
            ).model_dump(),
            AgentRunRecord(
                task_id="task_meal",
                agent="meal",
                objective="规划餐饮",
                status="blocked",
                revision_round=0,
            ).model_dump(),
        ]
        revised_proposal = AgentProposal(
            task_id="task_meal",
            agent="meal",
            status="success",
            plan_fragment={"task_type": "meal", "meal_candidates": [{"name": "火锅店"}]},
        )
        revised_run = AgentRunRecord(
            task_id="task_meal",
            agent="meal",
            objective="规划餐饮",
            status="success",
            tools_used=["place_search", "meal_pick"],
            revision_round=1,
        )

        with patch("agent.specialists.run_specialist", return_value=(revised_proposal, revised_run)) as runner:
            result = agent_dispatch_node(state)

        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.args[1].agent, "meal")
        self.assertEqual({item["agent"] for item in result.agent_proposals}, {"travel", "meal"})
        self.assertEqual(len(result.agent_runs), 3)


if __name__ == "__main__":
    unittest.main()
