"""What the intervals.icu ingest CLIs share: the source label and where settings come from.

Kept apart from ``icu`` so that ``icu`` and ``icu_comments`` can import each
other's pieces without a cycle.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from domestique import config

SOURCE = "intervals.icu"


def cli_settings(env: Mapping[str, str] | None = None) -> tuple[str, str | None]:
    """Athlete id and database URL for the CLIs: config.yaml, overridden by the environment.

    ``ICU_ATHLETE_ID`` and ``DOMESTIQUE_DSN`` win over ``athlete_id`` and
    ``database_url`` in the config; the config is only required when the
    environment does not supply both.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    athlete_id = source.get("ICU_ATHLETE_ID", "").strip()
    dsn = source.get("DOMESTIQUE_DSN", "").strip()
    if athlete_id and dsn:
        return athlete_id, dsn
    cfg = config.load(source)
    return athlete_id or cfg.athlete_id, dsn or cfg.database_url
