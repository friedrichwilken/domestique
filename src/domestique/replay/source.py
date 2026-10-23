"""What a replay reads, and the cursor view that hides the future.

A ``SeasonSource`` is a season of data: the fixture files or the athlete's own
ingested history. The harness never hands a source to the predictor or the
scorer; it hands them a ``CursorView``, which refuses anything after the cursor:

- wellness dated D is the morning reading of D (the night from D-1 to D), so it
  is visible from the cursor D on;
- a ride on day D is visible only once the day is over (cursor D+1): a session
  is never predicted from its own ride;
- a planned session is visible from its own day on, and its pairing only once
  the paired ride is visible.

A refused request returns nothing (None, an empty list), never an error, so
an accidental peek degrades into a gap instead of a leak.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Protocol

from domestique.ingest.plan_store import PlannedSession, WorkInterval
from domestique.metrics.types import Sample


@dataclass(frozen=True)
class Ride:
    id: int
    sport: str | None
    start_local: datetime
    max_hr: float | None
    work_intervals: tuple[WorkInterval, ...] = ()


@dataclass(frozen=True)
class Night:
    """The morning reading of ``date``: HRV and the sleep of the night before."""

    date: date
    hrv: float | None
    sleep_h: float | None


class SeasonSource(Protocol):
    athlete_id: str
    hr_max: float | None
    first: date
    last: date

    def planned_on(self, day: date) -> list[PlannedSession]: ...

    def rides(self, oldest: date, newest: date) -> list[Ride]:
        """Rides starting on ``oldest..newest`` (local dates, inclusive), newest first."""
        ...

    def ride(self, activity_id: int) -> Ride | None: ...

    def samples(self, activity_id: int) -> list[Sample]: ...

    def nights(self, oldest: date, newest: date) -> list[Night]:
        """Wellness dated ``oldest..newest`` (inclusive), newest first."""
        ...


class CursorView:
    """A read-only window on a source that ends at ``cursor``."""

    def __init__(self, source: SeasonSource, cursor: date) -> None:
        self._source = source
        self.cursor = cursor
        self.athlete_id = source.athlete_id
        self.hr_max = source.hr_max

    def _ride_visible(self, ride: Ride) -> bool:
        return ride.start_local.date() < self.cursor

    def night(self, day: date) -> Night | None:
        """The morning reading of ``day``; None after the cursor."""
        if day > self.cursor:
            return None
        found = self._source.nights(day, day)
        return found[0] if found else None

    def nights(self, oldest: date, newest: date) -> list[Night]:
        return self._source.nights(oldest, min(newest, self.cursor))

    def rides(self, oldest: date, newest: date) -> list[Ride]:
        last_visible = self.cursor - timedelta(days=1)
        return self._source.rides(oldest, min(newest, last_visible))

    def ride(self, activity_id: int) -> Ride | None:
        found = self._source.ride(activity_id)
        return found if found is not None and self._ride_visible(found) else None

    def samples(self, activity_id: int) -> list[Sample]:
        if self.ride(activity_id) is None:
            return []
        return self._source.samples(activity_id)

    def planned_on(self, day: date) -> list[PlannedSession]:
        if day > self.cursor:
            return []
        return [self._hide_future_pairing(s) for s in self._source.planned_on(day)]

    def _hide_future_pairing(self, session: PlannedSession) -> PlannedSession:
        aid = session.paired_activity_id
        if aid is None or self.ride(aid) is not None:
            return session
        return replace(session, paired_activity_id=None)
