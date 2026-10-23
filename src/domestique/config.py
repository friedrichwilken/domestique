"""Local configuration.

Everything athlete-specific lives outside the repository, in
``$DOMESTIQUE_HOME`` (default ``~/.config/domestique``):

    config.yaml      ids, timezone, bedtime, baselines, database URL
    intent/*.yaml    goals, constraints, overrides, rails

Secrets come from the environment only (``ICU_API_KEY``,
``DOMESTIQUE_HUMAN_TOKEN``). ``examples/`` in the repo shows the shape.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_HOME = Path("~/.config/domestique")


@dataclass(frozen=True)
class Config:
    home: Path
    athlete_id: str
    timezone: str
    bedtime: str
    hr_max: int | None
    baselines: dict[str, float] = field(default_factory=dict)
    intent_dir: Path = field(default_factory=lambda: DEFAULT_HOME / "intent")
    database_url: str | None = None


def home_dir(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("DOMESTIQUE_HOME", str(DEFAULT_HOME))).expanduser()


def load(env: dict[str, str] | None = None) -> Config:
    """Load ``config.yaml`` from the config home. Raises if it is missing."""
    home = home_dir(env)
    path = home / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy examples/config.yaml there and edit it; "
            "nothing athlete-specific is read from the repository."
        )
    raw = yaml.safe_load(path.read_text()) or {}
    for key in ("athlete_id", "timezone", "bedtime"):
        if key not in raw:
            raise ValueError(f"{path}: missing required field '{key}'")
    intent_dir = Path(raw.get("intent_dir", str(home / "intent"))).expanduser()
    return Config(
        home=home,
        athlete_id=str(raw["athlete_id"]),
        timezone=str(raw["timezone"]),
        bedtime=str(raw["bedtime"]),
        hr_max=int(raw["hr_max"]) if raw.get("hr_max") else None,
        baselines={k: float(v) for k, v in (raw.get("baselines") or {}).items()},
        intent_dir=intent_dir,
        database_url=raw.get("database_url"),
    )
