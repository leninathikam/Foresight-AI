from __future__ import annotations

import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest

@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()

from foresight.prediction.dataset import assemble, simulate_episode_rows
from foresight.prediction.models import RiskBundle, train_bundle
from foresight.simulation import ScenarioId, canonical_episode
from foresight.telemetry import TelemetryStream


@pytest.fixture(scope="session")
def small_bundle() -> RiskBundle:
    """A quickly trained bundle (few episodes) for tests; not used for reported metrics."""
    import joblib
    from foresight.artifacts import MODEL_PATH
    if MODEL_PATH.exists():
        try:
            return joblib.load(MODEL_PATH)
        except Exception:
            pass
    train = assemble([simulate_episode_rows(sc, seed) for sc in ScenarioId for seed in range(3)])
    val = assemble(
        [simulate_episode_rows(sc, seed) for sc in ScenarioId for seed in range(1000, 1002)]
    )
    bundle = train_bundle(train, val)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        joblib.dump(bundle, cache_path)
    except Exception:
        pass
    return bundle


@pytest.fixture
def cooling_stream_100min() -> TelemetryStream:
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    stream.advance(100 * 60)
    return stream
