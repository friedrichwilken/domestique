"""Plan versus execution for one day: ``python -m domestique.analysis --date YYYY-MM-DD``.

``just pve --date YYYY-MM-DD`` runs the same. HRmax and the overshoot margin
come from ``$DOMESTIQUE_HOME/config.yaml`` (``hr_max``, ``overshoot_margin_pp``).
Prints one line per planned session, then the questions for the athlete;
``--save`` also writes those questions to the ``questions`` table.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from domestique import config, db
from domestique.analysis.plan_vs_execution import (
    JoinRow,
    plan_vs_execution,
    questions_of,
    save_questions,
)
from domestique.ingest.plan_store import PgPlanStore, PlanStore


def run(cfg: config.Config, store: PlanStore, day: date) -> list[JoinRow]:
    """The join for ``day`` with HRmax and margin taken from the config."""
    hr_max = float(cfg.hr_max) if cfg.hr_max else None
    return plan_vs_execution(store, cfg.athlete_id, day, hr_max, cfg.overshoot_margin_pp)


def _num(value: float | None, unit: str = "") -> str:
    return "-" if value is None else f"{value:.0f}{unit}"


def _row_line(row: JoinRow) -> str:
    guidance = row.hr_guidance.text if row.hr_guidance else "-"
    planned = f"{row.planned.title or 'untitled'}: prescribed {guidance}"
    ex = row.executed
    if ex is None:
        return f"{planned} | {row.status}"
    intensity = "-" if ex.intensity_factor is None else f"{ex.intensity_factor:.2f}"
    return (
        f"{planned} | {row.status}: NP {_num(ex.np_w, ' W')}, avg HR {_num(ex.avg_hr)}, "
        f"peak HR {_num(ex.max_hr)}, IF {intensity}, work HR {_num(row.work_hr_pct, '% of max')}"
    )


def format_report(rows: Sequence[JoinRow]) -> list[str]:
    """One line per planned session, then one per question; a note when nothing is planned."""
    if not rows:
        return ["no planned session"]
    lines = [_row_line(r) for r in rows]
    lines += [f"question: {q.text}" for q in questions_of(rows)]
    return lines


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Plan versus execution for one day.")
    p.add_argument("--date", dest="day", required=True, type=date.fromisoformat)
    p.add_argument("--save", action="store_true", help="write the questions to the database")
    args = p.parse_args(argv)

    cfg = config.load()
    with db.connect(cfg.database_url) as conn:
        rows = run(cfg, PgPlanStore(conn), args.day)
        if args.save:
            save_questions(conn, questions_of(rows))
    sys.stdout.write("\n".join(format_report(rows)) + "\n")


if __name__ == "__main__":
    main()
