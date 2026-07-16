from __future__ import annotations

import unittest

from pydantic import ValidationError

from agent.contracts import AgentProposal, AgentTask, SupervisorDecision


class AgentContractTest(unittest.TestCase):
    def test_agent_task_rejects_unknown_agent(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(
                task_id="task_unknown",
                agent="finance",
                objective="处理预算",
            )

    def test_agent_proposal_rejects_confidence_outside_range(self) -> None:
        with self.assertRaises(ValidationError):
            AgentProposal(
                task_id="task_travel",
                agent="travel",
                status="success",
                confidence=1.5,
            )

    def test_supervisor_decision_accepts_mixed_tasks(self) -> None:
        decision = SupervisorDecision(
            primary_task_type="travel",
            tasks=[
                AgentTask(task_id="task_travel", agent="travel", objective="安排游玩"),
                AgentTask(task_id="task_meal", agent="meal", objective="安排火锅"),
            ],
            strategy="先规划游玩，再补餐饮",
        )

        self.assertEqual([item.agent for item in decision.tasks], ["travel", "meal"])


if __name__ == "__main__":
    unittest.main()
