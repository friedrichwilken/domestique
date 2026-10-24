"""Evaluate every rail for one day: ``python -m domestique.rails --date YYYY-MM-DD``.

Reads config from ``$DOMESTIQUE_HOME``, the day's rows from the database and
the thresholds from ``rails.yaml``; prints one line per triggered rail.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from domestique import config, db
from domestique.intent import load_intent
from domestique.rails.load import load_day
from domestique.rails.registry import RailResult, evaluate, limits_from_intent

QUIET = "no rail triggered"


def format_results(results: Sequence[RailResult]) -> list[str]:
    """One ``rail  action  wording`` line per result, or the quiet line."""
    if not results:
        return [QUIET]
    return [f"{r.rail}\t{r.action}\t{r.wording}" for r in results]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Evaluate all safety rails for one day.")
    p.add_argument("--date", dest="day", required=True, type=date.fromisoformat)
    args = p.parse_args(argv)

    cfg = config.load()
    limits = limits_from_intent(load_intent(cfg.intent_dir).rails)
    with db.connect(cfg.database_url) as conn:
        day = load_day(conn, cfg.athlete_id, args.day, cfg.timezone)
    lines = format_results(evaluate(day, cfg.baselines, limits))
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
