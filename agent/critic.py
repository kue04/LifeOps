from __future__ import annotations

from agent.contracts import CriticDecision, CriticIssue
from agent.nodes import reflect
from agent.state import AgentState


def critic_node(state: AgentState) -> AgentState:
    state = reflect(state)
    issues = [
        CriticIssue(
            code="plan_quality",
            severity="high" if "没有生成" in str(issue) or "超过用户限制" in str(issue) else "medium",
            agent=None,
            message=str(issue),
            revisable=True,
        )
        for issue in (state.reflection.get("issues") or [])
    ]
    next_action = state.reflection.get("next_action") or "final"
    if next_action == "replan":
        next_action = "revise"
    targets = _revision_targets([item.message for item in issues], state) if next_action == "revise" else []
    decision = CriticDecision(
        passed=bool(state.reflection.get("passed")),
        issues=issues,
        next_action=next_action if next_action in {"final", "revise", "ask_user"} else "ask_user",
        revision_targets=targets,
        review=str(state.reflection.get("review") or "已完成计划复核"),
    )
    state.critic_decision = decision.model_dump()
    if state.final_plan is not None:
        state.final_plan["critic"] = state.critic_decision
    state.reflection["next_action"] = "replan" if decision.next_action == "revise" else decision.next_action
    state.reflection["revision_targets"] = targets
    return state


def _revision_targets(issues: list[str], state: AgentState) -> list[str]:
    available = [str(item.get("agent")) for item in state.agent_tasks if item.get("agent")]
    targets = []
    mapping = {
        "meal": ["餐饮", "餐厅", "火锅", "用餐", "美食"],
        "errand": ["跑腿", "快递", "寄件", "取件", "办事"],
        "todo": ["待办", "任务", "时间块", "完成标准"],
        "travel": ["路线", "目的地", "景点", "天气", "行程"],
    }
    for agent, keywords in mapping.items():
        if agent in available and any(any(keyword in issue for keyword in keywords) for issue in issues):
            targets.append(agent)
    if targets:
        return targets
    return available
