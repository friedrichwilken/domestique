"""Command line for the replay; ``evals/replay.py`` calls ``main``.

    python evals/replay.py                       # fixture season, loop on
    python evals/replay.py --loop off            # confidence updates disabled
    python evals/replay.py --source db --from 2026-03-01 --to 2026-09-01

``--source db`` reads the athlete's own ingested history from the database in
``$DOMESTIQUE_HOME/config.yaml`` over a read-only connection (default range:
the last 182 days up to yesterday). Output goes to ``--out``: ``weekly.csv``,
``summary.md`` and, with the loop on, ``review.yaml`` (the bootstrap review
list; nothing is written to the claims store). The last line printed is the
headline.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from domestique import config
from domestique.claims.seed import read_seed
from domestique.replay.bootstrap import write_review
from domestique.replay.fixture import FixtureSeason
from domestique.replay.harness import RunResult, run_replay
from domestique.replay.pg import PgSeason, open_readonly
from domestique.replay.report import headline_line, planted_effect, summary_markdown, weekly_csv

DEFAULT_DAYS = 182


@dataclass(frozen=True)
class Written:
    result: RunResult
    files: tuple[Path, ...]


def parser(repo: Path) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Replay a season day by day and score predictions.")
    p.add_argument("--source", choices=("fixture", "db"), default="fixture")
    p.add_argument("--season", type=Path, default=repo / "evals/fixtures/season_a")
    p.add_argument("--priors", type=Path, default=repo / "evals/priors.yaml")
    p.add_argument("--loop", choices=("on", "off"), default="on")
    p.add_argument("--out", type=Path, default=repo / "evals/out")
    p.add_argument("--from", dest="first", type=date.fromisoformat)
    p.add_argument("--to", dest="last", type=date.fromisoformat)
    return p


def write_outputs(result: RunResult, label: str, out: Path) -> Written:
    out.mkdir(parents=True, exist_ok=True)
    files = [out / "weekly.csv", out / "summary.md"]
    files[0].write_text(weekly_csv(result))
    files[1].write_text(summary_markdown(result, label))
    if result.loop_on:
        files.append(write_review(result, label, out / "review.yaml"))
    return Written(result, tuple(files))


def replay_fixture(args: argparse.Namespace) -> Written:
    source = FixtureSeason(args.season)
    result = run_replay(source, read_seed(args.priors), args.loop == "on")
    return write_outputs(result, f"fixture {args.season.name}", args.out)


def replay_db(args: argparse.Namespace) -> Written:
    cfg = config.load()
    last = args.last or date.today() - timedelta(days=1)
    first = args.first or last - timedelta(days=DEFAULT_DAYS - 1)
    with open_readonly(cfg.database_url) as conn:
        source = PgSeason(conn, cfg.athlete_id, cfg.hr_max, first, last)
        result = run_replay(source, read_seed(args.priors), args.loop == "on")
        conn.rollback()
    return write_outputs(result, "ingested history", args.out)


def main(argv: list[str] | None = None, repo: Path | None = None) -> Written:
    args = parser(repo or Path.cwd()).parse_args(argv)
    written = replay_fixture(args) if args.source == "fixture" else replay_db(args)
    planted = planted_effect(written.result)
    lines = [f"wrote {path}" for path in written.files]
    for name, cell in (("first", planted.first), ("second", planted.second)):
        shown = "n/a" if cell is None else f"{cell.mae:.2f} h (n={cell.n})"
        lines.append(f"sleep MAE on evening-intensity sessions, {name} half: {shown}")
    lines.append(headline_line(written.result))
    sys.stdout.write("\n".join(lines) + "\n")
    return written
