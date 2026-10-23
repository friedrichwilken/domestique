"""The onboarding bootstrap: turn a replay with the loop on into a review list of candidate claims.

DESIGN.md, "Onboarding: the replay is the bootstrap", steps 3 and 4. Nothing
here writes to a claims store. The list is a file for the athlete to review;
an entry they accept is proposed through the claims MCP (``propose_claim``,
``add_binding``) and becomes active only through the human-gated
``confirm_or_retire``.

Two kinds of entries, each with horizon, hit rate, confidence and evidence:

- **tested prior**: every seeded prior that was scored at least once
  (official or shadow), in the state the loop left it: ``promote`` (it was
  promoted to ``observed`` on this athlete), ``retire`` (it missed until
  retired) or ``keep`` (still a prior). Hit rate is the replay's; its notes
  name the uninformative and overconfident flags.
- **pattern**: an ``observed`` candidate proposed from what the scorer saw. For
  each metric and session bucket (hard or easy by planned IF, evening or not by
  local start), when at least ``PATTERN_MIN_N`` predictions missed consistently
  on one side (``PATTERN_SIGN_SHARE``) by more than their typical half-range,
  the entry proposes a binding from the replay's own actuals against the base.
  Its hit rate is in-sample (how often that binding would have hit on the same
  sessions) and says so.

Rule (DESIGN.md, feedback horizons): a backfill never produces a ``season``
claim outside the ``prior`` layer. ``enforce_season_rule`` holds the line even
if a seeded season prior somehow reached ``observed``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from statistics import fmean, median, pstdev

import yaml

from domestique.claims.rules import Horizon, SourceLayer, Status
from domestique.claims.store import Claim, EvidenceInput
from domestique.loop.model import Binding, Metric, binding_params, conditions_json, parse_conditions
from domestique.loop.predict import applies
from domestique.replay.harness import HARD_IF, RunResult, Scored

PATTERN_MIN_N = 6
PATTERN_SIGN_SHARE = 0.75
PATTERN_RANGE_SD = 1.5  # proposed half-range, in standard deviations of the deltas
PROPOSED_CONFIDENCE = 0.3  # what propose_claim gives a new claim by default
MAX_EVIDENCE = 12
_EASY_IF = round(HARD_IF - 0.01, 2)
_EVENING = {"start_hour_from": 17, "start_hour_to": 23}
_NOT_EVENING = {"start_hour_from": 23, "start_hour_to": 17}

_LABEL = {
    Metric.WATTS_AT_HR: (
        "watts at the target heart rate",
        "%",
        "the mean of recent rides in the band",
    ),
    Metric.PEAK_HR: ("peak heart rate", " bpm", "the top of the prescribed heart-rate band"),
    Metric.HRV_NEXT_MORNING: ("next-morning HRV", " ms", "the recent median"),
    Metric.SLEEP_HOURS: ("sleep", " h", "the recent median"),
}


@dataclass(frozen=True)
class Bucket:
    name: str
    conditions: dict[str, object]

    def matches(self, s: Scored) -> bool:
        return applies(parse_conditions(self.conditions), s.session)


BUCKETS = (
    Bucket("hard sessions started in the evening", {"min_if": HARD_IF, **_EVENING}),
    Bucket("hard sessions started outside the evening", {"min_if": HARD_IF, **_NOT_EVENING}),
    Bucket("easy sessions started in the evening", {"max_if": _EASY_IF, **_EVENING}),
    Bucket("easy sessions started outside the evening", {"max_if": _EASY_IF, **_NOT_EVENING}),
)


@dataclass(frozen=True)
class ReviewEntry:
    origin: str  # "tested prior" or "pattern"
    proposal: str  # promote, keep, retire (tested priors) or new (patterns)
    text: str
    source_layer: str
    horizon: str
    confidence: float
    scored: int
    hits: int
    hit_rate: float
    hit_rate_basis: str  # "replay" or "in-sample"
    bindings: tuple[dict[str, object], ...]
    evidence: tuple[EvidenceInput, ...]
    notes: tuple[str, ...] = ()
    status: str = field(default=Status.CANDIDATE.value)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "origin": self.origin,
            "proposal": self.proposal,
            "text": self.text,
            "source_layer": self.source_layer,
            "horizon": self.horizon,
            "confidence": self.confidence,
            "scored": self.scored,
            "hits": self.hits,
            "hit_rate": round(self.hit_rate, 3),
            "hit_rate_basis": self.hit_rate_basis,
            "bindings": [dict(b) for b in self.bindings],
            "evidence": [dict(e) for e in self.evidence],
            "notes": list(self.notes),
        }


def _binding_dict(b: Binding) -> dict[str, object]:
    params = {k: v for k, v in binding_params(b).items() if v and k != "rides"}
    if b.metric == Metric.WATTS_AT_HR:
        params["rides"] = b.rides
    return {"metric": b.metric.value, "params": params, "conditions": conditions_json(b.when)}


def _evidence(rows: Sequence[Scored]) -> tuple[EvidenceInput, ...]:
    out: list[EvidenceInput] = []
    for s in rows[-MAX_EVIDENCE:]:
        p, o = s.prediction, s.outcome
        word = "hit" if s.hit else "miss"
        note = (
            f"{p.metric} {word}: actual {o.actual:g} against {p.expected:g} [{p.low:g}, {p.high:g}]"
        )
        out.append({"kind": s.evidence["kind"], "ref": s.evidence["ref"], "note": note})
    return tuple(out)


def _proposal(c: Claim) -> str:
    if c.status == Status.RETIRED:
        return "retire"
    if c.source_layer == SourceLayer.OBSERVED:
        return "promote"
    return "keep"


def _prior_entry(c: Claim, bindings: Sequence[Binding], rows: Sequence[Scored]) -> ReviewEntry:
    notes = []
    if c.uninformative:
        notes.append(
            "uninformative flag: its errors stay well inside its range; "
            "narrow the range so a hit means something"
        )
    if c.overconfident:
        notes.append("overconfident flag: it hits under 60% of the time; widen the range")
    if len({b.metric for b in bindings}) > 1:
        notes.append(
            "bound to more than one metric: calibration flags are per claim, "
            "so they mix the metrics; split it into one claim per metric"
        )
    references: tuple[EvidenceInput, ...] = tuple(
        {"kind": e.kind, "ref": e.ref, "note": e.note} for e in c.evidence
    )
    return ReviewEntry(
        origin="tested prior",
        proposal=_proposal(c),
        text=c.text,
        source_layer=c.source_layer.value,
        horizon=c.horizon.value,
        confidence=c.confidence,
        scored=c.scored,
        hits=c.hits,
        hit_rate=c.hits / c.scored if c.scored else 0.0,
        hit_rate_basis="replay",
        bindings=tuple(_binding_dict(b) for b in bindings),
        evidence=references + _evidence(rows),
        notes=tuple(notes),
    )


def tested_priors(result: RunResult) -> list[ReviewEntry]:
    out = []
    for c in result.claims:
        if c.id not in result.seeded or c.scored == 0:
            continue
        rows = sorted(
            (s for s in (*result.scored, *result.shadow_scored) if c.id in s.prediction.claim_ids),
            key=lambda s: s.session.date,
        )
        out.append(_prior_entry(c, result.seeded[c.id], rows))
    return out


def _base(s: Scored) -> float | None:
    value = s.prediction.basis.get("base")
    return float(value) if isinstance(value, int | float) else None


def _deltas(metric: Metric, rows: Sequence[Scored]) -> list[float]:
    """Actual against the base: percent for watts at HR, the metric's unit otherwise."""
    out = []
    for s in rows:
        base = _base(s)
        if base is None or (metric == Metric.WATTS_AT_HR and not base):
            continue
        actual = s.outcome.actual
        out.append(100.0 * (actual / base - 1) if metric == Metric.WATTS_AT_HR else actual - base)
    return out


def _consistent_miss(rows: Sequence[Scored]) -> bool:
    errors = [s.outcome.error for s in rows]
    mean = fmean(errors)
    same_side = sum(1 for e in errors if (e > 0) == (mean > 0)) / len(errors)
    half = median((s.prediction.high - s.prediction.low) / 2 for s in rows)
    return same_side >= PATTERN_SIGN_SHARE and abs(mean) > half


def _pattern_entry(metric: Metric, bucket: Bucket, rows: Sequence[Scored]) -> ReviewEntry | None:
    deltas = _deltas(metric, rows)
    if len(deltas) < PATTERN_MIN_N:
        return None
    shift = round(fmean(deltas), 2)
    spread = round(max(PATTERN_RANGE_SD * pstdev(deltas), 0.01), 2)
    in_range = sum(1 for d in deltas if abs(d - shift) <= spread)
    label, unit, base = _LABEL[metric]
    params: dict[str, object] = (
        {"change_pct": shift, "range_pct": spread}
        if metric == Metric.WATTS_AT_HR
        else {"offset": shift, "range_abs": spread}
    )
    return ReviewEntry(
        origin="pattern",
        proposal="new",
        text=(
            f"On {bucket.name}, {label} runs {shift:+g}{unit} against {base} "
            f"({len(deltas)} sessions in the replay)."
        ),
        source_layer=SourceLayer.OBSERVED.value,
        horizon=Horizon.DAY.value,
        confidence=PROPOSED_CONFIDENCE,
        scored=len(deltas),
        hits=in_range,
        hit_rate=in_range / len(deltas),
        hit_rate_basis="in-sample",
        bindings=({"metric": metric.value, "params": params, "conditions": bucket.conditions},),
        evidence=_evidence(rows),
        notes=("proposed from consistent misses; the hit rate is on the sessions it came from",),
    )


def patterns(result: RunResult) -> list[ReviewEntry]:
    out = []
    for metric in Metric:
        for bucket in BUCKETS:
            rows = [s for s in result.scored if s.prediction.metric == metric and bucket.matches(s)]
            if len(rows) < PATTERN_MIN_N or not _consistent_miss(rows):
                continue
            entry = _pattern_entry(metric, bucket, rows)
            if entry is not None:
                out.append(entry)
    return out


def _season_stays_prior(e: ReviewEntry) -> ReviewEntry:
    if e.horizon != Horizon.SEASON or e.source_layer == SourceLayer.PRIOR:
        return e
    return replace(
        e,
        source_layer=SourceLayer.PRIOR.value,
        proposal="keep",
        notes=(*e.notes, "season-horizon claims stay prior: a backfill cannot learn them"),
    )


def enforce_season_rule(entries: Sequence[ReviewEntry]) -> list[ReviewEntry]:
    """No ``season`` claim outside the ``prior`` layer, whatever produced it."""
    return [_season_stays_prior(e) for e in entries]


def review_list(result: RunResult) -> list[ReviewEntry]:
    return enforce_season_rule([*tested_priors(result), *patterns(result)])


def untested(result: RunResult) -> list[str]:
    return [c.text for c in result.claims if c.id in result.seeded and c.scored == 0]


def review_document(result: RunResult, source_label: str) -> dict[str, object]:
    entries = review_list(result)
    return {
        "athlete_id": result.athlete_id,
        "source": source_label,
        "range": {"from": result.first.isoformat(), "to": result.last.isoformat()},
        "note": (
            "Candidates only. Nothing here is in the claims store. Accepting an entry means "
            "proposing it through the claims MCP (propose_claim, add_binding); a human then "
            "confirms it with confirm_or_retire. Reject anything you recognise as coincidence, "
            "even when the numbers hit."
        ),
        "candidates": [e.as_dict() for e in entries],
        "untested_priors": untested(result),
    }


def write_review(result: RunResult, source_label: str, path: Path) -> Path:
    doc = review_document(result, source_label)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    return path
