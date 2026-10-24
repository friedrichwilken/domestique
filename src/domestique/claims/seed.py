"""Seed files: claims with their evidence and, where a claim can feed a metric, its bindings.

A seed file is YAML::

    athlete_id: athlete-synth-1
    claims:
      - text: "..."
        source_layer: observed | stated | prior
        horizon: day | week | season
        confidence: 0.6
        evidence: [{kind, ref, note?}, ...]
        bindings:                       # optional; a claim without one feeds no prediction
          - metric: sleep_hours
            params: {offset: -0.67, range_abs: 0.4}
            conditions: {min_if: 0.85, start_hour_from: 17, start_hour_to: 23}

``read_seed`` parses and validates the whole file (bindings through
``loop.model.parse_binding``) before anything is written. ``load_seed`` writes
it through the stores: every claim is proposed (status ``candidate``) and,
only when the caller asks for ``activate``, confirmed as ``active``. Loading
into a live store keeps the human gate: leave ``activate`` off and confirm
through the claims MCP. The replay harness activates its seed in its own
in-memory stores, which never reach the athlete's claims store.

Usage: python -m domestique.claims.seed --file evals/priors.yaml [--activate] [--athlete-id ID]

The command writes into the configured database for the configured athlete
(``--athlete-id`` overrides it, as does ``ICU_ATHLETE_ID``; the file's own
``athlete_id`` is not used). Without ``--activate`` every claim stays a
candidate until a human confirms it through the claims MCP.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from domestique import db
from domestique.claims.store import Claim, ClaimsStore, EvidenceInput, PgStore
from domestique.ingest.settings import cli_settings
from domestique.loop.model import Binding, parse_binding
from domestique.loop.store import LoopStore, PgLoopStore

SEED_BY = "seed"
_PLACEHOLDER_ID = "seed"  # bindings are parsed before the claim exists


@dataclass(frozen=True)
class SeedBinding:
    metric: str
    params: Mapping[str, object]
    conditions: Mapping[str, object]

    def bind(self, claim_id: str) -> Binding:
        return parse_binding(claim_id, self.metric, self.params, self.conditions)


@dataclass(frozen=True)
class SeedClaim:
    text: str
    source_layer: str
    horizon: str
    confidence: float
    evidence: tuple[EvidenceInput, ...]
    bindings: tuple[SeedBinding, ...] = ()


@dataclass(frozen=True)
class Seed:
    athlete_id: str
    claims: tuple[SeedClaim, ...]


def _mapping(raw: object, what: str) -> Mapping[str, object]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TypeError(f"{what} must be a mapping, got {raw!r}")
    return {str(k): v for k, v in raw.items()}


def _list(raw: object, what: str) -> list[object]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TypeError(f"{what} must be a list, got {raw!r}")
    return raw


def _binding(raw: object, where: str) -> SeedBinding:
    entry = _mapping(raw, where)
    b = SeedBinding(
        metric=str(entry.get("metric", "")),
        params=_mapping(entry.get("params"), f"{where}.params"),
        conditions=_mapping(entry.get("conditions"), f"{where}.conditions"),
    )
    b.bind(_PLACEHOLDER_ID)  # validate now: a bad binding fails the file, not a later write
    return b


def _evidence(raw: object, where: str) -> EvidenceInput:
    entry = _mapping(raw, where)
    note = entry.get("note")
    return {
        "kind": str(entry["kind"]),
        "ref": str(entry["ref"]),
        "note": None if note is None else str(note),
    }


def _claim(raw: object, where: str) -> SeedClaim:
    entry = _mapping(raw, where)
    confidence = entry.get("confidence", 0.3)
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        raise TypeError(f"{where}.confidence must be a number, got {confidence!r}")
    return SeedClaim(
        text=str(entry["text"]),
        source_layer=str(entry["source_layer"]),
        horizon=str(entry.get("horizon", "")),
        confidence=float(confidence),
        evidence=tuple(
            _evidence(e, f"{where}.evidence[{i}]")
            for i, e in enumerate(_list(entry.get("evidence"), f"{where}.evidence"))
        ),
        bindings=tuple(
            _binding(b, f"{where}.bindings[{i}]")
            for i, b in enumerate(_list(entry.get("bindings"), f"{where}.bindings"))
        ),
    )


def parse_seed(raw: object, where: str = "seed") -> Seed:
    doc = _mapping(raw, where)
    claims = _list(doc.get("claims"), f"{where}.claims")
    return Seed(
        athlete_id=str(doc["athlete_id"]),
        claims=tuple(_claim(c, f"{where}.claims[{i}]") for i, c in enumerate(claims)),
    )


def read_seed(path: Path) -> Seed:
    """Parse and validate a seed file; nothing is written."""
    return parse_seed(yaml.safe_load(path.read_text()), str(path))


def load_seed(
    seed: Seed,
    claims: ClaimsStore,
    loop: LoopStore,
    athlete_id: str | None = None,
    activate: bool = False,
    by: str = SEED_BY,
) -> list[tuple[Claim, tuple[Binding, ...]]]:
    """Write the seed's claims and bindings; returns each claim with its bindings.

    ``athlete_id`` overrides the file's (the replay seeds textbook priors for
    whichever athlete it replays).
    """
    who = athlete_id or seed.athlete_id
    out: list[tuple[Claim, tuple[Binding, ...]]] = []
    for s in seed.claims:
        c = claims.propose_claim(
            who, s.text, s.source_layer, s.horizon, list(s.evidence), by, s.confidence
        )
        if activate:
            c = claims.confirm_or_retire(c.id, "active", "seeded", by)
        bound = tuple(b.bind(c.id) for b in s.bindings)
        for b in bound:
            loop.add_binding(b)
        out.append((c, bound))
    return out


# --- command line --------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load a seed file into the claims store.")
    p.add_argument("--file", required=True, type=Path, help="seed YAML, e.g. evals/priors.yaml")
    p.add_argument(
        "--activate",
        action="store_true",
        help="confirm every seeded claim as active (default: they stay candidates)",
    )
    p.add_argument("--athlete-id", help="write for this athlete instead of the configured one")
    return p.parse_args(argv)


def settings(
    args: argparse.Namespace, env: Mapping[str, str] | None = None
) -> tuple[str, str | None]:
    """Athlete id and database URL: ``--athlete-id`` first, then the ingest CLIs' rules."""
    source: Mapping[str, str] = os.environ if env is None else env
    if args.athlete_id:
        source = {**source, "ICU_ATHLETE_ID": args.athlete_id}
    return cli_settings(source)


def summary(loaded: list[tuple[Claim, tuple[Binding, ...]]]) -> str:
    statuses = sorted({c.status.value for c, _ in loaded})
    n_bindings = sum(len(bs) for _, bs in loaded)
    return f"seeded {len(loaded)} claims ({', '.join(statuses) or 'none'}), {n_bindings} bindings"


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> None:
    args = parse_args(argv)
    seed = read_seed(args.file)  # validate the whole file before connecting
    athlete_id, dsn = settings(args, env)
    with db.connect(dsn) as conn:
        db.migrate(conn)
        with conn.transaction():  # all claims and bindings, or none
            loaded = load_seed(
                seed, PgStore(conn), PgLoopStore(conn), athlete_id, activate=args.activate
            )
    sys.stdout.write(summary(loaded) + "\n")


if __name__ == "__main__":
    main()
