"""Storage for the loop: bindings, predictions, outcomes and questions.

One interface, an in-memory implementation for tests and the replay harness,
and a Postgres one against migrations 0002, 0005 and 0006. Predictions are
pre-registered once per session, metric and claim, with at most one official
prediction per session and metric: an official prediction arriving after one
is already registered is kept as a shadow (the first registration stays the
reported one). ``save_predictions`` returns what it wrote, as written. An
outcome is written once per prediction, and ``record_outcome`` says whether
this call wrote it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from domestique import db
from domestique.analysis.plan_vs_execution import Question, save_questions
from domestique.loop.model import (
    Binding,
    Metric,
    Outcome,
    Prediction,
    binding_params,
    conditions_json,
    parse_binding,
)


class LoopStore(Protocol):
    def add_binding(self, binding: Binding) -> None: ...

    def bindings(self, athlete_id: str) -> list[Binding]: ...

    def save_predictions(self, predictions: Sequence[Prediction]) -> list[Prediction]: ...

    def predictions_for(self, planned_session_id: int) -> list[Prediction]: ...

    def scored_ids(self, planned_session_id: int) -> set[str]: ...

    def record_outcome(self, outcome: Outcome) -> bool: ...

    def save_question(self, question: Question) -> None: ...


@dataclass
class MemoryLoopStore:
    """In memory, for one athlete (``athlete_id`` None: whichever athlete asks)."""

    athlete_id: str | None = None
    binding_rows: dict[tuple[str, Metric], Binding] = field(default_factory=dict)
    predictions: dict[str, Prediction] = field(default_factory=dict)
    outcomes: dict[str, Outcome] = field(default_factory=dict)
    questions: list[Question] = field(default_factory=list)

    def add_binding(self, binding: Binding) -> None:
        self.binding_rows[(binding.claim_id, binding.metric)] = binding

    def bindings(self, athlete_id: str) -> list[Binding]:
        if self.athlete_id not in (None, athlete_id):
            return []
        return list(self.binding_rows.values())

    def save_predictions(self, predictions: Sequence[Prediction]) -> list[Prediction]:
        saved = []
        for p in predictions:
            mine = [
                q
                for q in self.predictions.values()
                if (q.planned_session_id, q.metric) == (p.planned_session_id, p.metric)
            ]
            if any(q.claim_id == p.claim_id for q in mine):
                continue
            row = _as_shadow_if_taken(p, any(q.official for q in mine))
            self.predictions[row.id] = row
            saved.append(row)
        return saved

    def predictions_for(self, planned_session_id: int) -> list[Prediction]:
        return [p for p in self.predictions.values() if p.planned_session_id == planned_session_id]

    def scored_ids(self, planned_session_id: int) -> set[str]:
        return {p.id for p in self.predictions_for(planned_session_id) if p.id in self.outcomes}

    def record_outcome(self, outcome: Outcome) -> bool:
        if outcome.prediction_id in self.outcomes:
            return False
        self.outcomes[outcome.prediction_id] = outcome
        return True

    def save_question(self, question: Question) -> None:
        self.questions.append(question)


def _as_shadow_if_taken(p: Prediction, official_taken: bool) -> Prediction:
    return replace(p, official=False) if p.official and official_taken else p


def _prediction(r: tuple[Any, ...]) -> Prediction:
    return Prediction(
        id=str(r[0]),
        planned_session_id=r[1],
        metric=Metric(r[2]),
        expected=float(r[3]),
        low=float(r[4]),
        high=float(r[5]),
        claim_ids=tuple(str(c) for c in r[6]),
        basis=dict(r[7]),
        official=bool(r[8]),
    )


class PgLoopStore:
    def __init__(self, conn: db.Conn) -> None:
        self.conn = conn

    def add_binding(self, binding: Binding) -> None:
        self.conn.execute(
            "INSERT INTO claim_bindings (claim_id, metric, params, conditions) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (claim_id, metric) DO UPDATE SET "
            "params = EXCLUDED.params, conditions = EXCLUDED.conditions",
            (
                binding.claim_id,
                binding.metric.value,
                Jsonb(binding_params(binding)),
                Jsonb(conditions_json(binding.when)),
            ),
        )

    def bindings(self, athlete_id: str) -> list[Binding]:
        rows = self.conn.execute(
            "SELECT b.claim_id, b.metric, b.params, b.conditions FROM claim_bindings b "
            "JOIN claims c ON c.id = b.claim_id WHERE c.athlete_id = %s ORDER BY b.created_at",
            (athlete_id,),
        ).fetchall()
        return [parse_binding(str(r[0]), r[1], r[2], r[3]) for r in rows]

    def _official_taken(self, p: Prediction) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM predictions WHERE planned_session_id = %s AND metric = %s AND official",
            (p.planned_session_id, p.metric.value),
        ).fetchone()
        return row is not None

    def save_predictions(self, predictions: Sequence[Prediction]) -> list[Prediction]:
        saved = []
        for p in predictions:
            row = _as_shadow_if_taken(p, p.official and self._official_taken(p))
            inserted = self.conn.execute(
                "INSERT INTO predictions (id, planned_session_id, metric, claim_id, official, "
                "expected, low, high, claim_ids, basis) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s) "
                "ON CONFLICT (planned_session_id, metric, claim_id) DO NOTHING RETURNING id",
                (
                    row.id,
                    row.planned_session_id,
                    row.metric.value,
                    row.claim_id,
                    row.official,
                    row.expected,
                    row.low,
                    row.high,
                    list(row.claim_ids),
                    Jsonb(row.basis),
                ),
            ).fetchone()
            if inserted is not None:
                saved.append(row)
        return saved

    def predictions_for(self, planned_session_id: int) -> list[Prediction]:
        rows = self.conn.execute(
            "SELECT id, planned_session_id, metric, expected, low, high, claim_ids, basis, "
            "official FROM predictions WHERE planned_session_id = %s "
            "ORDER BY metric, official DESC, claim_id",
            (planned_session_id,),
        ).fetchall()
        return [_prediction(r) for r in rows]

    def scored_ids(self, planned_session_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT o.prediction_id FROM outcomes o JOIN predictions p ON p.id = o.prediction_id "
            "WHERE p.planned_session_id = %s",
            (planned_session_id,),
        ).fetchall()
        return {str(r[0]) for r in rows}

    def record_outcome(self, outcome: Outcome) -> bool:
        row = self.conn.execute(
            "INSERT INTO outcomes (prediction_id, actual, error) VALUES (%s, %s, %s) "
            "ON CONFLICT (prediction_id) DO NOTHING RETURNING prediction_id",
            (outcome.prediction_id, outcome.actual, outcome.error),
        ).fetchone()
        return row is not None

    def save_question(self, question: Question) -> None:
        save_questions(self.conn, [question])
