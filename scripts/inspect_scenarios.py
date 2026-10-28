"""Print a compact summary of each canonical scenario (failure time, peak values)."""

from foresight.simulation import ScenarioId, canonical_episode, run_episode

for scenario in ScenarioId:
    readings, truths, twin = run_episode(canonical_episode(scenario))
    last = readings[-1]
    peak_t = max(r.temperature_c for r in readings)
    peak_v = max(r.vibration_mm_s for r in readings)
    fail = twin.state.failure_time_s
    print(
        f"{scenario.value:24s} failure={twin.state.failure_mode!s:8s} "
        f"t_fail={'-' if fail is None else f'{fail / 60:6.1f} min'}  "
        f"peakT={peak_t:6.1f}C peakVib={peak_v:5.2f}  "
        f"start T={readings[0].temperature_c:5.1f} I={readings[0].current_a:4.1f}A "
        f"last load={last.load_pct:5.1f}% health={truths[-1].bearing_health:.2f} "
        f"eta={truths[-1].cooling_efficiency:.2f}"
    )
