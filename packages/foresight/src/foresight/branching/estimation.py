"""Digital-twin synchronisation: estimate hidden machine state from observable telemetry.

The future-branching engine must not peek at simulator internals. Instead it fits the
datasheet model to recent telemetry:

* cooling efficiency from the thermal balance  C dT/dt = P_loss - G (T - T_amb),
  solved for G over several overlapping 10-minute windows, then inverted for eta;
* bearing damage by inverting the vibration model; its exponential growth rate from the
  log-damage trend normalised by mechanical stress;
* process load and its trend from the load channel and the known drive commands.

Uncertainty is the residual spread of the trend fits. Estimates are approximate by design and
labelled as such everywhere they are shown.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, Field

from foresight.prediction import physics
from foresight.prediction.features import WindowArrays
from foresight.simulation.params import DEFAULT_MOTOR
from foresight.telemetry import TelemetrySample

# Vibration noise biases inferred damage to ~0.1 on a healthy bearing; below this a defect is not
# distinguishable from noise.
DETECTABLE_DAMAGE = 0.15
# Trend fits over a shorter run (e.g. just after a restart) are dominated by start-up transients.
MIN_TREND_SPAN_S = 20 * 60.0


class ActuatorSettings(BaseModel):
    """Commanded settings. Known to the controller, so not 'hidden' state."""

    load_multiplier: float = 1.0
    speed_setpoint: float = 1.0
    aux_boost: float = 0.0


class StateEstimate(BaseModel):
    t_s: float
    temperature_c: float
    ambient_c: float
    cooling_efficiency: float
    cooling_efficiency_std: float
    cooling_trend_per_h: float = Field(description="d(eta)/dt, negative = degrading")
    bearing_damage: float
    bearing_damage_std: float
    bearing_growth_per_h: float
    process_load: float = Field(description="Applied load before the operator's load reduction")
    baseline_process_load: float = Field(
        description="Process load before any build-up observed in the window (removable by inspection)"
    )
    load_trend_per_h: float
    # Standard errors of the three trend fits; None = not identifiable from the data.
    cooling_trend_se_per_h: float | None = None
    bearing_growth_se_per_h: float | None = None
    load_trend_se_per_h: float | None = None
    actuators: ActuatorSettings
    method: str = "datasheet-model inversion over the last 40 min of telemetry"
    notes: list[str] = Field(default_factory=list)


def _window_mask(t: np.ndarray, t_end: float, seconds: float) -> np.ndarray:
    return (t > t_end - seconds) & (t <= t_end)


def _linear_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Return (intercept at x[-1], slope, residual std)."""
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 2:
        v = float(np.nanmean(y)) if np.isfinite(y).any() else float("nan")
        return v, 0.0, float("nan")
    xx, yy = x[mask], y[mask]
    slope, intercept = np.polyfit(xx, yy, 1) if len(xx) >= 2 else (0.0, yy.mean())
    resid = yy - (slope * xx + intercept)
    std = float(np.std(resid, ddof=1)) if len(xx) > 2 else float("nan")
    return float(slope * xx[-1] + intercept), float(slope), std


def slope_standard_error(x: np.ndarray, y: np.ndarray) -> float:
    """OLS standard error of the slope; inf when fewer than 3 valid points.

    Overlapping windows and autocorrelated samples make this an underestimate, so trends look
    more significant than they are; the information gate errs towards acting.
    """
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 3:
        return float("inf")
    xx, yy = x[mask], y[mask]
    sxx = float(np.sum((xx - xx.mean()) ** 2))
    if sxx <= 0:
        return float("inf")
    slope, intercept = np.polyfit(xx, yy, 1)
    ssr = float(np.sum((yy - (slope * xx + intercept)) ** 2))
    return float(np.sqrt(ssr / (len(xx) - 2) / sxx))


def _batch_slope_se(x: np.ndarray, y: np.ndarray, block_h: float) -> float:
    """Slope standard error from block means (batch means), for autocorrelated raw samples."""
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 3:
        return float("inf")
    xx, yy = x[mask], y[mask]
    idx = np.floor((xx - xx[0]) / block_h).astype(int)
    bx = np.array([xx[idx == i].mean() for i in np.unique(idx)])
    by = np.array([yy[idx == i].mean() for i in np.unique(idx)])
    return slope_standard_error(bx, by)


def estimate_state(
    samples: Sequence[TelemetrySample], actuators: ActuatorSettings
) -> StateEstimate:
    if len(samples) < 30:
        raise ValueError("Need at least 5 minutes of telemetry to estimate machine state")
    notes: list[str] = []
    # Maintenance or a shutdown changes the machine, so only the current run segment describes it.
    stopped = [i for i, s in enumerate(samples) if not s.running]
    if stopped and stopped[-1] < len(samples) - 1:
        samples = samples[stopped[-1] + 1 :]
        minutes = (samples[-1].t_s - samples[0].t_s) / 60.0
        notes.append(f"Using only the {minutes:.0f} min since the last restart")
    if len(samples) < 30:
        raise ValueError("Motor restarted less than 5 minutes ago; state not yet identifiable")
    arr = WindowArrays.from_samples(samples)
    v, t = arr.values, arr.t
    t_end = float(t[-1])
    p = DEFAULT_MOTOR
    trends_identifiable = t_end - float(t[0]) >= MIN_TREND_SPAN_S
    if not trends_identifiable:
        notes.append(
            f"Less than {MIN_TREND_SPAN_S / 60:.0f} min of running data: trends not estimated"
        )

    recent = _window_mask(t, t_end, 300) & arr.running
    if recent.sum() < 10:
        raise ValueError("Motor not running long enough in the last 5 minutes to estimate state")

    temp_now = float(np.nanmedian(v["temperature_c"][_window_mask(t, t_end, 60)]))
    amb_now = float(np.nanmedian(v["ambient_c"][recent]))
    speed = v["speed_rpm"] / p.synchronous_speed_rpm
    load = v["load_pct"] / 100.0

    # --- bearing damage per sample (vibration inversion), then trend of log-damage
    damage = physics.bearing_damage_from_vibration(v["vibration_mm_s"], speed, load)
    damage = np.where(arr.running, damage, np.nan)

    # --- cooling efficiency in overlapping 10-min windows every 5 min over the last 40 min
    eta_t, eta_v, dmg_t, dmg_v = [], [], [], []
    for k in range(7):
        w_end = t_end - k * 300.0
        m = _window_mask(t, w_end, 600) & arr.running
        if m.sum() < 30:
            continue
        tm = t[m] / 60.0
        temp_w = v["temperature_c"][m]
        slope = physics.nan_slope(tm, temp_w) / 60.0  # K/s
        rise = float(np.nanmean(temp_w - v["ambient_c"][m]))
        d_w = float(np.nanmedian(damage[m]))
        losses = float(
            np.nanmean(physics.nominal_losses_w(v["current_a"][m], speed[m], temp_w, d_w))
        )
        if not np.isfinite(slope) or rise < 5.0:
            continue
        g = (losses - p.thermal_capacitance_j_per_k * slope) / rise
        eta = float(
            physics.cooling_efficiency_from_conductance(
                g, np.nanmedian(speed[m]), actuators.aux_boost
            )
        )
        eta_t.append(w_end / 3600.0)
        eta_v.append(float(np.clip(eta, 0.0, 1.2)))
        dmg_t.append(w_end / 3600.0)
        dmg_v.append(d_w)

    order_eta = np.argsort(eta_t)
    eta_x, eta_y = np.array(eta_t)[order_eta], np.array(eta_v)[order_eta]
    if len(eta_y) >= 3:
        eta_now, eta_slope, eta_std = _linear_fit(eta_x, eta_y)
    elif len(eta_y):
        eta_now, eta_slope, eta_std = float(eta_y[-1]), 0.0, float("nan")
        notes.append("Short running history: cooling trend not estimated")
    else:
        eta_now, eta_slope, eta_std = 1.0, 0.0, float("nan")
        notes.append("Thermal balance not identifiable (rise < 5 K); assuming nominal cooling")
    eta_std = 0.05 if not np.isfinite(eta_std) else max(eta_std, 0.03)
    eta_slope_se = slope_standard_error(eta_x, eta_y)

    dmg_x, dmg_y = np.array(dmg_t)[np.argsort(dmg_t)], np.array(dmg_v)[np.argsort(dmg_t)]
    dmg_now = float(np.nanmedian(damage[recent]))
    growth = 0.0
    growth_se = float("inf")
    dmg_std = 0.02
    if dmg_now > DETECTABLE_DAMAGE and len(dmg_y) >= 3 and np.all(dmg_y > 0.01):
        _, log_slope, log_std = _linear_fit(dmg_x, np.log(dmg_y))
        thermal_factor = 1.0 + max(0.0, temp_now - 90.0) / 40.0
        stress = (
            float(np.nanmedian(load[recent])) ** 3
            * float(np.nanmedian(speed[recent]))
            * thermal_factor
        )
        growth = max(0.0, log_slope / max(stress, 1e-3))
        growth_se = slope_standard_error(dmg_x, np.log(dmg_y)) / max(stress, 1e-3)
        dmg_std = max(0.02, dmg_now * (log_std if np.isfinite(log_std) else 0.2))
    elif dmg_now <= DETECTABLE_DAMAGE:
        notes.append("Vibration within datasheet baseline: no bearing defect detectable")

    load_now = float(np.nanmedian(load[recent]))
    m30 = _window_mask(t, t_end, 1800) & arr.running
    load_slope = physics.nan_slope(t[m30] / 3600.0, load[m30])
    load_slope = 0.0 if not np.isfinite(load_slope) else load_slope
    load_slope_se = _batch_slope_se(t[m30] / 3600.0, load[m30], block_h=300.0 / 3600.0)
    multiplier = max(actuators.load_multiplier, 1e-3)

    # Load added since the start of the window is attributed to removable build-up (overload
    # scenario assumption); the earliest 10 minutes give the pre-ramp process baseline.
    baseline_load = load_now
    if t_end - t[0] >= 2400:
        early = (t <= t[0] + 600) & arr.running
        if early.sum() >= 20:
            baseline_load = min(load_now, float(np.nanmedian(load[early])))
    if load_now - baseline_load < 0.05 or load_slope <= 0.03:
        baseline_load = load_now
    if not trends_identifiable:
        eta_slope, growth, load_slope = 0.0, 0.0, 0.0
        eta_slope_se = growth_se = load_slope_se = float("inf")
        baseline_load = load_now

    def se(x: float, scale: float = 1.0) -> float | None:
        return float(x / scale) if np.isfinite(x) else None

    return StateEstimate(
        t_s=t_end,
        temperature_c=temp_now,
        ambient_c=amb_now,
        cooling_efficiency=float(np.clip(eta_now, 0.05, 1.0)),
        cooling_efficiency_std=float(eta_std),
        cooling_trend_per_h=float(min(eta_slope, 0.0)),
        bearing_damage=float(np.clip(dmg_now, 0.0, 1.0)),
        bearing_damage_std=float(dmg_std),
        bearing_growth_per_h=float(growth),
        process_load=load_now / multiplier,
        baseline_process_load=baseline_load / multiplier,
        load_trend_per_h=float(load_slope) / multiplier,
        cooling_trend_se_per_h=se(eta_slope_se),
        bearing_growth_se_per_h=se(growth_se),
        load_trend_se_per_h=se(load_slope_se, multiplier),
        actuators=actuators,
        notes=notes,
    )
