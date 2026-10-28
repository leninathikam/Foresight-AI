"""Nominal (datasheet) motor model used to build physics-informed features and state estimates.

These functions only use *observable* signals plus nameplate parameters that a plant would
know from the motor datasheet. They never read simulator ground truth.
"""

from __future__ import annotations

import numpy as np

from foresight.simulation.params import DEFAULT_MOTOR, MotorParameters


def speed_fraction(speed_rpm: np.ndarray, p: MotorParameters = DEFAULT_MOTOR) -> np.ndarray:
    return np.asarray(speed_rpm) / p.synchronous_speed_rpm


def load_from_current(current_a: np.ndarray, p: MotorParameters = DEFAULT_MOTOR) -> np.ndarray:
    """Invert the current model: torque fraction implied by measured current."""
    i = np.asarray(current_a) / p.rated_current_a
    m = p.magnetizing_current_fraction
    return np.sqrt(np.clip(i**2 - m**2, 0.0, None)) / np.sqrt(1.0 - m**2)


def nominal_losses_w(
    current_a: np.ndarray,
    speed_frac: np.ndarray,
    temperature_c: np.ndarray,
    bearing_damage: np.ndarray | float = 0.0,
    p: MotorParameters = DEFAULT_MOTOR,
) -> np.ndarray:
    copper = (
        p.copper_loss_rated_w
        * (np.asarray(current_a) / p.rated_current_a) ** 2
        * (
            1.0
            + p.copper_temp_coefficient * (np.asarray(temperature_c) - p.copper_reference_temp_c)
        )
    )
    iron = p.iron_loss_rated_w * np.clip(speed_frac, 0, None) ** 1.6
    friction = p.friction_loss_rated_w * speed_frac * (1.0 + 3.0 * np.asarray(bearing_damage))
    return copper + iron + friction


def nominal_conductance(
    speed_frac: np.ndarray, aux_boost: float = 0.0, p: MotorParameters = DEFAULT_MOTOR
):
    airflow = np.asarray(speed_frac) + aux_boost
    return p.rated_conductance_w_per_k * (
        p.natural_convection_fraction + (1.0 - p.natural_convection_fraction) * airflow
    )


def cooling_efficiency_from_conductance(
    conductance: np.ndarray,
    speed_frac: np.ndarray,
    aux_boost: float = 0.0,
    p: MotorParameters = DEFAULT_MOTOR,
) -> np.ndarray:
    airflow = np.clip(np.asarray(speed_frac) + aux_boost, 1e-3, None)
    forced = np.asarray(conductance) / p.rated_conductance_w_per_k - p.natural_convection_fraction
    return forced / ((1.0 - p.natural_convection_fraction) * airflow)


def nominal_base_vibration(
    speed_frac: np.ndarray, load_frac: np.ndarray, p: MotorParameters = DEFAULT_MOTOR
):
    return p.base_vibration_mm_s * np.asarray(speed_frac) ** 2 * (0.7 + 0.3 * np.asarray(load_frac))


def bearing_damage_from_vibration(
    vibration: np.ndarray,
    speed_frac: np.ndarray,
    load_frac: np.ndarray,
    p: MotorParameters = DEFAULT_MOTOR,
) -> np.ndarray:
    """Invert the vibration model for bearing damage (0 = healthy, 1 = destroyed)."""
    base = nominal_base_vibration(speed_frac, load_frac, p)
    excess = np.sqrt(np.clip(np.asarray(vibration) ** 2 - base**2, 0.0, None))
    scale = (
        p.bearing_vibration_gain_mm_s
        * np.clip(speed_frac, 1e-3, None)
        * (0.6 + 0.4 * np.asarray(load_frac))
    )
    return np.clip(excess / scale, 0.0, 1.0) ** (2.0 / 3.0)


def nan_slope(t: np.ndarray, y: np.ndarray) -> float:
    """Least-squares slope ignoring NaNs. Returns NaN with fewer than 3 valid points."""
    mask = np.isfinite(y) & np.isfinite(t)
    if mask.sum() < 3:
        return float("nan")
    tt, yy = t[mask], y[mask]
    tc = tt - tt.mean()
    denom = float(np.dot(tc, tc))
    if denom <= 0:
        return float("nan")
    return float(np.dot(tc, yy - yy.mean()) / denom)
