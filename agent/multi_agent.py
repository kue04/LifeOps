from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from agent.contracts import AgentTask, SupervisorDecision
from agent.prompts import SUPERVISOR_PROMPT
from agent.state import AgentState
from config import settings
from services.llm_client import llm_client


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
