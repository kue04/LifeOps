from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import patch

import agent.graph as graph
from agent.state import AgentState


class LangGraphBranchTest(unittest.TestCase):
    def test_clarification_branch_stops_before_tools(self) -> None:
        calls: list[str] = []

        def need_clarification(state: AgentState) -> AgentState:
            calls.append("need_clarification")
            state.clarification_question = "还需要补充：城市"
            state.execution_log.append({"node": "need_clarification", "summary": "ask", "details": {}})
            return state

        def tool_router(state: AgentState) -> AgentState:
            calls.append("tool_router")
            raise AssertionError("tool_router should not run when clarification is needed")

        nodes = [
            ("need_clarification", need_clarification),
            ("tool_router", tool_router),
        ]

        with patch.object(graph, "NODES", nodes), \
            patch.object(graph, "load_trace", lambda _trace_id: []):
            result = graph.run_lifeops("帮我安排周末")

        self.assertEqual(result["status"], "need_clarification")
        self.assertEqual(calls, ["need_clarification"])
        self.assertIn("城市", result["question"])

    def test_reflection_replan_branch_loops_once_to_tool_chain(self) -> None:
        calls = {"tool": 0, "score": 0, "plan": 0, "risk": 0, "reflection": 0}

        def tool_router(state: AgentState) -> AgentState:
            calls["tool"] += 1
            state.tool_results.append({"tool_name": "mock_tool", "status": "success"})
            state.execution_log.append({"node": "tool_router", "summary": "tool", "details": {}})
            return state

        def candidate_scorer(state: AgentState) -> AgentState:
            calls["score"] += 1
            state.candidates = [{"name": "候选", "score": 90}]
            state.execution_log.append({"node": "candidate_scorer", "summary": "score", "details": {}})
            return state

        def plan_generator(state: AgentState) -> AgentState:
            calls["plan"] += 1
            state.final_plan = {
                "version": calls["plan"],
                "itinerary": [{"time": "10:00-11:00", "place": "候选"}],
                "budget": {"total": 0},
            }
            state.execution_log.append({"node": "plan_generator", "summary": "plan", "details": {}})
            return state

        def risk_checker(state: AgentState) -> AgentState:
            calls["risk"] += 1
            state.execution_log.append({"node": "risk_checker", "summary": "risk", "details": {}})
            return state

        def reflection(state: AgentState) -> AgentState:
            calls["reflection"] += 1
            if calls["reflection"] == 1:
                state.reflection = {
                    "passed": False,
                    "issues": ["需要补齐路线"],
                    "next_action": "replan",
                }
            else:
                state.reflection = {"passed": True, "issues": [], "next_action": "final"}
            state.execution_log.append({"node": "reflection", "summary": "reflect", "details": state.reflection})
            return state

        @contextmanager
        def traced(*_args, **_kwargs):
            yield {}

        nodes = [
            ("tool_router", tool_router),
            ("candidate_scorer", candidate_scorer),
            ("plan_generator", plan_generator),
            ("risk_checker", risk_checker),
            ("reflection", reflection),
        ]
        events = []

        with patch.object(graph, "NODES", nodes), \
            patch.object(graph, "traced", traced), \
            patch.object(graph, "save_task_history", lambda *_args, **_kwargs: "task-id"), \
            patch.object(graph, "load_trace", lambda _trace_id: []):
            result = graph.run_lifeops("明天杭州玩一天", progress_callback=events.append)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["final_plan"]["version"], 2)
        self.assertEqual(calls, {"tool": 2, "score": 2, "plan": 2, "risk": 2, "reflection": 2})
        self.assertEqual(result["reflection"]["next_action"], "final")
        self.assertEqual(
            [item["node"] for item in result["execution_log"]].count("reflection_replan"),
            1,
        )
        self.assertTrue(any(event["node"] == "reflection_replan" for event in events))
        self.assertTrue(any(event.get("details", {}).get("round") == "auto_replan" for event in events))

    def test_task_router_sends_todo_to_todo_branch(self) -> None:
        calls: list[str] = []

        def planner(state: AgentState) -> AgentState:
            calls.append("planner")
            state.constraints["task_type"] = "todo"
            state.execution_log.append({"node": "planner", "summary": "plan", "details": {}})
            return state

        def task_router(state: AgentState) -> AgentState:
            calls.append("task_router")
            state.execution_log.append({"node": "task_router", "summary": "route", "details": {"task_type": "todo"}})
            return state

        def todo_decomposer(state: AgentState) -> AgentState:
            calls.append("todo_decomposer")
            state.execution_log.append({"node": "todo_decomposer", "summary": "todo", "details": {}})
            return state

        def todo_plan_generator(state: AgentState) -> AgentState:
            calls.append("todo_plan_generator")
            state.final_plan = {"task_type": "todo", "itinerary": [{"time": "09:00-09:30", "place": "任务"}], "budget": {}}
            state.execution_log.append({"node": "todo_plan_generator", "summary": "todo plan", "details": {}})
            return state

        def travel_tool_router(state: AgentState) -> AgentState:
            raise AssertionError("travel branch should not run for todo")

        def risk_checker(state: AgentState) -> AgentState:
            calls.append("risk_checker")
            state.execution_log.append({"node": "risk_checker", "summary": "risk", "details": {}})
            return state

        def reflection(state: AgentState) -> AgentState:
            calls.append("reflection")
            state.reflection = {"passed": True, "issues": [], "next_action": "final"}
            state.execution_log.append({"node": "reflection", "summary": "reflect", "details": state.reflection})
            return state

        @contextmanager
        def traced(*_args, **_kwargs):
            yield {}

        nodes = [
            ("constraint_extractor", lambda state: state),
            ("date_resolver", lambda state: state),
            ("load_memory", lambda state: state),
            ("need_clarification", lambda state: state),
            ("planner", planner),
            ("task_router", task_router),
            ("travel_tool_router", travel_tool_router),
            ("travel_candidate_scorer", lambda state: state),
            ("travel_plan_generator", lambda state: state),
            ("errand_tool_router", lambda state: state),
            ("errand_candidate_scorer", lambda state: state),
            ("errand_plan_generator", lambda state: state),
            ("meal_tool_router", lambda state: state),
            ("meal_candidate_scorer", lambda state: state),
            ("meal_plan_generator", lambda state: state),
            ("todo_decomposer", todo_decomposer),
            ("todo_plan_generator", todo_plan_generator),
            ("risk_checker", risk_checker),
            ("reflection", reflection),
        ]

        with patch.object(graph, "NODES", nodes), \
            patch.object(graph, "traced", traced), \
            patch.object(graph, "save_task_history", lambda *_args, **_kwargs: "task-id"), \
            patch.object(graph, "load_trace", lambda _trace_id: []):
            result = graph.run_lifeops("todo")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["final_plan"]["task_type"], "todo")
        self.assertEqual(calls, ["planner", "task_router", "todo_decomposer", "todo_plan_generator", "risk_checker", "reflection"])


if __name__ == "__main__":
    unittest.main()
