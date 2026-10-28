# Digital twin — model notes

This is a **physics-inspired teaching / research simulator**, not a certified industrial twin. Parameters live in `packages/foresight/src/foresight/simulation/params.py`.

## Thermal

Single lumped winding node:

\[
C \frac{dT}{dt} = P_\text{loss}(T) - G(\eta, \omega)\,(T - T_\text{amb})
\]

With losses held constant over a 5 s step, the ODE is linear and integrated exactly:

\[
T(t+\Delta t) = T_{ss} + (T - T_{ss})\,e^{-G\Delta t / C}
\]

Losses include copper (\(I^2\) with temperature coefficient), iron (\(\propto \omega^{1.6}\)), and friction (\(\propto \omega \cdot (1 + 3d)\) where \(d\) is bearing damage).

Cooling conductance \(G\) scales with shaft-fan airflow (speed) and auxiliary boost. Slowing a self-ventilated motor at constant torque **reduces** cooling — deliberate and physically standard.

## Bearing damage

Damage \(d = 1 - \text{health}\) grows exponentially once a defect is active, with cubic load dependence inspired by classical L10 life models. Vibration RMS combines a speed/load baseline with a defect term.

## Scenarios

| ID | Mechanism |
|----|-----------|
| `cooling_degradation` | Cooling efficiency fouling over time → thermal runaway risk |
| `bearing_deterioration` | Bearing defect onset → rising vibration / damage |
| `overload` | Applied load climbs past safe fraction → thermal + mechanical stress |
| `healthy` | No injected fault (control) |

Each episode uses a deterministic seed. Process and sensor RNG streams are independent so cloned future branches share matched disturbances (common random numbers).

## Interventions

- Reduce load / speed
- Increase auxiliary cooling
- Schedule inspection (repairs after delay)
- Controlled shutdown
- Continue operation (baseline)

## Economics

Illustrative costs in `EconomicParameters` (lost production, repair, downtime, intervention, deferred maintenance). Used for ranking futures — not market prices.
