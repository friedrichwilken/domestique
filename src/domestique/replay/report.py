"""Replay output: error per metric and week as CSV, a markdown summary with the headline last.

Per replayed week (week 1 starts on the first replayed day) and metric:
``n``, mean signed error (``actual - expected``, in the metric's unit), mean
absolute error, mean absolute error as percent of expected, and hit rate.
Sleep hours on evening-intensity sessions get their own rows (segment
``evening_intensity``): that is where the fixture's planted effect lives.

The headline is the mean absolute error across metrics over the final four
weeks. The metrics have different units (watts, bpm, ms, hours), so each
metric's error is taken relative to its expected value first and the metrics
are then averaged with equal weight; a raw mean would only measure watts.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from statistics import fmean

from domestique.loop.model import Metric
from domestique.replay.harness import RunResult, Scored, evening_intensity

FINAL_WEEKS = 4
DAYS_PER_WEEK = 7
SEGMENT_ALL = "all"
SEGMENT_EVENING = "evening_intensity"
CSV_FIELDS = (
    "week",
    "week_start",
    "metric",
    "segment",
    "n",
    "mean_error",
    "mae",
    "mae_pct",
    "hit_rate",
)


def week_of(result: RunResult, s: Scored) -> int:
    return (s.session.date - result.first).days // DAYS_PER_WEEK + 1


def weeks(result: RunResult) -> int:
    return (result.last - result.first).days // DAYS_PER_WEEK + 1


def _pct(s: Scored) -> float:
    expected = abs(s.prediction.expected)
    return 100.0 * abs(s.outcome.error) / expected if expected else 0.0


@dataclass(frozen=True)
class Cell:
    n: int
    mean_error: float
    mae: float
    mae_pct: float
    hit_rate: float


def cell(rows: Sequence[Scored]) -> Cell | None:
    if not rows:
        return None
    return Cell(
        n=len(rows),
        mean_error=fmean(s.outcome.error for s in rows),
        mae=fmean(abs(s.outcome.error) for s in rows),
        mae_pct=fmean(_pct(s) for s in rows),
        hit_rate=sum(s.hit for s in rows) / len(rows),
    )


def _segments(metric: Metric) -> tuple[str, ...]:
    return (SEGMENT_ALL, SEGMENT_EVENING) if metric == Metric.SLEEP_HOURS else (SEGMENT_ALL,)


def select(
    result: RunResult, metric: Metric, segment: str, week_range: Iterable[int]
) -> list[Scored]:
    wanted = set(week_range)
    return [
        s
        for s in result.scored
        if s.prediction.metric == metric
        and week_of(result, s) in wanted
        and (segment == SEGMENT_ALL or evening_intensity(s.session))
    ]


def weekly_rows(result: RunResult) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for week in range(1, weeks(result) + 1):
        start = result.first + timedelta(days=(week - 1) * DAYS_PER_WEEK)
        for metric in Metric:
            for segment in _segments(metric):
                c = cell(select(result, metric, segment, [week]))
                if c is None:
                    continue
                out.append(
                    {
                        "week": str(week),
                        "week_start": start.isoformat(),
                        "metric": metric.value,
                        "segment": segment,
                        "n": str(c.n),
                        "mean_error": f"{c.mean_error:.3f}",
                        "mae": f"{c.mae:.3f}",
                        "mae_pct": f"{c.mae_pct:.2f}",
                        "hit_rate": f"{c.hit_rate:.3f}",
                    }
                )
    return out


def weekly_csv(result: RunResult) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(weekly_rows(result))
    return buf.getvalue()


def final_weeks(result: RunResult) -> range:
    total = weeks(result)
    return range(max(1, total - FINAL_WEEKS + 1), total + 1)


def headline_by_metric(result: RunResult) -> dict[Metric, float]:
    """Mean absolute error as percent of expected, per metric, over the final four weeks."""
    out: dict[Metric, float] = {}
    for metric in Metric:
        c = cell(select(result, metric, SEGMENT_ALL, final_weeks(result)))
        if c is not None:
            out[metric] = c.mae_pct
    return out


def headline(result: RunResult) -> float | None:
    per_metric = headline_by_metric(result)
    return fmean(per_metric.values()) if per_metric else None


def headline_line(result: RunResult) -> str:
    value = headline(result)
    shown = "n/a (nothing scored)" if value is None else f"{value:.2f}% of expected"
    return f"Headline: mean absolute error across metrics, final {FINAL_WEEKS} weeks: {shown}"


@dataclass(frozen=True)
class Planted:
    """Sleep error on evening-intensity sessions, first half of the season against the second."""

    first: Cell | None
    second: Cell | None


def planted_effect(result: RunResult) -> Planted:
    total = weeks(result)
    half = total // 2
    return Planted(
        first=cell(select(result, Metric.SLEEP_HOURS, SEGMENT_EVENING, range(1, half + 1))),
        second=cell(
            select(result, Metric.SLEEP_HOURS, SEGMENT_EVENING, range(half + 1, total + 1))
        ),
    )


def _fmt(c: Cell | None, unit: str = "") -> str:
    if c is None:
        return "no scored predictions"
    return (
        f"MAE {c.mae:.2f}{unit}, mean error {c.mean_error:+.2f}{unit}, "
        f"hit rate {c.hit_rate:.0%}, n={c.n}"
    )


def _table(rows: Sequence[dict[str, str]]) -> list[str]:
    lines = [
        "| week | metric | segment | n | mean error | MAE | MAE % | hit rate |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {r['week']} | {r['metric']} | {r['segment']} | {r['n']} | {r['mean_error']} "
        f"| {r['mae']} | {r['mae_pct']} | {r['hit_rate']} |"
        for r in rows
    )
    return lines


def _claims_section(result: RunResult) -> list[str]:
    lines = [
        "| claim | layer | horizon | status | confidence | scored | hits |",
        "|---|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {c.text} | {c.source_layer} | {c.horizon} | {c.status} | {c.confidence:g} "
        f"| {c.scored} | {c.hits} |"
        for c in result.claims
    )
    return lines


def _gap_section(result: RunResult) -> list[str]:
    if not result.gaps and not result.pending:
        return ["None."]
    lines = [
        f"- predicted nothing for {m}, {n}x: {reason}"
        for (m, reason), n in sorted(
            result.gaps.items(), key=lambda kv: (-kv[1], kv[0][0].value, kv[0][1])
        )
    ]
    lines.extend(
        f"- left unscored {m}, {n}x: {reason}"
        for (m, reason), n in sorted(
            result.pending.items(), key=lambda kv: (-kv[1], kv[0][0].value, kv[0][1])
        )
    )
    return lines


def summary_markdown(result: RunResult, source_label: str) -> str:
    """The one-page summary. Its last line is the headline."""
    planted = planted_effect(result)
    per_metric = headline_by_metric(result)
    loop = "on" if result.loop_on else "off (confidence updates disabled)"
    lines = [
        f"# Replay: {source_label}, {result.first.isoformat()} to {result.last.isoformat()}",
        "",
        f"Loop {loop}. Sessions planned: {result.sessions}, predictions: {result.predictions}, "
        f"scored: {len(result.scored)}, questions drafted: {len(result.questions)}.",
        "",
        "## Planted effect: sleep on evening-intensity sessions",
        "",
        f"- first half of the season: {_fmt(planted.first, ' h')}",
        f"- second half of the season: {_fmt(planted.second, ' h')}",
        "",
        "## Error per metric and week",
        "",
        *_table(weekly_rows(result)),
        "",
        "## Unpredicted and unscored",
        "",
        *_gap_section(result),
        "",
        "## Claims at the end of the replay",
        "",
        *_claims_section(result),
        "",
        f"## Final {FINAL_WEEKS} weeks, mean absolute error as % of expected",
        "",
        *(f"- {m}: {v:.2f}%" for m, v in per_metric.items()),
        "",
        headline_line(result),
    ]
    return "\n".join(lines) + "\n"
