from __future__ import annotations

import numpy as np

from foresight.prediction import FEATURE_NAMES, RiskEngine
from foresight.prediction.changepoint import cusum
from foresight.prediction.dataset import HORIZONS_MIN, SPLIT_SEEDS, simulate_episode_rows
from foresight.prediction.features import features_from_samples
from foresight.simulation import ScenarioId, canonical_episode
from foresight.telemetry import TelemetryStream


def test_split_seed_ranges_are_disjoint():
    sets = [set(r) for r in SPLIT_SEEDS.values()]
    assert not (sets[0] & sets[1]) and not (sets[0] & sets[2]) and not (sets[1] & sets[2])


def test_cusum_detects_shift_and_ignores_noise():
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(300)
    assert cusum(noise, 0.0, 1.0).alarm_index is None
    shifted = np.concatenate([noise[:150], noise[150:] + 2.0])
    res = cusum(shifted, 0.0, 1.0)
    assert res.alarm_index is not None and 150 <= res.alarm_index < 170 and res.direction == "up"


def test_features_are_causal_and_finite():
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    stream.advance(3600)
    samples = list(stream.window)
    x_full = features_from_samples(samples)
    x_prefix = features_from_samples(samples[: len(samples) // 2])
    assert x_full is not None and x_prefix is not None
    assert x_full.shape == (len(FEATURE_NAMES),) and np.isfinite(x_full).all()
    # Appending future samples must not change features computed at an earlier time.
    stream2 = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    stream2.advance(1800)
    np.testing.assert_allclose(features_from_samples(list(stream2.window)), x_prefix)


def test_rise_residual_separates_cooling_fault_from_healthy():
    def residual(scenario):
        stream = TelemetryStream(canonical_episode(scenario))
        stream.advance(110 * 60)
        x = features_from_samples(list(stream.window))
        return x[FEATURE_NAMES.index("rise_residual_k")]

    assert residual(ScenarioId.COOLING_DEGRADATION) > residual(ScenarioId.HEALTHY) + 15


def test_episode_labels_respect_failure_time():
    ep = next(
        e
        for e in (simulate_episode_rows(ScenarioId.COOLING_DEGRADATION, s) for s in range(20))
        if e.failure_time_s is not None
    )
    assert (ep.t_s < ep.failure_time_s).all()
    ttf = ep.time_to_failure_s
    assert np.all(np.diff(ttf) < 0)
    for h in HORIZONS_MIN:
        assert ((ttf <= h * 60) == (ep.failure_time_s - ep.t_s <= h * 60)).all()


def test_risk_engine_outputs_valid_assessment(small_bundle):
    stream = TelemetryStream(canonical_episode(ScenarioId.OVERLOAD))
    engine = RiskEngine(small_bundle)
    for _ in range(80):
        stream.advance(60)
        a = engine.assess(list(stream.window))
    assert a.available
    assert [h.horizon_min for h in a.horizons] == list(HORIZONS_MIN)
    assert all(0 <= h.probability <= 1 for h in a.horizons)
    assert abs(sum(d.probability for d in a.diagnosis) - 1) < 1e-4
    ids = {e.id for e in a.evidence}
    assert "ml:risk_60m" in ids and "obs:load_frac" in ids
    assert {e.kind for e in a.evidence} <= {"observed", "ml_prediction"}


def test_risk_engine_unavailable_when_stopped(small_bundle):
    from foresight.simulation import ControlledShutdown

    stream = TelemetryStream(canonical_episode(ScenarioId.HEALTHY))
    stream.advance(1800)
    stream.apply_action(ControlledShutdown())
    stream.advance(600)
    a = RiskEngine(small_bundle).assess(list(stream.window))
    assert not a.available and a.reason
