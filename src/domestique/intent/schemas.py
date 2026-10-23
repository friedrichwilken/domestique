"""Pydantic schemas for the intent files. Unknown fields are rejected so typos surface."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RailAction = Literal["stop_plan", "downgrade_day", "refuse_additional_load", "no_intensity"]


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Goal(_Entry):
    id: str
    text: str
    rank: int = Field(ge=1)
    set_on: date
    set_by: str


class Constraint(_Entry):
    id: str
    set_by: str
    text: str | None = None
    value: float | str | None = None
    reason: str | None = None
    set_on: date | None = None

    @model_validator(mode="after")
    def _says_something(self) -> Constraint:
        if self.text is None and self.value is None:
            raise ValueError("a constraint needs 'text' or 'value'")
        return self


class Override(_Entry):
    ts: date | datetime
    by: str
    text: str
    overruled: str
    prediction_at_time: dict[str, float | str | None] = Field(default_factory=dict)


class Rail(_Entry):
    """Documentation plus thresholds; the behaviour lives in ``domestique.rails``."""

    id: str
    trigger: str
    action: RailAction
    message: str | None = None
    threshold: float | None = None
