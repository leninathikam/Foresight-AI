from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from foresight.branching import BranchOutcome
from foresight.prediction.schemas import EvidenceItem
from foresight.verification import VerificationResult


class AgentStage(StrEnum):
    OBSERVE = "OBSERVE"
    ANALYZE = "ANALYZE"
    HYPOTHESIZE = "HYPOTHESIZE"
    INVESTIGATE = "INVESTIGATE"
    SIMULATE = "SIMULATE"
    VERIFY = "VERIFY"
    RECOMMEND = "RECOMMEND"
    DONE = "DONE"
    FAILED = "FAILED"


ALLOWED_TRANSITIONS: dict[AgentStage, set[AgentStage]] = {
    AgentStage.OBSERVE: {AgentStage.ANALYZE, AgentStage.FAILED},
    AgentStage.ANALYZE: {AgentStage.HYPOTHESIZE, AgentStage.FAILED},
    AgentStage.HYPOTHESIZE: {
        AgentStage.INVESTIGATE,
        AgentStage.SIMULATE,
        AgentStage.RECOMMEND,
        AgentStage.FAILED,
    },
    AgentStage.INVESTIGATE: {
        AgentStage.INVESTIGATE,
        AgentStage.SIMULATE,
        AgentStage.VERIFY,
        AgentStage.FAILED,
    },
    AgentStage.SIMULATE: {
        AgentStage.INVESTIGATE,
        AgentStage.SIMULATE,
        AgentStage.VERIFY,
        AgentStage.FAILED,
    },
    AgentStage.VERIFY: {
        AgentStage.INVESTIGATE,
        AgentStage.SIMULATE,
        AgentStage.VERIFY,
        AgentStage.RECOMMEND,
        AgentStage.FAILED,
    },
    AgentStage.RECOMMEND: {AgentStage.DONE, AgentStage.FAILED},
    AgentStage.DONE: set(),
    AgentStage.FAILED: set(),
}


class Hypothesis(BaseModel):
    failure_mode: Literal["thermal", "bearing", "overload", "none"]
    statement: str
    likelihood: Literal["low", "medium", "high"]
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    would_be_refuted_by: str = ""
    unknown_evidence_ids: list[str] = Field(
        default_factory=list, description="Cited ids that do not exist"
    )
    source: Literal["llm", "deterministic"] = "llm"


class TraceStep(BaseModel):
    seq: int
    stage: AgentStage
    kind: Literal["tool_call", "llm_call", "verification", "transition", "note", "error"]
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""
    result: Any = None
    ok: bool = True
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    t_wall: str


class RejectedProposal(BaseModel):
    action: dict
    action_label: str
    source: str
    reasons: list[str]
    verification: VerificationResult


class AgentRecommendation(BaseModel):
    status: Literal["awaiting_approval", "no_action_needed", "no_safe_action_found"]
    action: dict | None
    action_label: str
    claimed_failure_mode: str
    rationale: str
    rationale_source: Literal["llm", "deterministic"]
    cited_evidence: list[EvidenceItem] = Field(default_factory=list)
    verification: VerificationResult | None = None
    branch: BranchOutcome | None = None
    baseline: BranchOutcome | None = None
    comparison_id: str | None = None
    selected_by: Literal["agent", "optimizer_fallback", "deterministic_planner"]


class AgentUsage(BaseModel):
    llm_calls: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    invalid_actions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    hallucinated_evidence_ids: int = 0


class AgentTrace(BaseModel):
    run_id: str
    session_id: str
    status: Literal["running", "completed", "failed"]
    provider: str
    model: str | None
    snapshot_t_s: float
    started_at: str
    finished_at: str | None = None
    latency_ms: float | None = None
    stage: AgentStage
    stage_history: list[AgentStage] = Field(default_factory=list)
    steps: list[TraceStep] = Field(default_factory=list)
    summary: str = ""
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    rejected: list[RejectedProposal] = Field(default_factory=list)
    recommendation: AgentRecommendation | None = None
    report: dict | None = None
    usage: AgentUsage = Field(default_factory=AgentUsage)
    error: str | None = None
    notice: str | None = None
