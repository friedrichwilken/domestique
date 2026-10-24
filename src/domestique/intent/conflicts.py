"""Constraint-versus-claim conflict report.

A claim addresses the same subject as a constraint when one of the claim's
bindings has a ``metric`` that is among the constraint's ``tags``. Bindings
are the only link; claim text is never matched. The intent layer beats every
other layer, so each row names the constraint as the one that applies and
lists the claim, with its source layer and confidence, as conflicting. The
report states the overlap; it does not resolve it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from domestique.claims.rules import SourceLayer
from domestique.claims.store import Claim
from domestique.intent.schemas import Constraint
from domestique.loop.model import Binding


@dataclass(frozen=True)
class Conflict:
    """One (constraint, claim) pair that share a subject; the constraint applies."""

    constraint: Constraint
    claim_id: str
    claim_text: str
    claim_source_layer: SourceLayer
    claim_confidence: float
    metrics: tuple[str, ...]
    wording: str
    winner: Literal["constraint"] = "constraint"


def _wording(constraint: Constraint, claim: Claim, metrics: Sequence[str]) -> str:
    said = constraint.text if constraint.text is not None else str(constraint.value)
    return (
        f"Constraint '{constraint.id}' (\"{said}\", set by {constraint.set_by}) and claim "
        f"'{claim.text}' ({claim.source_layer}, confidence {claim.confidence:.2f}) both concern "
        f"{', '.join(metrics)}. The constraint applies until a human changes constraints.yaml."
    )


def _metrics_by_claim(bindings: Sequence[Binding]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for b in bindings:
        out[b.claim_id].add(str(b.metric))
    return out


def conflicts(
    constraints: Sequence[Constraint],
    claims: Sequence[Claim],
    bindings: Sequence[Binding],
) -> list[Conflict]:
    """One row per (constraint, active claim) pair whose binding metrics meet the tags."""
    by_claim = _metrics_by_claim(bindings)
    rows: list[Conflict] = []
    for constraint in constraints:
        tags = set(constraint.tags)
        for claim in claims:
            shared = tuple(sorted(tags & by_claim.get(claim.id, set())))
            if claim.status != "active" or not shared:
                continue
            rows.append(
                Conflict(
                    constraint=constraint,
                    claim_id=claim.id,
                    claim_text=claim.text,
                    claim_source_layer=claim.source_layer,
                    claim_confidence=claim.confidence,
                    metrics=shared,
                    wording=_wording(constraint, claim, shared),
                )
            )
    return rows
