from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import patch

from agent import graph
from agent.nodes import _filter_reflection_blocked_places, final_response
from agent.state import AgentState


class ReflectionReplanTest(unittest.TestCase):
    def test_reflection_replan_runs_once_before_final_response(self) -> None:
        calls = {"candidate": 0, "plan": 0, "risk": 0, "reflection": 0}

        def candidate_scorer(state):
            calls["candidate"] += 1
            state.execution_log.append({"node": "candidate_scorer", "summary": "score", "details": {}})
            return state

        def plan_generator(state):
            calls["plan"] += 1
            state.final_plan = {"version": calls["plan"], "itinerary": [], "budget": {}}
            state.execution_log.append({"node": "plan_generator", "summary": "plan", "details": {}})
            return state

        def risk_checker(state):
            calls["risk"] += 1
            state.execution_log.append({"node": "risk_checker", "summary": "risk", "details": {}})
            return state

        def reflection(state):
            calls["reflection"] += 1
            if calls["reflection"] == 1:
                state.reflection = {
                    "passed": False,
                    "issues": ["计划只覆盖了一天"],
                    "next_action": "replan",
                    "review": "缺少第二天的行程",
                }
            else:
                state.reflection = {
                    "passed": True,
                    "issues": [],
                    "next_action": "final",
                    "review": "已补齐",
                }
            state.execution_log.append({"node": "reflection", "summary": "reflect", "details": state.reflection})
            return state

        def final_response(state):
            return {
                "status": "success",
                "trace_id": state.trace_id,
                "final_plan": state.final_plan,
                "reflection": state.reflection,
                "execution_log": state.execution_log,
                "replan_count": state.replan_count,
            }

        @contextmanager
        def traced(*_args, **_kwargs):
            yield {}

        nodes = [
            ("candidate_scorer", candidate_scorer),
            ("plan_generator", plan_generator),
            ("risk_checker", risk_checker),
            ("reflection", reflection),
        ]

        events = []

        with patch.object(graph, "NODES", nodes), \
            patch.object(graph, "traced", traced), \
            patch.object(graph, "final_response", final_response), \
            patch.object(graph, "save_task_history", lambda *_args, **_kwargs: "task-id"), \
            patch.object(graph, "load_trace", lambda _trace_id: []):
            result = graph.run_lifeops("明天去长沙玩两天", progress_callback=events.append)

        self.assertEqual(result["final_plan"]["version"], 2)
        self.assertEqual(result["reflection"]["next_action"], "final")
        self.assertEqual(result["replan_count"], 1)
        self.assertEqual(calls, {"candidate": 2, "plan": 2, "risk": 2, "reflection": 2})
        self.assertEqual(
            [item["node"] for item in result["execution_log"]].count("reflection_replan"),
            1,
        )
        replan_events = [event for event in events if event["node"] == "reflection_replan"]
        self.assertEqual(replan_events[0]["status"], "running")
        self.assertEqual(replan_events[0]["details"]["round"], "auto_replan")
        second_round = [
            event for event in events
            if event["node"] == "plan_generator"
            and event["status"] == "done"
            and event.get("details", {}).get("round") == "auto_replan"
        ]
        self.assertEqual(len(second_round), 1)

    def test_final_response_marks_failed_second_review_partial(self) -> None:
        state = AgentState(user_input="明天去厦门玩一天，想去奶茶店")
        state.final_plan = {
            "title": "厦门轻松一日游",
            "itinerary": [{"time": "10:00-11:00", "place": "中山路"}],
            "budget": {},
        }
        state.reflection = {
            "passed": False,
            "issues": ["计划中未推荐任何奶茶店，不符合用户目标"],
            "next_action": "replan",
            "review": "仍缺少目标偏好",
        }

        result = final_response(state)

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["quality_warnings"], ["计划中未推荐任何奶茶店，不符合用户目标"])
        self.assertIn("当前方案未完全满足", result["assistant_message"])

    def test_replan_filters_reflection_blocked_places(self) -> None:
        candidates = [
            {"name": "福建省源古历史博物馆", "estimated_cost": 0, "tags": []},
            {"name": "沙坡尾", "estimated_cost": 0, "tags": []},
        ]
        replan_context = {
            "issues": ["福建省源古历史博物馆(暂停开放)不能安排游览"],
        }

        filtered = _filter_reflection_blocked_places(candidates, replan_context)

        self.assertEqual([item["name"] for item in filtered], ["沙坡尾"])


if __name__ == "__main__":
    unittest.main()
