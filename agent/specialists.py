from __future__ import annotations

import copy
import time
from typing import Any

from langgraph.graph import END, StateGraph

from agent.contracts import AgentProposal, AgentRunRecord, AgentTask
from agent.nodes import (
    _build_dynamic_travel_plan,
    _build_errand_plan,
    _build_meal_plan,
    _build_todo_plan,
    _execute_dynamic_step,
    _plan_has_executable_items,
)
from agent.state import AgentState


SPECIALIST_TOOLS = {
    "travel": ["weather", "place_search", "search", "route", "budget"],
    "meal": ["place_search", "meal_pick", "route", "budget", "confirm_action"],
    "errand": ["place_search", "errand_parse", "route", "budget", "confirm_action"],
    "todo": ["todo_decompose", "confirm_action"],
}


def run_specialist(state: AgentState, task: AgentTask) -> tuple[AgentProposal, AgentRunRecord]:
    graph = SPECIALIST_GRAPHS[task.agent]
    result = graph.invoke({"root_state": state, "task": task, "started_at": time.perf_counter()})
    return result["proposal"], result["run"]


def _build_specialist_graph(agent: str):
    graph = StateGraph(dict)
    graph.add_node("prepare", lambda value: _prepare(value, agent))
    graph.add_node("execute_tools", lambda value: _execute_tools(value, agent))
    graph.add_node("build_proposal", lambda value: _build_proposal(value, agent))
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "execute_tools")
    graph.add_edge("execute_tools", "build_proposal")
    graph.add_edge("build_proposal", END)
    return graph.compile()


def _prepare(graph_state: dict[str, Any], agent: str) -> dict[str, Any]:
    root: AgentState = graph_state["root_state"]
    scoped = copy.deepcopy(root)
    scoped.constraints = copy.deepcopy(root.constraints)
    scoped.constraints["task_type"] = agent
    scoped.intent_contract = copy.deepcopy(root.intent_contract or {})
    scoped.intent_contract["primary_task_type"] = agent
    if agent != "travel":
        scoped.intent_contract["sub_tasks"] = [{"type": agent, "label": agent, "source": "supervisor"}]
    scoped.artifacts = {}
    scoped.tool_results = []
    scoped.candidates = []
    scoped.final_plan = None
    scoped.execution_log = []
    scoped._active_agent = agent  # type: ignore[attr-defined]
    scoped._active_task_id = graph_state["task"].task_id  # type: ignore[attr-defined]
    graph_state["scoped_state"] = scoped
    graph_state["tools_used"] = []
    graph_state["warnings"] = []
    return graph_state


def _execute_tools(graph_state: dict[str, Any], agent: str) -> dict[str, Any]:
    scoped: AgentState = graph_state["scoped_state"]
    for tool in SPECIALIST_TOOLS[agent]:
        if tool not in SPECIALIST_TOOLS[agent]:
            graph_state["warnings"].append(f"tool_not_allowed:{tool}")
            continue
        _execute_dynamic_step(scoped, {"tool": tool})
        graph_state["tools_used"].append(tool)
    return graph_state


def _build_proposal(graph_state: dict[str, Any], agent: str) -> dict[str, Any]:
    scoped: AgentState = graph_state["scoped_state"]
    task: AgentTask = graph_state["task"]
    builders = {
        "travel": _build_dynamic_travel_plan,
        "meal": _build_meal_plan,
        "errand": _build_errand_plan,
        "todo": _build_todo_plan,
    }
    plan = builders[agent](scoped)
    warnings = list(graph_state.get("warnings") or []) + _provider_warnings(scoped.tool_results)
    if not _plan_has_executable_items(plan):
        status = "blocked"
        confidence = 0.2
        warnings.append("missing_executable_items")
    elif warnings:
        status = "degraded"
        confidence = 0.6
    else:
        status = "success"
        confidence = 0.9
    artifacts = copy.deepcopy(scoped.artifacts)
    artifacts["candidates"] = copy.deepcopy(scoped.candidates)
    artifacts["execution_log"] = copy.deepcopy(scoped.execution_log)
    proposal = AgentProposal(
        task_id=task.task_id,
        agent=agent,
        status=status,
        plan_fragment=plan,
        artifacts=artifacts,
        tool_results=copy.deepcopy(scoped.tool_results),
        warnings=warnings,
        confidence=confidence,
    )
    run = AgentRunRecord(
        task_id=task.task_id,
        agent=agent,
        objective=task.objective,
        status=status,
        tools_used=list(graph_state.get("tools_used") or []),
        output_summary=_proposal_summary(plan),
        warnings=warnings,
        latency_ms=int((time.perf_counter() - graph_state["started_at"]) * 1000),
        revision_round=int(graph_state["root_state"].revision_round),
    )
    graph_state["proposal"] = proposal
    graph_state["run"] = run
    return graph_state


def _provider_warnings(tool_results: list[dict[str, Any]]) -> list[str]:
    warnings = []
    for result in tool_results:
        data = result.get("data")
        if isinstance(data, dict):
            if data.get("provider") == "mock":
                warnings.append(f"{result.get('tool_name')}:mock_provider")
            if data.get("provider_warning"):
                warnings.append(str(data["provider_warning"]))
    return list(dict.fromkeys(warnings))


def _proposal_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_type": plan.get("task_type"),
        "itinerary_count": len(plan.get("itinerary") or []),
        "todo_count": len(plan.get("todo_items") or []),
        "meal_count": len(plan.get("meal_candidates") or []),
        "errand_count": len(plan.get("errand_items") or []),
        "budget_total": (plan.get("budget") or {}).get("total"),
    }


SPECIALIST_GRAPHS = {
    agent: _build_specialist_graph(agent)
    for agent in SPECIALIST_TOOLS
}
