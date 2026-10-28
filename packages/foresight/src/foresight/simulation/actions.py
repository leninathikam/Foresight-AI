"""Intervention actions that can be applied to the simulated motor."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ActionType(StrEnum):
    CONTINUE = "continue_operation"
    REDUCE_LOAD = "reduce_load"
    REDUCE_SPEED = "reduce_speed"
    INCREASE_COOLING = "increase_cooling"
    SCHEDULE_INSPECTION = "schedule_inspection"
    CONTROLLED_SHUTDOWN = "controlled_shutdown"


class ContinueOperation(BaseModel):
    type: Literal[ActionType.CONTINUE] = ActionType.CONTINUE


class ReduceLoad(BaseModel):
    """Reduce the process feed, lowering conveyor torque by ``fraction`` of the current value."""

    type: Literal[ActionType.REDUCE_LOAD] = ActionType.REDUCE_LOAD
    fraction: float = Field(description="Fractional reduction of applied load, e.g. 0.2 = 20 %")


class ReduceSpeed(BaseModel):
    """Lower the drive speed setpoint by ``fraction``. Torque is unchanged (constant-torque load)."""

    type: Literal[ActionType.REDUCE_SPEED] = ActionType.REDUCE_SPEED
    fraction: float = Field(description="Fractional reduction of speed setpoint, e.g. 0.3 = 30 %")


class IncreaseCooling(BaseModel):
    """Switch on the auxiliary blower, adding ``boost`` x rated airflow."""

    type: Literal[ActionType.INCREASE_COOLING] = ActionType.INCREASE_COOLING
    boost: float = Field(description="Additional airflow as a fraction of rated fan airflow")


class ScheduleInspection(BaseModel):
    """Stop for inspection after ``delay_minutes``; cleans cooling paths, replaces worn bearings."""

    type: Literal[ActionType.SCHEDULE_INSPECTION] = ActionType.SCHEDULE_INSPECTION
    delay_minutes: float = Field(description="Minutes of continued operation before inspection")


class ControlledShutdown(BaseModel):
    type: Literal[ActionType.CONTROLLED_SHUTDOWN] = ActionType.CONTROLLED_SHUTDOWN


Action = Annotated[
    ContinueOperation
    | ReduceLoad
    | ReduceSpeed
    | IncreaseCooling
    | ScheduleInspection
    | ControlledShutdown,
    Field(discriminator="type"),
]


def describe_action(action: Action) -> str:
    match action:
        case ReduceLoad(fraction=f):
            return f"Reduce load by {f:.0%}"
        case ReduceSpeed(fraction=f):
            return f"Reduce speed by {f:.0%}"
        case IncreaseCooling(boost=b):
            return f"Auxiliary cooling +{b:.0%} airflow"
        case ScheduleInspection(delay_minutes=d):
            return f"Inspection in {d:.0f} min"
        case ControlledShutdown():
            return "Controlled shutdown"
        case _:
            return "Continue operation"
