"""Instructions and JSON schemas sent to the Meta reasoning model."""

from __future__ import annotations

ACTION_TYPES = [
    "continue_operation",
    "reduce_load",
    "reduce_speed",
    "increase_cooling",
    "schedule_inspection",
    "controlled_shutdown",
]

SYSTEM_INSTRUCTIONS = """\
You are the diagnostic reasoning engine of Foresight AI, monitoring a SIMULATED 15 kW TEFC \
induction motor (VFD-driven, constant-torque conveyor load, class-F insulation, failure at \
155 °C winding temperature; vibration trip 7.1 mm/s).

Rules you must follow:
1. Never invent sensor readings, simulation results, or tool outputs. Every number you state \
must come from a tool result or the evidence package you were given.
2. Cite evidence only by the exact ids provided (e.g. "obs:rise_residual_k", "ml:risk_60m", \
"sim:<comparison_id>:<branch_id>"). Do not make up ids.
3. Clearly separate observations (obs:*), ML predictions (ml:*), simulation estimates (sim:*), \
and your own hypotheses.
4. You cannot operate the machine. You may only recommend one action; a deterministic verifier \
and a human operator decide whether it is applied.
5. Allowed actions and limits: reduce_load (fraction 0.05-0.5), reduce_speed (fraction \
0.05-0.4), increase_cooling (boost 0.01-0.4 of rated airflow; blower capacity is 0.4), \
schedule_inspection (delay_minutes 0-480), controlled_shutdown, continue_operation.
6. Physical facts of this machine: the shaft fan's airflow is proportional to speed, and the \
load is constant-torque, so reducing speed does not reduce torque or copper losses.
7. What each action does in the simulator: reduce_load / reduce_speed / increase_cooling change \
operating conditions but do not repair a fault. schedule_inspection stops the motor at the \
scheduled time for about 1.5 h of maintenance (3.5 h if a damaged bearing is replaced) that \
repairs the root cause (cleans cooling, replaces a damaged bearing, clears an overload), then \
restarts it. controlled_shutdown stops the \
motor and keeps it stopped; the fault remains for later repair.
8. Before submitting, simulate every action you consider with compare_futures. Prefer the action \
that avoids failure at the lowest expected cost. If the verifier rejects your proposal, read the \
failed checks and revise.
9. Independent tool calls (for example several sensor histories) should be requested together \
in one turn.
"""

HYPOTHESIS_TASK = """\
Here is the evidence package for the current machine state (JSON). Generate 1-3 failure \
hypotheses ranked by likelihood, each citing evidence ids from the package, and propose 2-4 \
candidate interventions worth simulating. List any additional information you would need.

EVIDENCE PACKAGE:
{evidence}
"""

INVESTIGATE_TASK = """\
Now investigate with the tools. The 60-minute temperature and vibration trends are already in \
the evidence package; fetch other channels only if they would change your decision. Run \
compare_futures on your candidate interventions (the no-action baseline is always included), \
then call submit_recommendation with exactly one action, the failure mode you believe is \
developing, the evidence ids that support it (including the sim:* id of the chosen branch), \
and a concise rationale grounded in the tool results. Tool-call budget: {budget} calls.
"""

NUDGE_SUBMIT = (
    "You have not submitted a recommendation. Call submit_recommendation now with the best "
    "simulated action, or controlled_shutdown if no simulated action is safe."
)

REVISION_TASK = """\
The verifier REJECTED your proposal '{label}'. Failed checks:
{reasons}
Revise: simulate an alternative (or a smaller/different parameter) with compare_futures if \
needed, then call submit_recommendation again. Revisions left: {left}.
"""

_NULLABLE_NUMBER = {"type": ["number", "null"]}

ACTION_SCHEMA_STRICT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string", "enum": ACTION_TYPES},
        "fraction": {**_NULLABLE_NUMBER, "description": "reduce_load / reduce_speed fraction"},
        "boost": {**_NULLABLE_NUMBER, "description": "increase_cooling extra airflow fraction"},
        "delay_minutes": {**_NULLABLE_NUMBER, "description": "schedule_inspection delay"},
    },
    "required": ["type", "fraction", "boost", "delay_minutes"],
}

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ACTION_TYPES},
        "fraction": {"type": "number", "description": "For reduce_load / reduce_speed"},
        "boost": {"type": "number", "description": "For increase_cooling"},
        "delay_minutes": {"type": "number", "description": "For schedule_inspection"},
    },
    "required": ["type"],
}

HYPOTHESIS_FORMAT = {
    "type": "json_schema",
    "name": "failure_hypotheses",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "failure_mode": {
                            "type": "string",
                            "enum": ["thermal", "bearing", "overload", "none"],
                        },
                        "statement": {"type": "string"},
                        "likelihood": {"type": "string", "enum": ["low", "medium", "high"]},
                        "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "would_be_refuted_by": {"type": "string"},
                    },
                    "required": [
                        "failure_mode",
                        "statement",
                        "likelihood",
                        "supporting_evidence_ids",
                        "would_be_refuted_by",
                    ],
                },
            },
            "candidate_interventions": {"type": "array", "items": ACTION_SCHEMA_STRICT},
            "information_needed": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "hypotheses", "candidate_interventions", "information_needed"],
    },
}

CHANNEL_ENUM = [
    "temperature_c",
    "ambient_c",
    "vibration_mm_s",
    "speed_rpm",
    "load_pct",
    "current_a",
    "voltage_v",
]

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "name": "get_machine_state",
        "description": "Latest observed sensor values, drive commands, and run status. No hidden simulator state.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_sensor_history",
        "description": "Downsampled history and trend statistics for one sensor channel.",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": CHANNEL_ENUM},
                "minutes": {"type": "number", "description": "Look-back window, 5-120 minutes"},
            },
            "required": ["channel", "minutes"],
        },
    },
    {
        "type": "function",
        "name": "analyze_anomalies",
        "description": "Isolation-forest anomaly score, CUSUM change points, and the most deviant features vs healthy operation.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "predict_failure_risk",
        "description": "Calibrated failure probabilities for 15/30/60 min horizons and fault-class probabilities.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "inspect_visual_evidence",
        "description": "Request visual inspection evidence for a component (camera/thermal imagery).",
        "parameters": {
            "type": "object",
            "properties": {
                "component": {
                    "type": "string",
                    "enum": ["cooling_fins", "bearing_housing", "conveyor", "motor"],
                }
            },
            "required": ["component"],
        },
    },
    {
        "type": "function",
        "name": "compare_futures",
        "description": (
            "Simulate up to 5 interventions from the current estimated machine state with an 8-member "
            "ensemble (matched disturbances); the no-action baseline is always included. Returns failure "
            "incidence, peak temperature/vibration, downtime, cost, and the sim:* evidence id per branch."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "actions": {"type": "array", "items": ACTION_SCHEMA, "description": "1-5 actions"},
                "horizon_min": {
                    "type": "number",
                    "description": "Simulation horizon, 60-240 minutes (default 180)",
                },
            },
            "required": ["actions"],
        },
    },
    {
        "type": "function",
        "name": "verify_intervention",
        "description": "Run the deterministic safety verifier on an action that has already been simulated. Does not apply it.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": ACTION_SCHEMA,
                "claimed_failure_mode": {
                    "type": "string",
                    "enum": ["thermal", "bearing", "overload", "none", "unknown"],
                },
            },
            "required": ["action"],
        },
    },
    {
        "type": "function",
        "name": "submit_recommendation",
        "description": "Submit exactly one recommended action for independent verification and human approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": ACTION_SCHEMA,
                "claimed_failure_mode": {
                    "type": "string",
                    "enum": ["thermal", "bearing", "overload", "none"],
                },
                "cited_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "rationale": {
                    "type": "string",
                    "description": "2-5 sentences grounded in tool outputs",
                },
            },
            "required": ["action", "claimed_failure_mode", "cited_evidence_ids", "rationale"],
        },
    },
]
