from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class AgentState:
    user_input: str
    user_id: str = "default"
    goal: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    intent_contract: dict[str, Any] = field(default_factory=dict)
    execution_plan: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    user_profile: dict[str, Any] = field(default_factory=dict)
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    final_plan: dict[str, Any] | None = None
    risks: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)
    reflection: dict[str, Any] = field(default_factory=dict)
    replan_context: dict[str, Any] = field(default_factory=dict)
    llm_usage: list[dict[str, Any]] = field(default_factory=list)
    execution_log: list[dict[str, Any]] = field(default_factory=list)
    need_human_confirm: bool = False
    clarification_question: str | None = None
    replan_count: int = 0
    trace_id: str = field(default_factory=lambda: uuid4().hex[:12])
