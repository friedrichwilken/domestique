"""Chat modes: one per file in ``skills/``, the file verbatim as the system prompt.

The prompt is a short prefix carrying the date, the timezone and the athlete id
from the configuration, then the skill file exactly as it is on disk. No prompt
text lives in Python: editing a mode means editing its Markdown file.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MODES: tuple[str, ...] = (
    "post-ride-debrief",
    "morning-readiness",
    "weekly-review",
    "plan-vs-execution",
)
# The repository's skills/ next to src/; DOMESTIQUE_SKILLS_DIR overrides it (the image).
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"


@dataclass(frozen=True)
class ModeContext:
    """What the prefix carries, all of it from the athlete's configuration."""

    today: date
    timezone: str
    athlete_id: str


@dataclass(frozen=True)
class Mode:
    name: str
    system: str


def skills_dir(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    configured = source.get("DOMESTIQUE_SKILLS_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_SKILLS_DIR


def context_for(athlete_id: str, timezone: str, now: datetime | None = None) -> ModeContext:
    """Today in the athlete's timezone."""
    moment = now or datetime.now(ZoneInfo(timezone))
    return ModeContext(moment.astimezone(ZoneInfo(timezone)).date(), timezone, athlete_id)


def prefix(ctx: ModeContext) -> str:
    return (
        f"Date: {ctx.today.isoformat()}\nTimezone: {ctx.timezone}\nAthlete id: {ctx.athlete_id}\n\n"
    )


def load_mode(name: str, ctx: ModeContext, directory: Path | None = None) -> Mode:
    """The mode's system prompt: the prefix, then ``skills/<name>.md`` byte for byte."""
    if name not in MODES:
        raise ValueError(f"unknown mode {name!r}; one of {', '.join(MODES)}")
    path = (directory or skills_dir()) / f"{name}.md"
    return Mode(name, prefix(ctx) + path.read_text(encoding="utf-8"))
