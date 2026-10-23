"""Claims repository: one interface, a psycopg implementation and an in-memory one.

Functions: query_claims, propose_claim, attach_evidence, confirm_or_retire.
Every state change appends a claim_history row (never updated or deleted).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, NotRequired, Protocol, TypedDict

import psycopg

from domestique.claims.rules import HORIZON_CAP, Horizon, SourceLayer, Status

EVIDENCE_KINDS = ("activity", "interval", "wellness", "statement", "reference", "query")


@dataclass(frozen=True)
class Evidence:
    kind: str
    ref: str
    note: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class Claim:
    id: str
    athlete_id: str
    text: str
    source_layer: SourceLayer
    horizon: Horizon
    confidence: float
    status: Status
    created_by: str
    created_at: datetime
    last_tested_at: datetime | None = None
    hit_streak: int = 0
    scored: int = 0
    hits: int = 0
    always_hit: bool = False
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class HistoryRow:
    claim_id: str
    ts: datetime
    confidence: float
    status: Status
    reason: str
    by: str


class EvidenceInput(TypedDict):
    """Evidence as supplied by callers: ``{kind, ref, note?}``."""

    kind: str
    ref: str
    note: NotRequired[str | None]


class ClaimNotFoundError(KeyError):
    pass


def _check_evidence(kind: str) -> None:
    if kind not in EVIDENCE_KINDS:
        raise ValueError(f"evidence kind must be one of {EVIDENCE_KINDS}, got {kind!r}")


class ClaimsStore(Protocol):
    def query_claims(
        self,
        athlete_id: str | None = None,
        source_layer: str | None = None,
        status: str | None = None,
        text_contains: str | None = None,
    ) -> list[Claim]: ...

    def propose_claim(  # noqa: PLR0917  # callers pass all seven positionally (tests, mcp)
        self,
        athlete_id: str,
        text: str,
        source_layer: str,
        horizon: str,
        evidence: list[EvidenceInput],
        created_by: str,
        confidence: float = 0.3,
    ) -> Claim: ...

    def attach_evidence(
        self, claim_id: str, kind: str, ref: str, note: str | None = None
    ) -> Evidence: ...

    def confirm_or_retire(self, claim_id: str, status: str, reason: str, by: str) -> Claim: ...

    def record_adjustment(
        self, claim: Claim, reason: str, by: str, notes: Sequence[str] = ()
    ) -> Claim: ...

    def clear_always_hit(self, claim_id: str, reason: str, by: str) -> Claim: ...

    def history(self, claim_id: str) -> list[HistoryRow]: ...


def _validate_proposal(
    text: str,
    source_layer: str,
    horizon: str,
    evidence: list[EvidenceInput],
    confidence: float = 0.3,
) -> None:
    SourceLayer(source_layer)  # raises ValueError if unknown: no layer, no claim
    if not horizon:
        raise ValueError("horizon is required: one of day, week, season")
    try:
        Horizon(horizon)
    except ValueError:
        raise ValueError(f"horizon must be one of day, week, season, got {horizon!r}") from None
    if confidence > HORIZON_CAP[Horizon(horizon)]:
        raise ValueError(
            f"confidence {confidence} exceeds the {horizon}-horizon cap "
            f"{HORIZON_CAP[Horizon(horizon)]}"
        )
    if not text.strip():
        raise ValueError("claim text is empty")
    for e in evidence:
        _check_evidence(e["kind"])


def _check_decision(status: str) -> Status:
    s = Status(status)
    if s == Status.CANDIDATE:
        raise ValueError("confirm_or_retire takes 'active' or 'retired'")
    return s


class MemoryStore:
    """In-memory implementation used by tests and the replay harness."""

    def __init__(self) -> None:
        self._claims: dict[str, Claim] = {}
        self._history: list[HistoryRow] = []

    def _log(self, c: Claim, reason: str, by: str) -> None:
        self._history.append(
            HistoryRow(c.id, datetime.now(UTC), c.confidence, c.status, reason, by)
        )

    def query_claims(
        self,
        athlete_id: str | None = None,
        source_layer: str | None = None,
        status: str | None = None,
        text_contains: str | None = None,
    ) -> list[Claim]:
        return [
            c
            for c in self._claims.values()
            if not (athlete_id and c.athlete_id != athlete_id)
            and not (source_layer and c.source_layer != source_layer)
            and not (status and c.status != status)
            and not (text_contains and text_contains.lower() not in c.text.lower())
        ]

    def propose_claim(  # noqa: PLR0917  # callers pass all seven positionally (tests, mcp)
        self,
        athlete_id: str,
        text: str,
        source_layer: str,
        horizon: str,
        evidence: list[EvidenceInput],
        created_by: str,
        confidence: float = 0.3,
    ) -> Claim:
        _validate_proposal(text, source_layer, horizon, evidence, confidence)
        c = Claim(
            id=str(uuid.uuid4()),
            athlete_id=athlete_id,
            text=text,
            source_layer=SourceLayer(source_layer),
            horizon=Horizon(horizon),
            confidence=confidence,
            status=Status.CANDIDATE,
            created_by=created_by,
            created_at=datetime.now(UTC),
            evidence=tuple(Evidence(e["kind"], e["ref"], e.get("note")) for e in evidence),
        )
        self._claims[c.id] = c
        self._log(c, "proposed", created_by)
        return c

    def _get(self, claim_id: str) -> Claim:
        try:
            return self._claims[claim_id]
        except KeyError:
            raise ClaimNotFoundError(claim_id) from None

    def attach_evidence(
        self, claim_id: str, kind: str, ref: str, note: str | None = None
    ) -> Evidence:
        _check_evidence(kind)
        c = self._get(claim_id)
        ev = Evidence(kind, ref, note)
        self._claims[claim_id] = replace(c, evidence=(*c.evidence, ev))
        return ev

    def confirm_or_retire(self, claim_id: str, status: str, reason: str, by: str) -> Claim:
        s = _check_decision(status)
        c = replace(self._get(claim_id), status=s)
        self._claims[claim_id] = c
        self._log(c, reason, by)
        return c

    def record_adjustment(
        self, claim: Claim, reason: str, by: str, notes: Sequence[str] = ()
    ) -> Claim:
        """Persist a claim returned by rules.adjust_with_notes; log reason, then each note."""
        self._get(claim.id)
        c = replace(claim, last_tested_at=datetime.now(UTC))
        self._claims[c.id] = c
        self._log(c, reason, by)
        for note in notes:
            self._log(c, note, by)
        return c

    def clear_always_hit(self, claim_id: str, reason: str, by: str) -> Claim:
        c = replace(self._get(claim_id), always_hit=False)
        self._claims[claim_id] = c
        self._log(c, f"always-hit flag cleared: {reason}", by)
        return c

    def history(self, claim_id: str) -> list[HistoryRow]:
        return [h for h in self._history if h.claim_id == claim_id]


_COLS = (
    "id, athlete_id, text, source_layer, confidence, status, created_by, created_at, "
    "last_tested_at, hit_streak, horizon, scored, hits, always_hit"
)


# psycopg rows are untyped tuples straight from the database: the one honest use of Any here.
type _Row = tuple[Any, ...]
type _Conn = psycopg.Connection[_Row]
type _Cur = psycopg.Cursor[_Row]


def _returned_id(cur: _Cur) -> Any:
    """First column of the single row an ``INSERT ... RETURNING id`` produced."""
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT ... RETURNING produced no row")
    return row[0]


class PgStore:
    """psycopg implementation against migrations/0002_claims.sql."""

    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def _row_to_claim(self, r: _Row, evidence: Sequence[Evidence] = ()) -> Claim:
        return Claim(
            id=str(r[0]),
            athlete_id=r[1],
            text=r[2],
            source_layer=SourceLayer(r[3]),
            confidence=float(r[4]),
            status=Status(r[5]),
            created_by=r[6],
            created_at=r[7],
            last_tested_at=r[8],
            hit_streak=r[9],
            horizon=Horizon(r[10]),
            scored=r[11],
            hits=r[12],
            always_hit=r[13],
            evidence=tuple(evidence),
        )

    def _evidence(self, cur: _Cur, claim_id: str) -> list[Evidence]:
        cur.execute("SELECT id, kind, ref, note FROM evidence WHERE claim_id = %s", (claim_id,))
        return [Evidence(kind=k, ref=r, note=n, id=str(i)) for i, k, r, n in cur.fetchall()]

    def _get(self, cur: _Cur, claim_id: str) -> Claim:
        cur.execute(f"SELECT {_COLS} FROM claims WHERE id = %s", (claim_id,))
        row = cur.fetchone()
        if row is None:
            raise ClaimNotFoundError(claim_id)
        return self._row_to_claim(row, self._evidence(cur, claim_id))

    def _log(self, cur: _Cur, c: Claim, reason: str, by: str) -> None:
        cur.execute(
            "INSERT INTO claim_history (claim_id, confidence, status, reason, by) "
            "VALUES (%s, %s, %s, %s, %s)",
            (c.id, c.confidence, c.status.value, reason, by),
        )

    def query_claims(
        self,
        athlete_id: str | None = None,
        source_layer: str | None = None,
        status: str | None = None,
        text_contains: str | None = None,
    ) -> list[Claim]:
        where: list[str] = []
        args: list[str] = []
        for col, val in (
            ("athlete_id", athlete_id),
            ("source_layer", source_layer),
            ("status", status),
        ):
            if val:
                where.append(f"{col} = %s")
                args.append(val)
        if text_contains:
            where.append("text ILIKE %s")
            args.append(f"%{text_contains}%")
        sql = f"SELECT {_COLS} FROM claims"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at"
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
            return [self._row_to_claim(r, self._evidence(cur, r[0])) for r in rows]

    def propose_claim(  # noqa: PLR0917  # callers pass all seven positionally (tests, mcp)
        self,
        athlete_id: str,
        text: str,
        source_layer: str,
        horizon: str,
        evidence: list[EvidenceInput],
        created_by: str,
        confidence: float = 0.3,
    ) -> Claim:
        _validate_proposal(text, source_layer, horizon, evidence, confidence)
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO claims (athlete_id, text, source_layer, horizon, confidence, "
                "status, created_by) VALUES (%s, %s, %s, %s, %s, 'candidate', %s) "
                "RETURNING id",
                (athlete_id, text, source_layer, horizon, confidence, created_by),
            )
            cid = _returned_id(cur)
            for e in evidence:
                cur.execute(
                    "INSERT INTO evidence (claim_id, kind, ref, note) VALUES (%s, %s, %s, %s)",
                    (cid, e["kind"], e["ref"], e.get("note")),
                )
            c = self._get(cur, cid)
            self._log(cur, c, "proposed", created_by)
            return c

    def attach_evidence(
        self, claim_id: str, kind: str, ref: str, note: str | None = None
    ) -> Evidence:
        _check_evidence(kind)
        with self.conn.transaction(), self.conn.cursor() as cur:
            self._get(cur, claim_id)
            cur.execute(
                "INSERT INTO evidence (claim_id, kind, ref, note) VALUES (%s, %s, %s, %s) "
                "RETURNING id",
                (claim_id, kind, ref, note),
            )
            return Evidence(kind, ref, note, id=str(_returned_id(cur)))

    def confirm_or_retire(self, claim_id: str, status: str, reason: str, by: str) -> Claim:
        s = _check_decision(status)
        with self.conn.transaction(), self.conn.cursor() as cur:
            self._get(cur, claim_id)
            cur.execute("UPDATE claims SET status = %s WHERE id = %s", (s.value, claim_id))
            c = self._get(cur, claim_id)
            self._log(cur, c, reason, by)
            return c

    def record_adjustment(
        self, claim: Claim, reason: str, by: str, notes: Sequence[str] = ()
    ) -> Claim:
        with self.conn.transaction(), self.conn.cursor() as cur:
            self._get(cur, claim.id)
            cur.execute(
                "UPDATE claims SET confidence = %s, status = %s, source_layer = %s, "
                "hit_streak = %s, scored = %s, hits = %s, always_hit = %s, "
                "last_tested_at = now() WHERE id = %s",
                (
                    claim.confidence,
                    claim.status.value,
                    claim.source_layer.value,
                    claim.hit_streak,
                    claim.scored,
                    claim.hits,
                    claim.always_hit,
                    claim.id,
                ),
            )
            c = self._get(cur, claim.id)
            self._log(cur, c, reason, by)
            for note in notes:
                self._log(cur, c, note, by)
            return c

    def clear_always_hit(self, claim_id: str, reason: str, by: str) -> Claim:
        with self.conn.transaction(), self.conn.cursor() as cur:
            self._get(cur, claim_id)
            cur.execute("UPDATE claims SET always_hit = false WHERE id = %s", (claim_id,))
            c = self._get(cur, claim_id)
            self._log(cur, c, f"always-hit flag cleared: {reason}", by)
            return c

    def history(self, claim_id: str) -> list[HistoryRow]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT claim_id, ts, confidence, status, reason, by FROM claim_history "
                "WHERE claim_id = %s ORDER BY ts",
                (claim_id,),
            )
            return [
                HistoryRow(str(a), b, float(c), Status(d), e, f)
                for a, b, c, d, e, f in cur.fetchall()
            ]
