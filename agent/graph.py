from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from agent.nodes import (
    call_tools,
    check_clarification,
    check_risks_node,
    errand_candidate_scorer,
    errand_plan_generator,
    errand_tool_router,
    execute_plan,
    extract_constraints,
    final_response,
    generate_plan,
    load_memory,
    meal_candidate_scorer,
    meal_plan_generator,
    meal_tool_router,
    normalize_dates,
    plan_steps,
    reflect,
    route_task,
    score_candidates_node,
    synthesize_plan,
    todo_decomposer,
    todo_plan_generator,
    travel_candidate_scorer,
    travel_plan_generator,
    travel_tool_router,
)
from agent.state import AgentState
from services.trace_logger import load_trace, traced
from storage.db import save_task_history


ProgressCallback = Callable[[dict[str, Any]], None]


NODES = [
    ("constraint_extractor", extract_constraints),
    ("date_resolver", normalize_dates),
    ("load_memory", load_memory),
    ("need_clarification", check_clarification),
    ("planner", plan_steps),
    ("execute_plan", execute_plan),
    ("synthesize_plan", synthesize_plan),
    ("risk_checker", check_risks_node),
    ("reflection", reflect),
]


def run_lifeops(
    user_input: str,
    previous_result: dict | None = None,
    trace_id: str | None = None,
    progress_callback: ProgressCallback | None = None,
    request_context: dict[str, Any] | None = None,
) -> dict:
    state = _initial_state(user_input, previous_result, trace_id, request_context)
    state._progress_callback = progress_callback  # type: ignore[attr-defined]
    _emit(progress_callback, state.trace_id, "run", "run", "开始执行规划任务", "running", {}, 0)
    _emit(progress_callback, state.trace_id, "run", "run", "任务已创建，开始执行节点", "done", {}, 1)
    state = _run_langgraph(state, NODES, progress_callback)
    result = final_response(state)
    if result.get("status") == "success":
        result["task_id"] = save_task_history(user_input, result.get("final_plan"))
    result["trace"] = load_trace(state.trace_id)
    _emit(
        progress_callback,
        state.trace_id,
        "result",
        "final_response",
        "规划结果已生成",
        "done",
        {"status": result.get("status"), "question": result.get("question")},
        100,
        result=result,
    )
    return result


def build_lifeops_graph(nodes: list[tuple[str, Any]] | None = None):
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise RuntimeError("Install langgraph before using build_lifeops_graph()") from exc

    nodes = nodes or NODES
    graph = StateGraph(dict)
    for name, node in nodes:
        graph.add_node(name, _langgraph_node(name, node))

    if not nodes:
        raise ValueError("LifeOps graph requires at least one node")

    graph.set_entry_point(nodes[0][0])
    replan_start = _replan_nodes(nodes)[0][0] if _replan_nodes(nodes) else None

    if _has_task_router(nodes):
        _add_branched_edges(graph, nodes, END)
        return graph.compile()

    for index, (name, _node) in enumerate(nodes):
        next_name = nodes[index + 1][0] if index + 1 < len(nodes) else None
        if name == "need_clarification":
            graph.add_conditional_edges(
                name,
                _route_after_clarification,
                {
                    "end": END,
                    "continue": next_name or END,
                },
            )
        elif name == "reflection":
            graph.add_conditional_edges(
                name,
                _route_after_reflection,
                {
                    "final": END,
                    "replan": replan_start or END,
                },
            )
        elif next_name:
            graph.add_edge(name, next_name)
        else:
            graph.add_edge(name, END)

    return graph.compile()


def _add_branched_edges(graph: Any, nodes: list[tuple[str, Any]], end_node: Any) -> None:
    node_names = {name for name, _node in nodes}
    required = {
        "constraint_extractor",
        "date_resolver",
        "load_memory",
        "need_clarification",
        "planner",
        "task_router",
        "risk_checker",
        "reflection",
    }
    missing = required - node_names
    if missing:
        raise ValueError(f"Branched LifeOps graph missing nodes: {sorted(missing)}")

    graph.add_edge("constraint_extractor", "date_resolver")
    graph.add_edge("date_resolver", "load_memory")
    graph.add_edge("load_memory", "need_clarification")
    graph.add_conditional_edges(
        "need_clarification",
        _route_after_clarification,
        {"end": end_node, "continue": "planner"},
    )
    graph.add_edge("planner", "task_router")
    graph.add_conditional_edges(
        "task_router",
        _route_after_task_router,
        {
            "travel": "travel_tool_router",
            "errand": "errand_tool_router",
            "meal": "meal_tool_router",
            "todo": "todo_decomposer",
        },
    )
    graph.add_edge("travel_tool_router", "travel_candidate_scorer")
    graph.add_edge("travel_candidate_scorer", "travel_plan_generator")
    graph.add_edge("travel_plan_generator", "risk_checker")
    graph.add_edge("errand_tool_router", "errand_candidate_scorer")
    graph.add_edge("errand_candidate_scorer", "errand_plan_generator")
    graph.add_edge("errand_plan_generator", "risk_checker")
    graph.add_edge("meal_tool_router", "meal_candidate_scorer")
    graph.add_edge("meal_candidate_scorer", "meal_plan_generator")
    graph.add_edge("meal_plan_generator", "risk_checker")
    graph.add_edge("todo_decomposer", "todo_plan_generator")
    graph.add_edge("todo_plan_generator", "risk_checker")
    graph.add_edge("risk_checker", "reflection")
    graph.add_conditional_edges(
        "reflection",
        _route_after_reflection,
        {
            "final": end_node,
            "travel": "travel_tool_router",
            "errand": "errand_tool_router",
            "meal": "meal_tool_router",
            "todo": "todo_decomposer",
        },
    )


def _run_langgraph(
    state: AgentState,
    nodes: list[tuple[str, Any]],
    progress_callback: ProgressCallback | None,
) -> AgentState:
    graph_state = {
        "state": state,
        "nodes": nodes,
        "progress_callback": progress_callback,
        "step_index": 0,
        "active_round": "initial",
        "round_position": 0,
        "round_total": len(nodes),
    }
    result = build_lifeops_graph(nodes).invoke(graph_state)
    return result["state"]


def _langgraph_node(name: str, node: Any):
    def run(graph_state: dict[str, Any]) -> dict[str, Any]:
        state: AgentState = graph_state["state"]
        progress_callback = graph_state.get("progress_callback")
        round_name = graph_state.get("active_round", "initial")
        if state.replan_count > 0 and state.replan_context and name in {item[0] for item in _replan_nodes(graph_state.get("nodes") or NODES)}:
            round_name = "auto_replan"
        event_details = {"round": "auto_replan"} if round_name == "auto_replan" else {}
        progress_floor, progress_ceiling = (91, 99) if round_name == "auto_replan" else (1, 90)
        round_total = len(_replan_nodes(graph_state.get("nodes") or NODES)) if round_name == "auto_replan" else int(graph_state.get("round_total") or 1)
        round_total = max(round_total, 1)
        round_position = int(graph_state.get("round_position") or 0)

        _emit(
            progress_callback,
            state.trace_id,
            "node",
            name,
            _node_start_summary(name),
            "running",
            event_details,
            _progress_for(progress_floor, progress_ceiling, round_position, round_total),
        )

        graph_state["step_index"] = int(graph_state.get("step_index") or 0) + 1
        with traced(state.trace_id, graph_state["step_index"], name, _snapshot(state)) as holder:
            graph_state["state"] = node(state)
            state = graph_state["state"]
            holder["output"] = _snapshot(state)

        graph_state["round_position"] = round_position + 1
        latest_log = state.execution_log[-1] if state.execution_log else {}
        _emit(
            progress_callback,
            state.trace_id,
            "node",
            name,
            latest_log.get("summary") or _node_done_summary(name),
            "done",
            _merge_event_details(latest_log.get("details") or {}, event_details),
            _progress_for(progress_floor, progress_ceiling, round_position + 1, round_total),
        )
        return graph_state

    return run


def _route_after_clarification(graph_state: dict[str, Any]) -> str:
    state: AgentState = graph_state["state"]
    return "end" if state.clarification_question else "continue"


def _route_after_task_router(graph_state: dict[str, Any]) -> str:
    state: AgentState = graph_state["state"]
    return _task_branch_key(state)


def _route_after_reflection(graph_state: dict[str, Any]) -> str:
    state: AgentState = graph_state["state"]
    progress_callback = graph_state.get("progress_callback")
    if _should_auto_replan(state):
        _prepare_auto_replan(state)
        replan_nodes = _replan_nodes(graph_state.get("nodes") or NODES)
        graph_state["active_round"] = "auto_replan"
        graph_state["round_position"] = 0
        graph_state["round_total"] = len(replan_nodes)
        _emit(
            progress_callback,
            state.trace_id,
            "node",
            "reflection_replan",
            "反思触发自动重排，正在补齐不足",
            "running",
            {
                "issues": state.replan_context.get("issues", []),
                "review": state.replan_context.get("review"),
                "round": "auto_replan",
            },
            91,
        )
        if _has_task_router(graph_state.get("nodes") or NODES):
            return _task_branch_key(state)
        return "replan"
    return "final"


def _initial_state(
    user_input: str,
    previous_result: dict | None,
    trace_id: str | None = None,
    request_context: dict[str, Any] | None = None,
) -> AgentState:
    state = AgentState(user_input=user_input)
    if trace_id:
        state.trace_id = trace_id
    if previous_result and previous_result.get("constraints"):
        state.constraints.update(previous_result["constraints"])
        state.goal = previous_result.get("final_plan", {}).get("goal")
        state.replan_count = int(previous_result.get("reflection", {}).get("replan_count", 0))
        state.execution_log.append(
            {
                "node": "context_restore",
                "summary": "读取上一轮上下文，用于本轮重规划",
                "details": {"previous_trace_id": previous_result.get("trace_id")},
            }
        )
    if request_context:
        state.constraints.update({key: value for key, value in request_context.items() if value})
    return state


def _run_node_sequence(
    state: AgentState,
    nodes: list[tuple[str, Any]],
    progress_callback: ProgressCallback | None,
    step_offset: int,
    progress_floor: int,
    progress_ceiling: int,
    event_details: dict[str, Any] | None = None,
) -> AgentState:
    total = max(len(nodes), 1)
    for index, (name, node) in enumerate(nodes, start=1):
        _emit(
            progress_callback,
            state.trace_id,
            "node",
            name,
            _node_start_summary(name),
            "running",
            event_details or {},
            _progress_for(progress_floor, progress_ceiling, index - 1, total),
        )
        with traced(state.trace_id, step_offset + index, name, _snapshot(state)) as holder:
            state = node(state)
            holder["output"] = _snapshot(state)
        latest_log = state.execution_log[-1] if state.execution_log else {}
        _emit(
            progress_callback,
            state.trace_id,
            "node",
            name,
            latest_log.get("summary") or _node_done_summary(name),
            "done",
            _merge_event_details(latest_log.get("details") or {}, event_details),
            _progress_for(progress_floor, progress_ceiling, index, total),
        )
        if state.clarification_question:
            break
    return state


def _replan_nodes(nodes: list[tuple[str, Any]] | None = None) -> list[tuple[str, Any]]:
    replannable = {
        "planner",
        "execute_plan",
        "synthesize_plan",
        "tool_router",
        "candidate_scorer",
        "plan_generator",
        "travel_tool_router",
        "travel_candidate_scorer",
        "travel_plan_generator",
        "errand_tool_router",
        "errand_candidate_scorer",
        "errand_plan_generator",
        "meal_tool_router",
        "meal_candidate_scorer",
        "meal_plan_generator",
        "todo_decomposer",
        "todo_plan_generator",
        "risk_checker",
        "reflection",
    }
    return [(name, node) for name, node in (nodes or NODES) if name in replannable]


def _has_task_router(nodes: list[tuple[str, Any]]) -> bool:
    return any(name == "task_router" for name, _node in nodes)


def _task_branch_key(state: AgentState) -> str:
    task_type = state.constraints.get("task_type") or "travel"
    return str(task_type) if task_type in {"travel", "errand", "meal", "todo"} else "travel"


def _progress_for(start: int, end: int, position: int, total: int) -> int:
    return start + int((position / max(total, 1)) * max(end - start, 1))


def _merge_event_details(details: Any, extra: dict[str, Any] | None) -> Any:
    if not extra:
        return details
    if isinstance(details, dict):
        return {**details, **extra}
    return {"value": details, **extra}


def _should_auto_replan(state: AgentState) -> bool:
    if state.replan_count >= 1:
        return False
    if state.clarification_question:
        return False
    return (state.reflection or {}).get("next_action") == "replan"


def _prepare_auto_replan(state: AgentState) -> None:
    state.replan_count += 1
    state.replan_context = copy.deepcopy(state.reflection)
    state.execution_log.append(
        {
            "node": "reflection_replan",
            "summary": "反思要求自动重排，已基于问题补强计划",
            "details": {
                "issues": state.replan_context.get("issues", []),
                "review": state.replan_context.get("review"),
                "next_action": state.replan_context.get("next_action"),
            },
        }
    )


def _snapshot(state: AgentState) -> dict:
    return copy.deepcopy(
        {
            "user_input": state.user_input,
            "goal": state.goal,
            "constraints": state.constraints,
            "intent_contract": state.intent_contract,
            "execution_plan": state.execution_plan,
            "artifacts_keys": sorted(state.artifacts.keys()),
            "plan_steps": state.plan_steps,
            "tool_results_count": len(state.tool_results),
            "candidates_count": len(state.candidates),
            "has_final_plan": state.final_plan is not None,
            "risks": state.risks,
            "reflection": state.reflection,
            "llm_usage": state.llm_usage,
            "execution_log_count": len(state.execution_log),
            "need_human_confirm": state.need_human_confirm,
            "clarification_question": state.clarification_question,
            "replan_count": state.replan_count,
        }
    )


def _emit(
    callback: ProgressCallback | None,
    trace_id: str,
    phase: str,
    node: str,
    summary: str,
    status: str,
    details: Any,
    progress: int,
    result: dict[str, Any] | None = None,
) -> None:
    if not callback:
        return
    event = {
        "trace_id": trace_id,
        "phase": phase,
        "node": node,
        "summary": summary,
        "details": details,
        "status": status,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "progress": progress,
    }
    if result is not None:
        event["result"] = result
    callback(event)


def _node_start_summary(node: str) -> str:
    return {
        "constraint_extractor": "正在理解用户输入和目标",
        "date_resolver": "正在解析日期和时间范围",
        "load_memory": "正在读取长期偏好",
        "need_clarification": "正在检查信息是否足够",
        "planner": "正在拆解执行步骤",
        "execute_plan": "正在按意图动态调用工具",
        "synthesize_plan": "正在按用户意图组装计划",
        "task_router": "正在选择生活任务分支",
        "tool_router": "正在调用天气、搜索和地点工具",
        "travel_tool_router": "正在调用旅行工具链",
        "travel_candidate_scorer": "正在筛选旅行候选地点",
        "travel_plan_generator": "正在生成旅行计划",
        "errand_tool_router": "正在准备跑腿地点候选",
        "errand_candidate_scorer": "正在整理跑腿候选事项",
        "errand_plan_generator": "正在生成跑腿时间轴",
        "meal_tool_router": "正在准备餐饮地点候选",
        "meal_candidate_scorer": "正在整理餐饮候选",
        "meal_plan_generator": "正在生成餐饮计划",
        "todo_decomposer": "正在拆解待办任务",
        "todo_plan_generator": "正在生成待办时间块",
        "candidate_scorer": "正在筛选和排序候选地点",
        "plan_generator": "正在生成路线、预算和计划正文",
        "risk_checker": "正在检查天气、预算和节奏风险",
        "reflection": "正在复核计划质量",
    }.get(node, "正在执行步骤")


def _node_done_summary(node: str) -> str:
    return {
        "constraint_extractor": "已识别用户目标和约束",
        "date_resolver": "已完成日期解析",
        "load_memory": "已读取偏好信息",
        "need_clarification": "已完成信息完整性检查",
        "planner": "已生成执行步骤",
        "execute_plan": "已完成动态工具编排",
        "synthesize_plan": "已按意图生成计划",
        "task_router": "已选择生活任务分支",
        "tool_router": "已完成工具调用",
        "travel_tool_router": "已完成旅行工具调用",
        "travel_candidate_scorer": "已完成旅行候选排序",
        "travel_plan_generator": "已生成旅行计划",
        "errand_tool_router": "已完成跑腿候选准备",
        "errand_candidate_scorer": "已完成跑腿候选整理",
        "errand_plan_generator": "已生成跑腿计划",
        "meal_tool_router": "已完成餐饮候选准备",
        "meal_candidate_scorer": "已完成餐饮候选整理",
        "meal_plan_generator": "已生成餐饮计划",
        "todo_decomposer": "已完成待办拆解",
        "todo_plan_generator": "已生成待办计划",
        "candidate_scorer": "已完成候选地点排序",
        "plan_generator": "已生成计划草案",
        "risk_checker": "已完成风险检查",
        "reflection": "已完成质量复核",
    }.get(node, "步骤已完成")


if __name__ == "__main__":
    demo = "这周六我想在杭州轻松玩一天，预算 500，喜欢咖啡、展览和夜景，不想太累。"
    print(json.dumps(run_lifeops(demo), ensure_ascii=False, indent=2))
