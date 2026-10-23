"""Timing of a session relative to the athlete's configured bedtime."""

from __future__ import annotations

from datetime import datetime, time, timedelta


def hours_before_bed(session_end_local: datetime, bedtime: time) -> float:
    """Hours from the session end until the next occurrence of ``bedtime``.

    Both are athlete-local wall-clock; ``session_end_local`` should be naive
    or carry the athlete's tzinfo. A session ending exactly at bedtime is 0.
    """
    bed = session_end_local.replace(
        hour=bedtime.hour, minute=bedtime.minute, second=bedtime.second, microsecond=0
    )
    if bed < session_end_local:
        bed += timedelta(days=1)
    return (bed - session_end_local).total_seconds() / 3600
