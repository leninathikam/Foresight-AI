"""End-to-end smoke test of the core loop without the web stack (deterministic planner)."""

import asyncio
import time

from foresight.agents import AgentOrchestrator, AgentSnapshot
from foresight.artifacts import load_or_train_bundle
from foresight.branching import ActuatorSettings, compare_futures, estimate_state
from foresight.config import Settings
from foresight.prediction import RiskEngine
from foresight.simulation import (
    ControlledShutdown,
    IncreaseCooling,
    ReduceLoad,
    ReduceSpeed,
    ScenarioId,
    ScheduleInspection,
    canonical_episode,
)
from foresight.telemetry import TelemetryStream


def main() -> None:
    bundle = load_or_train_bundle()
    for scenario, minutes in [
        (ScenarioId.COOLING_DEGRADATION, 100),
        (ScenarioId.BEARING_DETERIORATION, 120),
        (ScenarioId.OVERLOAD, 60),
    ]:
        stream = TelemetryStream(canonical_episode(scenario))
        engine = RiskEngine(bundle)
        for _ in range(minutes):
            stream.advance(60)
            a = engine.assess(list(stream.window))
        truth = stream.truth_window[-1]
        print(
            f"\n=== {scenario.value} @ {minutes} min | true eta={truth.cooling_efficiency:.2f} "
            f"health={truth.bearing_health:.2f}"
        )
        print(
            "risk:",
            {h.horizon_min: round(h.probability, 2) for h in a.horizons},
            "| diag:",
            a.diagnosis[0].label,
            round(a.diagnosis[0].probability, 2),
            "| anomaly:",
            a.anomaly.is_anomalous,
            "| cps:",
            [c.signal for c in a.change_points if c.detected],
        )
        s = stream.twin.state
        act = ActuatorSettings(
            load_multiplier=s.load_multiplier,
            speed_setpoint=s.speed_setpoint,
            aux_boost=s.aux_boost,
        )
        est = estimate_state(list(stream.window), act)
        print(
            f"estimate: eta={est.cooling_efficiency:.2f}±{est.cooling_efficiency_std:.2f} "
            f"trend={est.cooling_trend_per_h:+.2f}/h dmg={est.bearing_damage:.2f} "
            f"growth={est.bearing_growth_per_h:.2f}/h load={est.process_load:.2f} "
            f"trend={est.load_trend_per_h:+.2f}/h"
        )
        t0 = time.perf_counter()
        comp = compare_futures(
            [
                IncreaseCooling(boost=0.4),
                ReduceLoad(fraction=0.3),
                ReduceSpeed(fraction=0.3),
                ScheduleInspection(delay_minutes=10),
                ControlledShutdown(),
            ],
            estimate=est,
        )
        print(f"branching {comp.compute_ms:.0f} ms (wall {time.perf_counter() - t0:.1f}s)")
        for b in comp.branches:
            print(
                f"  {b.label:32s} fail={b.failure_incidence:.2f} ttf={b.median_time_to_failure_min} "
                f"Tp90={b.peak_temperature_p90_c:6.1f} Vp90={b.peak_vibration_p90_mm_s:5.2f} "
                f"obj={b.objective:9.0f} {b.cost_breakdown_mean.model_dump()}"
            )
        oracle = compare_futures(
            [ReduceLoad(fraction=0.3)], state_source="oracle", oracle_twin=stream.twin
        )
        print(
            "  oracle baseline fail:",
            oracle.branches[0].failure_incidence,
            "reduce 30% fail:",
            oracle.branches[1].failure_incidence,
        )

        snap = AgentSnapshot("smoke", stream.t_s, list(stream.window), act, a, stream.twin.clone())
        trace = asyncio.run(AgentOrchestrator(snap, Settings(MODEL_API_KEY=None)).run())
        rec = trace.recommendation
        print(f"agent: {trace.status} stages={'>'.join(trace.stage_history)}")
        print(
            f"  recommendation: {rec.status} {rec.action_label} by {rec.selected_by}; "
            f"rejected={[r.action_label for r in trace.rejected]}"
        )
        if trace.error:
            print("  error:", trace.error)


if __name__ == "__main__":
    main()
