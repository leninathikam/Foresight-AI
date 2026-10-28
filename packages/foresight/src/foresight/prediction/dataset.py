"""Simulator-generated, episode-split datasets for the predictive models.

Leakage controls:
* splits are by *episode* with disjoint seed ranges (train / validation / test),
* every scenario (including healthy) appears in every split, so test scenarios are seen as
  types but never as the same randomized episode,
* features only use samples at or before the prediction time (causal windows),
* rows after a failure are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from joblib import Parallel, delayed

from foresight.prediction.features import FEATURE_NAMES, WindowArrays, compute_features
from foresight.simulation import ScenarioId, sample_episode
from foresight.telemetry import TelemetryConfig, TelemetryStream

HORIZONS_MIN: tuple[int, ...] = (15, 30, 60)
DIAGNOSIS_CLASSES: tuple[str, ...] = ("none", "cooling", "bearing", "overload")
ROW_STRIDE_S = 60.0
EPISODE_DURATION_S = 6 * 3600.0

SPLIT_SEEDS: dict[str, range] = {
    "train": range(0, 40),
    "validation": range(1000, 1015),
    "test": range(2000, 2020),
}

_FAULT_CLASS = {
    ScenarioId.HEALTHY: "none",
    ScenarioId.COOLING_DEGRADATION: "cooling",
    ScenarioId.BEARING_DETERIORATION: "bearing",
    ScenarioId.OVERLOAD: "overload",
}


@dataclass
class EpisodeRows:
    scenario: ScenarioId
    seed: int
    t_s: np.ndarray
    features: np.ndarray
    time_to_failure_s: np.ndarray  # inf when the episode never fails
    diagnosis: np.ndarray  # index into DIAGNOSIS_CLASSES (fault active at that time)
    failure_time_s: float | None
    failure_mode: str | None
    fault_onset_s: float | None


@dataclass
class Dataset:
    X: np.ndarray
    labels: dict[int, np.ndarray]
    diagnosis: np.ndarray
    episode: np.ndarray  # integer episode index
    scenario: np.ndarray
    t_s: np.ndarray
    time_to_failure_s: np.ndarray
    episodes: list[EpisodeRows] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return int(self.X.shape[0])


def _fault_onset(config) -> float | None:
    f = config.fault
    for onset in (f.cooling_fouling_onset_s, f.bearing_defect_onset_s, f.overload_onset_s):
        if onset is not None:
            return onset
    return None


def simulate_episode_rows(scenario: ScenarioId, seed: int) -> EpisodeRows:
    config = sample_episode(scenario, seed, duration_s=EPISODE_DURATION_S)
    tel_cfg = TelemetryConfig(window_size=int(EPISODE_DURATION_S / 10) + 10)
    stream = TelemetryStream(config, tel_cfg)
    while stream.t_s < config.duration_s and not stream.twin.state.failed:
        stream.advance(ROW_STRIDE_S)
    samples = list(stream.window)
    arr = WindowArrays.from_samples(samples)
    stride = max(1, round(ROW_STRIDE_S / tel_cfg.sample_interval_s))
    failure_time = stream.twin.state.failure_time_s
    onset = _fault_onset(config)

    t_rows, feats = [], []
    for end in range(stride - 1, len(samples), stride):
        if failure_time is not None and arr.t[end] >= failure_time:
            break
        f = compute_features(arr, end)
        if f is None:
            continue
        t_rows.append(arr.t[end])
        feats.append(f)
    t = np.array(t_rows, dtype=float)
    ttf = (failure_time - t) if failure_time is not None else np.full_like(t, np.inf)
    fault_class = DIAGNOSIS_CLASSES.index(_FAULT_CLASS[scenario])
    diagnosis = np.where((onset is not None) & (t >= (onset or 0.0)), fault_class, 0)
    return EpisodeRows(
        scenario=scenario,
        seed=seed,
        t_s=t,
        features=np.array(feats, dtype=float).reshape(-1, len(FEATURE_NAMES)),
        time_to_failure_s=ttf,
        diagnosis=diagnosis.astype(int),
        failure_time_s=failure_time,
        failure_mode=stream.twin.state.failure_mode,
        fault_onset_s=onset,
    )


def build_dataset(split: str, n_jobs: int = -1) -> Dataset:
    jobs = [(sc, seed) for sc in ScenarioId for seed in SPLIT_SEEDS[split]]
    episodes: list[EpisodeRows] = Parallel(n_jobs=n_jobs)(
        delayed(simulate_episode_rows)(sc, seed) for sc, seed in jobs
    )
    return assemble(episodes)


def assemble(episodes: list[EpisodeRows]) -> Dataset:
    X = np.concatenate([e.features for e in episodes])
    ttf = np.concatenate([e.time_to_failure_s for e in episodes])
    labels = {h: (ttf <= h * 60.0).astype(int) for h in HORIZONS_MIN}
    return Dataset(
        X=X,
        labels=labels,
        diagnosis=np.concatenate([e.diagnosis for e in episodes]),
        episode=np.concatenate([np.full(len(e.t_s), i) for i, e in enumerate(episodes)]),
        scenario=np.concatenate([np.full(len(e.t_s), e.scenario.value) for e in episodes]),
        t_s=np.concatenate([e.t_s for e in episodes]),
        time_to_failure_s=ttf,
        episodes=episodes,
    )
