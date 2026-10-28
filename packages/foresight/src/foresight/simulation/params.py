"""Physical and economic parameters of the simulated motor-driven conveyor.

The values describe a generic 15 kW, 4-pole, totally-enclosed fan-cooled (TEFC) induction
motor on a variable-frequency drive, driving a constant-torque conveyor load. They are chosen
to be physically plausible, not to match any specific certified product. Every relationship
that uses them is documented in ``docs/simulation-model.md``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MotorParameters:
    # Electrical rating
    rated_power_kw: float = 15.0
    rated_voltage_v: float = 400.0
    rated_current_a: float = 28.5
    synchronous_speed_rpm: float = 1500.0
    rated_slip: float = 0.02  # 1470 rpm at rated torque
    magnetizing_current_fraction: float = 0.35  # no-load current / rated current

    # Losses at rated operating point (sum ~1.15 kW, efficiency ~93 %)
    copper_loss_rated_w: float = 650.0  # at 75 °C winding temperature
    iron_loss_rated_w: float = 350.0  # at rated speed / frequency
    friction_loss_rated_w: float = 150.0  # with healthy bearings at rated speed
    copper_temp_coefficient: float = 0.00393  # 1/K, copper resistivity
    copper_reference_temp_c: float = 75.0

    # Lumped single-node thermal model of the winding
    thermal_capacitance_j_per_k: float = 30_000.0
    rated_conductance_w_per_k: float = 14.4  # gives an 80 K rise at rated losses
    natural_convection_fraction: float = 0.25  # cooling left with fan stopped / fully fouled
    max_aux_cooling_boost: float = 0.4  # auxiliary blower capacity (extra airflow fraction)

    # Thermal limits (insulation class F)
    temperature_warning_c: float = 130.0
    temperature_failure_c: float = 155.0

    # Vibration model (velocity RMS, mm/s) and ISO 10816-3 group-2 style zones
    base_vibration_mm_s: float = 0.9
    bearing_vibration_gain_mm_s: float = 10.0
    vibration_alarm_mm_s: float = 4.5
    vibration_trip_mm_s: float = 7.1

    # Bearing damage growth: d(damage)/dt = k * damage * load^3 * speed * f(T)
    bearing_failure_health: float = 0.10
    bearing_background_growth_per_s: float = 2.0e-7

    # Load envelope
    max_safe_load_fraction: float = 1.0
    max_allowed_load_fraction: float = 1.15  # short-term service factor


@dataclass(frozen=True)
class EconomicParameters:
    """Cost assumptions used by the future-branching objective. All values are illustrative."""

    production_margin_per_hour: float = 600.0  # at 100 % throughput
    unplanned_failure_repair_cost: float = 18_000.0
    unplanned_failure_downtime_h: float = 12.0
    inspection_cost: float = 600.0
    inspection_downtime_h: float = 1.5
    bearing_replacement_cost: float = 1_200.0
    bearing_replacement_extra_downtime_h: float = 2.0
    aux_cooling_cost_per_hour: float = 8.0
    restart_cost: float = 200.0


DEFAULT_MOTOR = MotorParameters()
DEFAULT_ECONOMICS = EconomicParameters()
