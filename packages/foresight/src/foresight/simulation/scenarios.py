"""Failure scenarios with deterministic, seed-controlled parameters.

A ``ScenarioSpec`` describes *ranges*; ``sample_episode`` turns a spec and a seed into one fully
specified ``EpisodeConfig``. The demo uses fixed "canonical" configurations so the walkthrough is
identical every time, while training/evaluation sample many episodes from disjoint seed ranges.
"""

from __future__ import annotations

from enum import StrEnum

import numpy as np
from pydantic import BaseModel, Field


class ScenarioId(StrEnum):
    HEALTHY = "healthy"
    COOLING_DEGRADATION = "cooling_degradation"
    BEARING_DETERIORATION = "bearing_deterioration"
    OVERLOAD = "overload"


class FaultConfig(BaseModel):
    """Ground-truth fault injected into the simulator. Hidden from the predictive models."""

    cooling_fouling_onset_s: float | None = None
    cooling_fouling_rate_per_h: float = 0.0  # loss of cooling efficiency per hour
    cooling_floor: float = 0.15

    bearing_defect_onset_s: float | None = None
    bearing_initial_damage: float = 0.0  # 1 - health right after the defect initiates
    bearing_growth_per_h: float = 0.0  # exponential damage growth rate at rated load/speed

    overload_onset_s: float | None = None
    overload_ramp_h: float = 1.0
    overload_target_load: float = 1.0


class EpisodeConfig(BaseModel):
    scenario: ScenarioId
    seed: int
    duration_s: float = 6 * 3600.0
    base_load: float = Field(0.85, description="Applied torque as fraction of rated")
    speed_setpoint: float = Field(1.0, description="Drive speed setpoint as fraction of rated")
    ambient_c: float = 30.0
    initial_bearing_health: float = 1.0
    initial_cooling_efficiency: float = 1.0
    fault: FaultConfig = Field(default_factory=FaultConfig)


class ScenarioInfo(BaseModel):
    id: ScenarioId
    title: str
    description: str
    expected_failure_mode: str | None
    plausible_interventions: list[str]


SCENARIOS: dict[ScenarioId, ScenarioInfo] = {
    ScenarioId.HEALTHY: ScenarioInfo(
        id=ScenarioId.HEALTHY,
        title="Healthy baseline",
        description="Nominal operation at 85 % load. Used as the no-fault reference.",
        expected_failure_mode=None,
        plausible_interventions=["continue_operation"],
    ),
    ScenarioId.COOLING_DEGRADATION: ScenarioInfo(
        id=ScenarioId.COOLING_DEGRADATION,
        title="Cooling degradation",
        description=(
            "Dust fouling of the cooling fins and fan cowl progressively reduces heat rejection. "
            "Winding temperature drifts up until the class-F limit (155 °C) is exceeded."
        ),
        expected_failure_mode="thermal",
        plausible_interventions=["increase_cooling", "reduce_load", "schedule_inspection"],
    ),
    ScenarioId.BEARING_DETERIORATION: ScenarioInfo(
        id=ScenarioId.BEARING_DETERIORATION,
        title="Bearing deterioration",
        description=(
            "A drive-end bearing spall initiates and grows. Damage growth is accelerated by load "
            "(cubic, as in L10 life rating) and speed. Vibration rises through the ISO zones."
        ),
        expected_failure_mode="bearing",
        plausible_interventions=["reduce_load", "reduce_speed", "schedule_inspection"],
    ),
    ScenarioId.OVERLOAD: ScenarioInfo(
        id=ScenarioId.OVERLOAD,
        title="Overload",
        description=(
            "Material build-up on the conveyor ramps the applied torque above rating, increasing "
            "current, copper losses and bearing stress."
        ),
        expected_failure_mode="thermal",
        plausible_interventions=["reduce_load", "controlled_shutdown", "schedule_inspection"],
    ),
}


def canonical_episode(scenario: ScenarioId, seed: int = 7) -> EpisodeConfig:
    """Fixed, hand-chosen configuration used by the live demo."""
    fault = FaultConfig()
    if scenario is ScenarioId.COOLING_DEGRADATION:
        fault = FaultConfig(cooling_fouling_onset_s=20 * 60, cooling_fouling_rate_per_h=0.32)
    elif scenario is ScenarioId.BEARING_DETERIORATION:
        fault = FaultConfig(
            bearing_defect_onset_s=20 * 60, bearing_initial_damage=0.12, bearing_growth_per_h=0.75
        )
    elif scenario is ScenarioId.OVERLOAD:
        fault = FaultConfig(overload_onset_s=20 * 60, overload_ramp_h=1.0, overload_target_load=1.4)
    return EpisodeConfig(scenario=scenario, seed=seed, fault=fault)


def sample_episode(
    scenario: ScenarioId, seed: int, duration_s: float = 6 * 3600.0
) -> EpisodeConfig:
    """Draw a randomized episode. The same (scenario, seed) always yields the same config."""
    scenario_index = list(ScenarioId).index(scenario)
    rng = np.random.default_rng(np.random.SeedSequence([seed, scenario_index, 0xC0FFEE]))
    base_load = float(rng.uniform(0.7, 0.95))
    ambient = float(rng.uniform(22.0, 38.0))
    speed = float(rng.choice([0.9, 1.0, 1.0, 1.0]))
    health = float(rng.uniform(0.97, 1.0))
    onset = float(rng.uniform(0.1, 0.4) * duration_s)

    fault = FaultConfig()
    if scenario is ScenarioId.COOLING_DEGRADATION:
        fault = FaultConfig(
            cooling_fouling_onset_s=onset,
            cooling_fouling_rate_per_h=float(rng.uniform(0.12, 0.45)),
            cooling_floor=float(rng.uniform(0.1, 0.3)),
        )
    elif scenario is ScenarioId.BEARING_DETERIORATION:
        fault = FaultConfig(
            bearing_defect_onset_s=onset,
            bearing_initial_damage=float(rng.uniform(0.06, 0.2)),
            bearing_growth_per_h=float(rng.uniform(0.35, 1.1)),
        )
    elif scenario is ScenarioId.OVERLOAD:
        fault = FaultConfig(
            overload_onset_s=onset,
            overload_ramp_h=float(rng.uniform(0.5, 2.0)),
            overload_target_load=float(rng.uniform(1.15, 1.5)),
        )
    return EpisodeConfig(
        scenario=scenario,
        seed=seed,
        duration_s=duration_s,
        base_load=base_load,
        speed_setpoint=speed,
        ambient_c=ambient,
        initial_bearing_health=health,
        fault=fault,
    )
