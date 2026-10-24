"""One report input from two sources: the database and a replay result.

``from_db`` and ``from_replay`` both build a ``ReportData``; the charts and
pages never know which one they were given. Per claim it holds the claim's
calibration state and every scored prediction made for it, official and
shadow, oldest first. Unscored predictions are left out: there is nothing to
draw against their range yet.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date

from domestique import db
from domestique.claims.rules import Status
from domestique.claims.store import Claim, HistoryRow, PgStore
from domestique.replay.harness import RunResult, Scored


@dataclass(frozen=True)
class PredictionRow:
    """One scored prediction: its pre-registered range and what was observed."""

    day: date  # date of the planned session the prediction was made for
    metric: str
    low: float
    high: float
    expected: float
    actual: float
    official: bool

    @property
    def hit(self) -> bool:
        return self.low <= self.actual <= self.high

    @property
    def miss_by(self) -> float:
        """Signed distance from the range to the observed value; zero on a hit."""
        if self.actual > self.high:
            return self.actual - self.high
        if self.actual < self.low:
            return self.actual - self.low
        return 0.0


@dataclass(frozen=True)
class ClaimReport:
    id: str
    text: str
    source_layer: str
    horizon: str
    confidence: float
    status: str
    scored: int
    hits: int
    calib_scored: int
    calib_hits: int
    calib_abs_error: float
    calib_half_range: float
    uninformative: bool
    overconfident: bool
    predictions: tuple[PredictionRow, ...] = ()  # scored, oldest first
    history: tuple[HistoryRow, ...] = ()  # every state change, oldest first

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.scored if self.scored else None

    @property
    def error_share(self) -> float | None:
        """Mean absolute error as a share of the mean half-range, over the calibration window."""
        if self.calib_half_range > 0:
            return self.calib_abs_error / self.calib_half_range
        return None


@dataclass(frozen=True)
class ReportData:
    athlete_id: str
    claims: tuple[ClaimReport, ...]


def claim_report(
    claim: Claim, predictions: Iterable[PredictionRow], history: Iterable[HistoryRow] = ()
) -> ClaimReport:
    return ClaimReport(
        id=claim.id,
        text=claim.text,
        source_layer=claim.source_layer.value,
        horizon=claim.horizon.value,
        confidence=claim.confidence,
        status=claim.status.value,
        scored=claim.scored,
        hits=claim.hits,
        calib_scored=claim.calib_scored,
        calib_hits=claim.calib_hits,
        calib_abs_error=claim.calib_abs_error,
        calib_half_range=claim.calib_half_range,
        uninformative=claim.uninformative,
        overconfident=claim.overconfident,
        predictions=tuple(sorted(predictions, key=lambda p: (p.day, p.metric))),
        history=tuple(history),
    )


def build(
    athlete_id: str,
    claims: Sequence[Claim],
    scored: Iterable[tuple[str, PredictionRow]],
    history: Iterable[HistoryRow] = (),
) -> ReportData:
    """``scored`` pairs a claim id with one of its scored predictions; history rows in order."""
    by_claim: defaultdict[str, list[PredictionRow]] = defaultdict(list)
    for claim_id, row in scored:
        by_claim[claim_id].append(row)
    changes: defaultdict[str, list[HistoryRow]] = defaultdict(list)
    for h in history:
        changes[h.claim_id].append(h)
    return ReportData(
        athlete_id, tuple(claim_report(c, by_claim[c.id], changes[c.id]) for c in claims)
    )


_SCORED_SQL = (
    "SELECT p.claim_id, s.date, p.metric, p.low, p.high, p.expected, o.actual, p.official "
    "FROM predictions p "
    "JOIN outcomes o ON o.prediction_id = p.id "
    "JOIN planned_sessions s ON s.id = p.planned_session_id "
    "JOIN claims c ON c.id = p.claim_id "
    "WHERE c.athlete_id = %s ORDER BY s.date, p.metric, p.id"
)


_HISTORY_SQL = (
    "SELECT h.claim_id, h.ts, h.confidence, h.status, h.reason, h.by "
    "FROM claim_history h JOIN claims c ON c.id = h.claim_id "
    "WHERE c.athlete_id = %s ORDER BY h.ts"
)


def history_from_db(conn: db.Conn, athlete_id: str) -> list[HistoryRow]:
    rows = conn.execute(_HISTORY_SQL, (athlete_id,)).fetchall()
    return [
        HistoryRow(str(r[0]), r[1], float(r[2]), Status(r[3]), str(r[4]), str(r[5])) for r in rows
    ]


def from_db(conn: db.Conn, athlete_id: str) -> ReportData:
    claims = PgStore(conn).query_claims(athlete_id=athlete_id)
    rows = conn.execute(_SCORED_SQL, (athlete_id,)).fetchall()
    scored = (
        (
            str(r[0]),
            PredictionRow(
                day=r[1],
                metric=str(r[2]),
                low=float(r[3]),
                high=float(r[4]),
                expected=float(r[5]),
                actual=float(r[6]),
                official=bool(r[7]),
            ),
        )
        for r in rows
    )
    return build(athlete_id, claims, scored, history_from_db(conn, athlete_id))


def _replay_row(s: Scored) -> tuple[str, PredictionRow]:
    p = s.prediction
    return p.claim_id, PredictionRow(
        day=s.session.date,
        metric=p.metric.value,
        low=p.low,
        high=p.high,
        expected=p.expected,
        actual=s.outcome.actual,
        official=p.official,
    )


def from_replay(result: RunResult) -> ReportData:
    rows = (_replay_row(s) for s in [*result.scored, *result.shadow_scored])
    return build(result.athlete_id, result.claims, rows)


def history_json(rows: Iterable[HistoryRow]) -> list[dict[str, object]]:
    """History rows as JSON-ready values, oldest first."""
    return [
        {
            "claim_id": h.claim_id,
            "ts": h.ts.isoformat(),
            "confidence": h.confidence,
            "status": h.status.value,
            "reason": h.reason,
            "by": h.by,
        }
        for h in rows
    ]


def as_json(data: ReportData) -> dict[str, object]:
    """The report as JSON-ready values, derived numbers included. Every prediction, no limit."""
    claims = []
    for c in data.claims:
        row = asdict(c)
        row["hit_rate"] = c.hit_rate
        row["error_share"] = c.error_share
        row["predictions"] = [
            {**asdict(p), "day": p.day.isoformat(), "hit": p.hit} for p in c.predictions
        ]
        row["history"] = history_json(c.history)
        claims.append(row)
    return {"athlete_id": data.athlete_id, "claims": claims}
