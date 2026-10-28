"""Rolling-window feature extraction from telemetry (observable signals only)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from foresight.prediction import physics
from foresight.simulation.params import DEFAULT_MOTOR
from foresight.telemetry import CHANNELS, TelemetrySample

FEATURE_NAMES: tuple[str, ...] = (
    "temperature_c",
    "temp_rise_k",
    "temp_slope_10m",
    "temp_slope_30m",
    "rise_residual_k",
    "cooling_index",
    "vibration_mm_s",
    "vib_slope_30m",
    "vib_std_5m",
    "bearing_index",
    "current_ratio",
    "load_frac",
    "load_slope_30m",
    "speed_frac",
    "minutes_to_temp_limit",
    "missing_fraction",
)

FEATURE_DESCRIPTIONS: dict[str, str] = {
    "temperature_c": "Winding temperature, 5-min median (°C)",
    "temp_rise_k": "Temperature rise over ambient (K)",
    "temp_slope_10m": "Temperature trend over 10 min (K/min)",
    "temp_slope_30m": "Temperature trend over 30 min (K/min)",
    "rise_residual_k": "Measured rise minus datasheet steady-state rise for the measured current (K)",
    "cooling_index": "Apparent cooling efficiency from thermal balance (1 = nominal)",
    "vibration_mm_s": "Vibration velocity RMS, 5-min median (mm/s)",
    "vib_slope_30m": "Vibration trend over 30 min (mm/s per min)",
    "vib_std_5m": "Vibration variability over 5 min (mm/s)",
    "bearing_index": "Bearing damage implied by vibration above the datasheet baseline (0-1)",
    "current_ratio": "Current / rated current",
    "load_frac": "Applied load / rated torque",
    "load_slope_30m": "Load trend over 30 min (fraction per min)",
    "speed_frac": "Speed / synchronous speed",
    "minutes_to_temp_limit": "Linear extrapolation of time to 155 °C (min, capped at 600)",
    "missing_fraction": "Fraction of missing/invalid values in the 10-min window",
}

MIN_VALID_SAMPLES = 20
LIMIT_CAP_MIN = 600.0


@dataclass
class WindowArrays:
    t: np.ndarray
    values: dict[str, np.ndarray]
    running: np.ndarray

    @classmethod
    def from_samples(cls, samples: Sequence[TelemetrySample]) -> WindowArrays:
        t = np.array([s.t_s for s in samples], dtype=float)
        values = {
            c: np.array(
                [np.nan if s.values[c] is None else s.values[c] for s in samples], dtype=float
            )
            for c in CHANNELS
        }
        running = np.array([s.running for s in samples], dtype=bool)
        return cls(t=t, values=values, running=running)


def _window(arr: WindowArrays, end: int, seconds: float) -> slice:
    t_end = arr.t[end]
    start = int(np.searchsorted(arr.t, t_end - seconds, side="right"))
    return slice(start, end + 1)


def _median(x: np.ndarray) -> float:
    return float(np.nanmedian(x)) if np.isfinite(x).any() else float("nan")


def compute_features(arr: WindowArrays, end: int) -> np.ndarray | None:
    """Features for the window ending at index ``end``. ``None`` if the motor is stopped or
    the window has too little valid data to say anything."""
    if not arr.running[end]:
        return None
    w5, w10, w30 = _window(arr, end, 300), _window(arr, end, 600), _window(arr, end, 1800)
    v = arr.values
    running10 = arr.running[w10]
    if (
        running10.sum() < MIN_VALID_SAMPLES
        or np.isfinite(v["temperature_c"][w10]).sum() < MIN_VALID_SAMPLES
    ):
        return None
    t_min = arr.t / 60.0

    temp = _median(v["temperature_c"][w5])
    amb = _median(v["ambient_c"][w5])
    vib = _median(v["vibration_mm_s"][w5])
    current = _median(v["current_a"][w5])
    speed = _median(v["speed_rpm"][w5]) / DEFAULT_MOTOR.synchronous_speed_rpm
    load = _median(v["load_pct"][w5]) / 100.0

    slope10 = physics.nan_slope(t_min[w10], v["temperature_c"][w10])
    slope30 = physics.nan_slope(t_min[w30], v["temperature_c"][w30])

    rise = temp - amb
    losses = float(physics.nominal_losses_w(current, speed, temp))
    g_nominal = float(physics.nominal_conductance(speed))
    rise_residual = rise - losses / g_nominal
    # Thermal balance: C dT/dt = P - G * rise  =>  G_apparent = (P - C dT/dt) / rise
    c = DEFAULT_MOTOR.thermal_capacitance_j_per_k
    dTdt = (slope10 if np.isfinite(slope10) else 0.0) / 60.0
    g_apparent = (losses - c * dTdt) / max(rise, 1.0)
    cooling_index = float(physics.cooling_efficiency_from_conductance(g_apparent, speed))

    vib_slope = physics.nan_slope(t_min[w30], v["vibration_mm_s"][w30])
    vib_std = (
        float(np.nanstd(v["vibration_mm_s"][w5]))
        if np.isfinite(v["vibration_mm_s"][w5]).sum() > 2
        else 0.0
    )
    bearing_index = float(physics.bearing_damage_from_vibration(vib, speed, load))
    load_slope = physics.nan_slope(t_min[w30], v["load_pct"][w30] / 100.0)

    if np.isfinite(slope30) and slope30 > 1e-3:
        to_limit = (DEFAULT_MOTOR.temperature_failure_c - temp) / slope30
        to_limit = float(np.clip(to_limit, 0.0, LIMIT_CAP_MIN))
    else:
        to_limit = LIMIT_CAP_MIN

    window_vals = np.stack([v[ch][w10] for ch in CHANNELS])
    missing = float(1.0 - np.isfinite(window_vals).mean())

    feats = np.array(
        [
            temp,
            rise,
            slope10,
            slope30,
            rise_residual,
            cooling_index,
            vib,
            vib_slope,
            vib_std,
            bearing_index,
            current / DEFAULT_MOTOR.rated_current_a,
            load,
            load_slope,
            speed,
            to_limit,
            missing,
        ],
        dtype=float,
    )
    # Remaining NaNs (e.g. a channel fully dropped out) become 0-trend / neutral values.
    return np.nan_to_num(feats, nan=0.0)


def features_from_samples(samples: Sequence[TelemetrySample]) -> np.ndarray | None:
    if not samples:
        return None
    arr = WindowArrays.from_samples(samples)
    return compute_features(arr, len(samples) - 1)
