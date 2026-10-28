"""Physics-inspired digital twin of a VFD-driven TEFC induction motor on a conveyor.

Model summary (see docs/simulation-model.md for the derivation and assumptions):

* Thermal: single lumped node.  C dT/dt = P_loss(T) - G(eta, speed) * (T - T_ambient).
  With losses held constant over a step the ODE is linear, so we use its exact solution
  T(t+dt) = T_ss + (T - T_ss) * exp(-G dt / C) instead of explicit Euler.
* Losses: copper ~ I^2 with copper resistance temperature coefficient, iron ~ speed^1.6,
  friction ~ speed * (1 + 3 * bearing damage).
* Cooling: G = G_rated * (f_nat + (1 - f_nat) * eta * (speed + aux_boost)). The shaft fan's
  airflow scales with speed, so slowing a self-ventilated motor at constant torque *reduces*
  cooling. That is deliberate and physically standard (low-speed derating).
* Bearing damage d = 1 - health grows exponentially once a defect exists:
  dd/dt = k * d * load^3 * speed * f(T), mirroring the cubic load dependence of L10 life.
* Vibration velocity RMS combines a speed/load dependent baseline with a bearing defect term.

Randomness comes from two independent streams spawned from the episode seed: process
disturbances (load and ambient fluctuations) and sensor noise. Each step consumes a fixed number
of draws from each stream regardless of state or actions, so two branches cloned from the same
state see *identical* disturbances (common random numbers) unless explicitly re-seeded.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np

from foresight.simulation.actions import (
    Action,
    ContinueOperation,
    ControlledShutdown,
    IncreaseCooling,
    ReduceLoad,
    ReduceSpeed,
    ScheduleInspection,
)
from foresight.simulation.params import (
    DEFAULT_ECONOMICS,
    DEFAULT_MOTOR,
    EconomicParameters,
    MotorParameters,
)
from foresight.simulation.scenarios import EpisodeConfig

STEP_S = 5.0
LOAD_NOISE_SIGMA = 0.015
LOAD_NOISE_THETA = 1.0 / 120.0  # Ornstein-Uhlenbeck mean reversion rate, 1/s
AMBIENT_NOISE_SIGMA = 0.6
AMBIENT_NOISE_THETA = 1.0 / 1800.0


@dataclass
class MotorState:
    t_s: float = 0.0
    temperature_c: float = 30.0
    ambient_c: float = 30.0
    bearing_damage: float = 0.0
    cooling_efficiency: float = 1.0
    load_multiplier: float = 1.0  # set by reduce_load (process feed reduction)
    speed_setpoint: float = 1.0
    aux_boost: float = 0.0
    overload_extra: float = 0.0
    overload_cleared: bool = False
    bearing_defect_active: bool = False
    cooling_fouling_active: bool = False
    cooling_fault_cleared: bool = False
    shutdown: bool = False
    failed: bool = False
    failure_mode: str | None = None
    failure_time_s: float | None = None
    inspection_due_s: float | None = None
    maintenance_until_s: float | None = None
    load_noise: float = 0.0
    ambient_noise: float = 0.0
    # accounting (used by the future-branching cost model)
    production_equiv_s: float = 0.0
    downtime_s: float = 0.0
    aux_cooling_s: float = 0.0
    operating_s: float = 0.0
    inspections: int = 0
    bearing_replacements: int = 0
    restarts: int = 0

    @property
    def bearing_health(self) -> float:
        return 1.0 - self.bearing_damage

    @property
    def running(self) -> bool:
        return not (self.shutdown or self.failed or self.maintenance_until_s is not None)


@dataclass(frozen=True)
class TrueOutputs:
    """Noise-free physical quantities at the current step."""

    load_fraction: float
    speed_fraction: float
    current_a: float
    voltage_v: float
    speed_rpm: float
    vibration_mm_s: float
    losses_w: float
    conductance_w_per_k: float


@dataclass(frozen=True)
class SensorReading:
    """What an operator / predictive model can observe."""

    t_s: float
    temperature_c: float
    ambient_c: float
    vibration_mm_s: float
    speed_rpm: float
    load_pct: float
    current_a: float
    voltage_v: float
    running: bool


@dataclass(frozen=True)
class GroundTruth:
    """Simulator internals that are *not* observable by the predictive models."""

    t_s: float
    bearing_health: float
    cooling_efficiency: float
    failed: bool
    failure_mode: str | None
    operating_hours: float
    in_maintenance: bool
    shutdown: bool


@dataclass
class ActionRecord:
    t_s: float
    action: Action
    applied: dict = field(default_factory=dict)


class MotorTwin:
    def __init__(
        self,
        config: EpisodeConfig,
        params: MotorParameters = DEFAULT_MOTOR,
        state: MotorState | None = None,
        economics: EconomicParameters = DEFAULT_ECONOMICS,
    ) -> None:
        self.config = config
        self.params = params
        self.economics = economics
        streams = np.random.SeedSequence(config.seed).spawn(2)
        self._disturbance_rng = np.random.Generator(np.random.PCG64(streams[0]))
        self._sensor_rng = np.random.Generator(np.random.PCG64(streams[1]))
        if state is None:
            state = MotorState(
                temperature_c=config.ambient_c,
                ambient_c=config.ambient_c,
                bearing_damage=1.0 - config.initial_bearing_health,
                cooling_efficiency=config.initial_cooling_efficiency,
                speed_setpoint=config.speed_setpoint,
            )
            # Start from thermal steady state so episodes don't begin with a warm-up transient.
            state.temperature_c = self._steady_state_temperature(state)
        self.state = state
        self.actions: list[ActionRecord] = []
        self.last_outputs: TrueOutputs = self.true_outputs()

    # ------------------------------------------------------------------ cloning
    def clone(self, reseed: int | None = None) -> MotorTwin:
        """Deep copy including RNG state. ``reseed`` replaces the random streams."""
        twin = copy.deepcopy(self)
        if reseed is not None:
            streams = np.random.SeedSequence(reseed).spawn(2)
            twin._disturbance_rng = np.random.Generator(np.random.PCG64(streams[0]))
            twin._sensor_rng = np.random.Generator(np.random.PCG64(streams[1]))
        return twin

    # ------------------------------------------------------------------ physics
    def _process_load(self, s: MotorState) -> float:
        return self.config.base_load + s.overload_extra

    def true_outputs(self, s: MotorState | None = None) -> TrueOutputs:
        s = s or self.state
        p = self.params
        if not s.running:
            return TrueOutputs(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, self._conductance(s, 0.0))
        speed = s.speed_setpoint
        load = max(0.0, self._process_load(s) * s.load_multiplier * (1.0 + s.load_noise))
        i_mag = p.magnetizing_current_fraction
        i_torque_rated = math.sqrt(1.0 - i_mag**2)
        current = p.rated_current_a * math.sqrt(i_mag**2 + (i_torque_rated * load) ** 2)
        copper = (
            p.copper_loss_rated_w
            * (current / p.rated_current_a) ** 2
            * (1.0 + p.copper_temp_coefficient * (s.temperature_c - p.copper_reference_temp_c))
        )
        iron = p.iron_loss_rated_w * speed**1.6
        friction = p.friction_loss_rated_w * speed * (1.0 + 3.0 * s.bearing_damage)
        rpm = p.synchronous_speed_rpm * speed * (1.0 - p.rated_slip * load)
        voltage = p.rated_voltage_v * speed * (1.0 - 0.01 * current / p.rated_current_a)
        base_vib = p.base_vibration_mm_s * speed**2 * (0.7 + 0.3 * load)
        bearing_vib = (
            p.bearing_vibration_gain_mm_s * s.bearing_damage**1.5 * speed * (0.6 + 0.4 * load)
        )
        vibration = math.sqrt(base_vib**2 + bearing_vib**2)
        return TrueOutputs(
            load_fraction=load,
            speed_fraction=speed,
            current_a=current,
            voltage_v=voltage,
            speed_rpm=rpm,
            vibration_mm_s=vibration,
            losses_w=copper + iron + friction,
            conductance_w_per_k=self._conductance(s, speed),
        )

    def _conductance(self, s: MotorState, speed: float) -> float:
        p = self.params
        airflow = speed + (s.aux_boost if speed > 0 else 0.0)
        forced = (1.0 - p.natural_convection_fraction) * s.cooling_efficiency * airflow
        return p.rated_conductance_w_per_k * (p.natural_convection_fraction + forced)

    def _steady_state_temperature(self, s: MotorState) -> float:
        # Fixed-point iteration because copper loss depends on temperature.
        for _ in range(50):
            out = self.true_outputs(s)
            s.temperature_c = s.ambient_c + out.losses_w / out.conductance_w_per_k
        return s.temperature_c

    # ------------------------------------------------------------------ actions
    def apply_action(self, action: Action) -> ActionRecord:
        """Apply an intervention. Values are clipped to what is *physically* possible here;
        policy limits are the verifier's job, not the simulator's."""
        s = self.state
        applied: dict = {}
        match action:
            case ReduceLoad(fraction=f):
                f = float(np.clip(f, 0.0, 0.95))
                s.load_multiplier = s.load_multiplier * (1.0 - f)
                applied = {"load_multiplier": s.load_multiplier}
            case ReduceSpeed(fraction=f):
                f = float(np.clip(f, 0.0, 0.9))
                s.speed_setpoint = s.speed_setpoint * (1.0 - f)
                applied = {"speed_setpoint": s.speed_setpoint}
            case IncreaseCooling(boost=b):
                s.aux_boost = float(np.clip(b, 0.0, self.params.max_aux_cooling_boost))
                applied = {"aux_boost": s.aux_boost}
            case ScheduleInspection(delay_minutes=d):
                s.inspection_due_s = s.t_s + max(0.0, d) * 60.0
                applied = {"inspection_due_s": s.inspection_due_s}
            case ControlledShutdown():
                s.shutdown = True
                applied = {"shutdown": True}
            case ContinueOperation():
                applied = {}
        record = ActionRecord(t_s=s.t_s, action=action, applied=applied)
        self.actions.append(record)
        return record

    # ------------------------------------------------------------------ stepping
    def _update_faults(self, dt: float) -> None:
        s, f = self.state, self.config.fault
        t = s.t_s
        if (
            f.cooling_fouling_onset_s is not None
            and t >= f.cooling_fouling_onset_s
            and not s.cooling_fault_cleared
        ):
            s.cooling_fouling_active = True
        if s.cooling_fouling_active and s.running:
            s.cooling_efficiency = max(
                f.cooling_floor, s.cooling_efficiency - f.cooling_fouling_rate_per_h * dt / 3600.0
            )
        if (
            f.bearing_defect_onset_s is not None
            and t >= f.bearing_defect_onset_s
            and not s.bearing_defect_active
            and s.bearing_replacements == 0
        ):
            s.bearing_defect_active = True
            s.bearing_damage = max(s.bearing_damage, f.bearing_initial_damage)
        if f.overload_onset_s is not None and t >= f.overload_onset_s and not s.overload_cleared:
            progress = min(1.0, (t - f.overload_onset_s) / (f.overload_ramp_h * 3600.0))
            s.overload_extra = progress * (f.overload_target_load - self.config.base_load)

    def _update_bearing(self, out: TrueOutputs, dt: float) -> None:
        s, p = self.state, self.params
        if not s.running:
            return
        thermal_factor = 1.0 + max(0.0, s.temperature_c - 90.0) / 40.0
        stress = out.load_fraction**3 * out.speed_fraction * thermal_factor
        growth = p.bearing_background_growth_per_s
        if s.bearing_defect_active:
            growth += self.config.fault.bearing_growth_per_h / 3600.0 * s.bearing_damage
        s.bearing_damage = min(1.0, s.bearing_damage + growth * stress * dt)

    def _handle_maintenance(self) -> None:
        s = self.state
        if s.failed or s.shutdown:
            return
        if s.inspection_due_s is not None and s.t_s >= s.inspection_due_s:
            econ = self.economics
            duration_h = econ.inspection_downtime_h
            s.inspections += 1
            # Inspection fixes root causes: blocked inlet cleared and fins cleaned, conveyor
            # build-up removed, worn bearing replaced.
            s.cooling_efficiency = 1.0
            s.cooling_fouling_active = False
            s.cooling_fault_cleared = True
            s.overload_extra = 0.0
            s.overload_cleared = True
            if s.bearing_damage > 0.2:
                s.bearing_damage = 0.0
                s.bearing_defect_active = False
                s.bearing_replacements += 1
                duration_h += econ.bearing_replacement_extra_downtime_h
            s.inspection_due_s = None
            s.maintenance_until_s = s.t_s + duration_h * 3600.0
        if s.maintenance_until_s is not None and s.t_s >= s.maintenance_until_s:
            s.maintenance_until_s = None
            s.restarts += 1

    def step(self, dt: float = STEP_S) -> tuple[SensorReading, GroundTruth]:
        s, p = self.state, self.params

        # Fixed-count random draws (common random numbers across branches).
        d_load, d_amb = self._disturbance_rng.standard_normal(2)
        noise = self._sensor_rng.standard_normal(7)

        s.load_noise += (
            -LOAD_NOISE_THETA * s.load_noise * dt
            + LOAD_NOISE_SIGMA * math.sqrt(2 * LOAD_NOISE_THETA * dt) * d_load
        )
        s.ambient_noise += -AMBIENT_NOISE_THETA * s.ambient_noise * dt + AMBIENT_NOISE_SIGMA * (
            math.sqrt(2 * AMBIENT_NOISE_THETA * dt) * d_amb
        )
        s.ambient_c = self.config.ambient_c + s.ambient_noise

        self._handle_maintenance()
        self._update_faults(dt)
        out = self.true_outputs()

        # Exact solution of the linear thermal ODE over the step.
        g = out.conductance_w_per_k
        t_ss = s.ambient_c + out.losses_w / g
        s.temperature_c = t_ss + (s.temperature_c - t_ss) * math.exp(
            -g * dt / p.thermal_capacitance_j_per_k
        )
        self._update_bearing(out, dt)

        if s.running:
            s.operating_s += dt
            s.production_equiv_s += dt * min(1.0, s.load_multiplier) * s.speed_setpoint
            if s.aux_boost > 0:
                s.aux_cooling_s += dt
        else:
            s.downtime_s += dt
        s.t_s += dt

        if not s.failed:
            if s.temperature_c >= p.temperature_failure_c:
                self._fail("thermal")
            elif s.bearing_health <= p.bearing_failure_health:
                self._fail("bearing")

        running = s.running
        if running and out.speed_fraction == 0.0:  # restarted this step (maintenance finished)
            out = self.true_outputs()
        self.last_outputs = out
        reading = SensorReading(
            t_s=s.t_s,
            temperature_c=s.temperature_c + 0.3 * noise[0],
            ambient_c=s.ambient_c + 0.2 * noise[1],
            vibration_mm_s=max(0.0, out.vibration_mm_s * (1.0 + 0.04 * noise[2]))
            if running
            else 0.0,
            speed_rpm=max(0.0, out.speed_rpm + 2.0 * noise[3]) if running else 0.0,
            load_pct=max(0.0, 100.0 * out.load_fraction + 0.8 * noise[4]) if running else 0.0,
            current_a=max(0.0, out.current_a * (1.0 + 0.01 * noise[5])) if running else 0.0,
            voltage_v=max(0.0, out.voltage_v + 1.0 * noise[6]) if running else 0.0,
            running=running,
        )
        truth = GroundTruth(
            t_s=s.t_s,
            bearing_health=s.bearing_health,
            cooling_efficiency=s.cooling_efficiency,
            failed=s.failed,
            failure_mode=s.failure_mode,
            operating_hours=s.operating_s / 3600.0,
            in_maintenance=s.maintenance_until_s is not None,
            shutdown=s.shutdown,
        )
        return reading, truth

    def _fail(self, mode: str) -> None:
        s = self.state
        s.failed = True
        s.failure_mode = mode
        s.failure_time_s = s.t_s
        s.inspection_due_s = None


def run_episode(
    config: EpisodeConfig,
    sample_every_s: float = 10.0,
    stop_on_failure: bool = True,
) -> tuple[list[SensorReading], list[GroundTruth], MotorTwin]:
    """Simulate a whole episode without interventions, sampling every ``sample_every_s``."""
    twin = MotorTwin(config)
    readings: list[SensorReading] = []
    truths: list[GroundTruth] = []
    steps_per_sample = max(1, round(sample_every_s / STEP_S))
    n_steps = int(config.duration_s / STEP_S)
    for i in range(1, n_steps + 1):
        reading, truth = twin.step()
        if i % steps_per_sample == 0 or truth.failed:
            readings.append(reading)
            truths.append(truth)
        if truth.failed and stop_on_failure:
            break
    return readings, truths, twin
