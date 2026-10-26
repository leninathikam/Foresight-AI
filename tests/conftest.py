from __future__ import annotations

import pytest

from foresight.prediction.dataset import assemble, simulate_episode_rows
from foresight.prediction.models import RiskBundle, train_bundle
from foresight.simulation import ScenarioId, canonical_episode
from foresight.telemetry import TelemetryStream


@pytest.fixture(scope="session")
def small_bundle() -> RiskBundle:
    """A quickly trained bundle (few episodes) for tests; not used for reported metrics."""
    train = assemble([simulate_episode_rows(sc, seed) for sc in ScenarioId for seed in range(3)])
    val = assemble(
        [simulate_episode_rows(sc, seed) for sc in ScenarioId for seed in range(1000, 1002)]
    )
    return train_bundle(train, val)


@pytest.fixture
def cooling_stream_100min() -> TelemetryStream:
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    stream.advance(100 * 60)
    return stream
