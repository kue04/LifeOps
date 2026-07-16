from __future__ import annotations

import json
import copy
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from agent.contracts import AgentTask, SupervisorDecision
from agent.prompts import SUPERVISOR_PROMPT
from agent.state import AgentState
from config import settings
from services.llm_client import llm_client
from tools.budget import estimate_budget
from tools.route import estimate_route


AGENT_OUTPUTS = {
    "travel": ["itinerary", "route", "budget"],
    "meal": ["meal_candidates", "itinerary", "budget"],
    "errand": ["errand_items", "itinerary", "route"],
    "todo": ["todo_items", "time_blocks", "acceptance_criteria"],
}


def build_rule_supervisor_decision(state: AgentState) -> SupervisorDecision:
    contract = state.intent_contract or {}
    sub_tasks = contract.get("sub_tasks") or []
    agents = []
    for item in sub_tasks:
        agent = str(item.get("type") or "")
        if agent in AGENT_OUTPUTS and agent not in agents:
            agents.append(agent)
    if not agents:
        fallback = str(contract.get("primary_task_type") or state.constraints.get("task_type") or "todo")
        agents = [fallback if fallback in AGENT_OUTPUTS else "todo"]
    tasks = [
        AgentTask(
            task_id=f"task_{agent}_{index}",
            agent=agent,
            objective=_agent_objective(agent, state),
            depends_on=[],
            required_outputs=list(AGENT_OUTPUTS[agent]),
            context={"goal": contract.get("goal"), "constraints": state.constraints},
        )
        for index, agent in enumerate(agents, start=1)
    ]
    primary = str(contract.get("primary_task_type") or agents[0])
    if primary not in AGENT_OUTPUTS:
        primary = agents[0]
    return SupervisorDecision(
        primary_task_type=primary,
        tasks=tasks,
        strategy="按意图合同委派专项 Agent，并使用结构化提案合并结果",
    )


def validate_supervisor_decision(decision: SupervisorDecision, state: AgentState) -> list[str]:
    errors: list[str] = []
    task_ids = [task.task_id for task in decision.tasks]
    if len(task_ids) != len(set(task_ids)):
        errors.append("task_id 重复")
    expected_agents = {
        str(item.get("type"))
        for item in (state.intent_contract or {}).get("sub_tasks", [])
        if str(item.get("type")) in AGENT_OUTPUTS
    }
    actual_agents = {task.agent for task in decision.tasks}
    for agent in sorted(expected_agents - actual_agents):
        errors.append(f"缺少 {agent} Agent")
    expected_primary = str((state.intent_contract or {}).get("primary_task_type") or "")
    if expected_primary in AGENT_OUTPUTS and decision.primary_task_type != expected_primary:
        errors.append(f"primary_task_type 应保持为 {expected_primary}")
    known_ids = set(task_ids)
    for task in decision.tasks:
        for dependency in task.depends_on:
            if dependency not in known_ids:
                errors.append(f"依赖不存在：{dependency}")
    if _has_dependency_cycle(decision.tasks):
        errors.append("AgentTask 依赖存在循环")
    return errors


def supervisor_node(state: AgentState) -> AgentState:
    fallback_reason: str | None = None
    validation_errors: list[str] = []
    decision: SupervisorDecision | None = None
    if _llm_enabled():
        try:
            raw = llm_client.json_complete(
                SUPERVISOR_PROMPT,
                json.dumps(
                    {
                        "user_input": state.user_input,
                        "constraints": state.constraints,
                        "intent_contract": state.intent_contract,
                        "previous_intent_contract": state.previous_intent_contract,
                        "memory_resolution": state.memory_resolution,
                    },
                    ensure_ascii=False,
                ),
            )
            decision = SupervisorDecision.model_validate(raw)
            validation_errors = validate_supervisor_decision(decision, state)
            if validation_errors:
                fallback_reason = "llm_decision_invalid"
                decision = None
        except (ValidationError, ValueError, TypeError) as exc:
            fallback_reason = "llm_schema_invalid"
            validation_errors = [str(exc)]
        except Exception as exc:
            fallback_reason = "llm_error"
            validation_errors = [str(exc)]
    else:
        fallback_reason = "llm_disabled"

    source = "llm"
    if decision is None:
        decision = build_rule_supervisor_decision(state)
        source = "rule_fallback"
    state.supervisor_decision = decision.model_dump()
    state.agent_tasks = [task.model_dump() for task in decision.tasks]
    state.planner_meta = {
        "source": source,
        "model": _llm_model_name() if source == "llm" else None,
        "fallback_reason": fallback_reason,
        "validation_errors": validation_errors,
        "strategy": decision.strategy,
    }
    state.execution_plan = [
        {
            "id": task.task_id,
            "task_id": task.task_id,
            "agent": task.agent,
            "tool": f"{task.agent}_agent",
            "purpose": task.objective,
            "depends_on": task.depends_on,
            "status": "pending",
        }
        for task in decision.tasks
    ]
    state.plan_steps = [
        {
            "step": task.objective,
            "tool": f"{task.agent}_agent",
            "agent": task.agent,
            "task_id": task.task_id,
            "status": "pending",
        }
        for task in decision.tasks
    ]
    state.execution_log.append(
        {
            "node": "planner",
            "summary": "Supervisor 已生成 Agent 委派计划",
            "details": {
                "planner_meta": state.planner_meta,
                "agent_tasks": state.agent_tasks,
            },
        }
    )
    return state


def agent_dispatch_node(state: AgentState) -> AgentState:
    from agent.contracts import AgentTask
    from agent.specialists import run_specialist

    all_tasks = [AgentTask.model_validate(item) for item in state.agent_tasks]
    revision_targets = set(state.replan_context.get("revision_targets") or []) if state.revision_round else set()
    if revision_targets:
        state.agent_proposals = [
            item for item in state.agent_proposals
            if item.get("agent") not in revision_targets
        ]
        state.tool_results = [
            tool
            for proposal in state.agent_proposals
            for tool in proposal.get("tool_results") or []
        ]
        tasks = [task for task in all_tasks if task.agent in revision_targets]
    else:
        state.agent_proposals = []
        state.agent_runs = []
        state.tool_results = []
        tasks = all_tasks
    completed: set[str] = {
        task.task_id for task in all_tasks
        if task not in tasks
    }
    pending = list(tasks)
    while pending:
        ready = [task for task in pending if set(task.depends_on).issubset(completed)]
        if not ready:
            raise RuntimeError("AgentTask dependency graph cannot be resolved")
        for task in ready:
            _emit_agent_event(state, task, "agent_started", "running")
            proposal, run = run_specialist(state, task)
            state.agent_proposals.append(proposal.model_dump())
            state.agent_runs.append(run.model_dump())
            state.tool_results.extend(proposal.tool_results)
            state.execution_log.extend(proposal.artifacts.get("execution_log") or [])
            completed.add(task.task_id)
            pending.remove(task)
            _emit_agent_event(
                state,
                task,
                "agent_completed",
                "done" if proposal.status != "blocked" else "error",
                {"status": proposal.status, "output_summary": run.output_summary, "warnings": run.warnings},
            )
    latest_runs = {}
    for run in state.agent_runs:
        latest_runs[run.get("agent")] = run
    task_by_agent = {task.agent: task for task in all_tasks}
    state.execution_plan = [
        {
            "id": f"{task_by_agent[agent].task_id}:{tool}",
            "task_id": task_by_agent[agent].task_id,
            "agent": agent,
            "tool": tool,
            "purpose": task_by_agent[agent].objective,
            "depends_on": task_by_agent[agent].depends_on,
            "status": "completed" if run.get("status") != "blocked" else "failed",
        }
        for agent, run in latest_runs.items()
        if agent in task_by_agent
        for tool in run.get("tools_used") or []
    ]
    state.plan_steps = [
        {
            "step": item.get("purpose"),
            "tool": item.get("tool"),
            "agent": item.get("agent"),
            "task_id": item.get("task_id"),
            "status": item.get("status"),
        }
        for item in state.execution_plan
    ]
    state.execution_log.append(
        {
            "node": "execute_plan",
            "summary": "专项 Agent 已完成委派任务",
            "details": {"agent_runs": state.agent_runs},
        }
    )
    return state


def compose_node(state: AgentState) -> AgentState:
    from agent.nodes import _build_mixed_plan

    proposals = [item for item in state.agent_proposals if item.get("status") != "blocked"]
    if not proposals:
        state.final_plan = None
        return state
    if len(proposals) == 1:
        state.final_plan = copy.deepcopy(proposals[0].get("plan_fragment") or {})
    else:
        state.artifacts = _merge_proposal_artifacts(proposals, state)
        state.candidates = list(state.artifacts.get("candidates") or [])
        task_types = {str(item.get("agent")) for item in proposals}
        state.final_plan = _build_mixed_plan(state, task_types)
    if state.final_plan is not None:
        state.final_plan["intent_contract"] = state.intent_contract
        state.final_plan["execution_plan"] = state.execution_plan
        state.final_plan["agent_tasks"] = state.agent_tasks
        state.final_plan["planner_meta"] = state.planner_meta
        state.final_plan["agent_runs"] = state.agent_runs
        state.final_plan["memory_resolution"] = state.memory_resolution
    state.execution_log.append(
        {
            "node": "synthesize_plan",
            "summary": "Composer 已合并 Agent Proposal",
            "details": {"proposal_count": len(proposals), "task_type": (state.final_plan or {}).get("task_type")},
        }
    )
    return state


def _merge_proposal_artifacts(proposals: list[dict[str, Any]], state: AgentState) -> dict[str, Any]:
    from agent.nodes import _constrain_mixed_budget

    merged: dict[str, Any] = {
        "places": [],
        "meal_candidates": [],
        "errand_items": [],
        "confirm_actions": [],
        "candidates": [],
        "lifestyle_places": {"foods": [], "hotels": []},
    }
    route_places: list[dict[str, Any]] = []
    for proposal in proposals:
        artifacts = proposal.get("artifacts") or {}
        fragment = proposal.get("plan_fragment") or {}
        for key in ["places", "meal_candidates", "errand_items", "confirm_actions", "candidates"]:
            merged[key].extend(copy.deepcopy(artifacts.get(key) or fragment.get(key) or []))
        if artifacts.get("todo"):
            merged["todo"] = copy.deepcopy(artifacts["todo"])
        lifestyle = artifacts.get("lifestyle_places") or fragment.get("lifestyle_places") or {}
        merged["lifestyle_places"]["foods"].extend(copy.deepcopy(lifestyle.get("foods") or []))
        merged["lifestyle_places"]["hotels"].extend(copy.deepcopy(lifestyle.get("hotels") or []))
        for key in ["weather", "search_results", "travel_research"]:
            if artifacts.get(key) and not merged.get(key):
                merged[key] = copy.deepcopy(artifacts[key])
        route_places.extend(copy.deepcopy((artifacts.get("route") or {}).get("ordered_places") or []))
    route_places = _dedupe_places(route_places)
    route = estimate_route(route_places) if route_places else {"ordered_places": [], "legs": [], "travel_minutes": 0, "provider": "none"}
    merged["route"] = route
    budget = estimate_budget(route.get("ordered_places") or [], state.constraints.get("budget"), state.constraints.get("pace"))
    merged["budget"] = _constrain_mixed_budget(budget, state.constraints.get("budget"))
    merged["places"] = _dedupe_places(merged["places"])
    merged["meal_candidates"] = _dedupe_places(merged["meal_candidates"])
    merged["candidates"] = _dedupe_places(merged["candidates"])
    merged["lifestyle_places"]["foods"] = _dedupe_places(merged["lifestyle_places"]["foods"])
    merged["lifestyle_places"]["hotels"] = _dedupe_places(merged["lifestyle_places"]["hotels"])
    merged["confirm_actions"] = _dedupe_actions(merged["confirm_actions"])
    return merged


def _dedupe_places(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in items:
        key = (item.get("name") or item.get("title"), item.get("location"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_actions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in items:
        key = (item.get("type") or item.get("action_type"), item.get("label"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _emit_agent_event(
    state: AgentState,
    task: AgentTask,
    summary: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> None:
    callback = getattr(state, "_progress_callback", None)
    if not callback:
        return
    callback(
        {
            "trace_id": state.trace_id,
            "phase": "agent",
            "parent_node": "execute_plan",
            "node": f"{task.agent}_agent",
            "agent_name": task.agent,
            "task_id": task.task_id,
            "summary": summary,
            "details": details or {},
            "status": status,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "revision_round": state.revision_round,
        }
    )


def _agent_objective(agent: str, state: AgentState) -> str:
    goal = str((state.intent_contract or {}).get("goal") or state.goal or state.user_input)
    labels = {
        "travel": "生成出行路线、地点依据和预算",
        "meal": "生成餐饮候选、用餐安排和预算",
        "errand": "生成跑腿事项、地点和顺路顺序",
        "todo": "拆解待办、时间块和完成标准",
    }
    return f"{labels[agent]}：{goal}"


def _has_dependency_cycle(tasks: list[AgentTask]) -> bool:
    graph = {task.task_id: list(task.depends_on) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        for dependency in graph.get(task_id, []):
            if dependency in graph and visit(dependency):
                return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    return any(visit(task_id) for task_id in graph)


def _llm_enabled() -> bool:
    if settings.llm_mode == "deepseek":
        return bool(settings.deepseek_api_key)
    if settings.llm_mode == "openai":
        return bool(settings.openai_api_key)
    return False


def _llm_model_name() -> str:
    if settings.llm_mode == "deepseek":
        return settings.deepseek_model
    if settings.llm_mode == "openai":
        return settings.openai_model
    return "mock"
