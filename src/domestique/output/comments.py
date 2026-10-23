"""Debrief comments written to an activity, behind the ``write_comments`` switch.

Every comment the system writes starts with ``SYSTEM_MARKER`` so it is never
confused with the athlete's, and every statement in it names its source
layer ("your data shows" / "you told me" / "the literature says"). A remark
about one interval is pinned to that interval's stream indices.

The writer only ever creates comments. It has no path to edit or delete one,
so comments by anyone else are untouched by construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from domestique.claims.rules import SourceLayer
from domestique.config import Config
from domestique.ingest.icu_client import IcuPayload

SYSTEM_MARKER = "[domestique]"

LAYER_LABEL: dict[SourceLayer, str] = {
    SourceLayer.OBSERVED: "your data shows",
    SourceLayer.STATED: "you told me",
    SourceLayer.PRIOR: "the literature says",
}


def is_system_comment(content: str) -> bool:
    """True for comments this system wrote (they start with the marker)."""
    return content.lstrip().startswith(SYSTEM_MARKER)


@dataclass(frozen=True)
class Statement:
    text: str
    layer: SourceLayer


@dataclass(frozen=True)
class Pin:
    """The stretch of the ride a comment points at, as stream indices."""

    start_index: int
    end_index: int

    @classmethod
    def from_interval(cls, interval: IcuPayload) -> Pin:
        """Pin to an intervals.icu interval payload (its ``start_index``/``end_index``)."""
        return cls(int(interval["start_index"]), int(interval["end_index"]))


@dataclass(frozen=True)
class Remark:
    """One comment: statements about the ride, optionally pinned to an interval."""

    statements: tuple[Statement, ...]
    pin: Pin | None = None

    def __post_init__(self) -> None:
        if not self.statements:
            raise ValueError("a remark needs at least one statement")


class CommentPoster(Protocol):
    def post_message(self, activity_id: str, body: dict[str, object]) -> object: ...


def render(remark: Remark) -> str:
    """Comment text: the marker line, then one labelled statement per line."""
    lines = [SYSTEM_MARKER]
    lines += [f"- ({LAYER_LABEL[s.layer]}) {s.text}" for s in remark.statements]
    return "\n".join(lines)


def body(remark: Remark) -> dict[str, object]:
    """The request body for one comment, with pin indices when the remark has a pin."""
    payload: dict[str, object] = {"content": render(remark)}
    if remark.pin is not None:
        payload["start_index"] = remark.pin.start_index
        payload["end_index"] = remark.pin.end_index
    return payload


def write_debrief(
    cfg: Config, poster: CommentPoster, activity_id: str, remarks: Sequence[Remark]
) -> list[dict[str, object]]:
    """Produce the debrief comments; post them only when ``cfg.write_comments`` is true.

    Returns the bodies either way, so the debrief always exists locally.
    """
    bodies = [body(r) for r in remarks]
    if cfg.write_comments:
        for b in bodies:
            poster.post_message(activity_id, b)
    return bodies
