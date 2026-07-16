from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentName = Literal["travel", "meal", "errand", "todo"]


class AgentTask(BaseModel):
    task_id: str = Field(..., min_length=1)
    agent: AgentName
    objective: str = Field(..., min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    revision_context: list[str] = Field(default_factory=list)


class SupervisorDecision(BaseModel):
    primary_task_type: str
    tasks: list[AgentTask] = Field(..., min_length=1, max_length=4)
    strategy: str = Field(..., min_length=1)


class AgentProposal(BaseModel):
    task_id: str
    agent: AgentName
    status: Literal["success", "degraded", "blocked"]
    plan_fragment: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0, le=1)


class AgentRunRecord(BaseModel):
    task_id: str
    agent: AgentName
    objective: str
    status: Literal["success", "degraded", "blocked"]
    tools_used: list[str] = Field(default_factory=list)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    latency_ms: int = Field(default=0, ge=0)
    revision_round: int = Field(default=0, ge=0, le=1)


class CriticIssue(BaseModel):
    code: str
    severity: Literal["low", "medium", "high"]
    agent: AgentName | None = None
    message: str
    revisable: bool = False


class CriticDecision(BaseModel):
    passed: bool
    issues: list[CriticIssue] = Field(default_factory=list)
    next_action: Literal["final", "revise", "ask_user"]
    revision_targets: list[AgentName] = Field(default_factory=list)
    review: str
