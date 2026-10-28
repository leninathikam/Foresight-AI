from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EvidenceKind = Literal[
    "observed", "ml_prediction", "simulation_estimate", "llm_hypothesis", "verified"
]


class EvidenceItem(BaseModel):
    """A citable piece of evidence. ``kind`` keeps observations and model outputs separate."""

    id: str
    kind: EvidenceKind
    signal: str
    value: float
    unit: str = ""
    healthy_mean: float | None = None
    z_score: float | None = None
    description: str


class HorizonRisk(BaseModel):
    horizon_min: int
    probability: float = Field(ge=0.0, le=1.0)
    raw_probability: float = Field(ge=0.0, le=1.0)
    method: str = "xgboost + isotonic calibration (validation seeds)"


class AnomalyResult(BaseModel):
    score: float
    threshold: float
    is_anomalous: bool
    method: str = "isolation forest (healthy training windows)"


class ChangePoint(BaseModel):
    signal: str
    detected: bool
    t_s: float | None = None
    direction: str | None = None
    statistic: float


class DiagnosisProbability(BaseModel):
    label: str
    probability: float


class RiskAssessment(BaseModel):
    t_s: float
    available: bool = True
    reason: str | None = None
    horizons: list[HorizonRisk] = Field(default_factory=list)
    anomaly: AnomalyResult | None = None
    change_points: list[ChangePoint] = Field(default_factory=list)
    diagnosis: list[DiagnosisProbability] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    features: dict[str, float] = Field(default_factory=dict)
    heuristic_minutes_to_temp_limit: float | None = Field(
        None, description="Linear extrapolation heuristic, not a statistical estimate"
    )
    model_version: str = ""
    latency_ms: float = 0.0
