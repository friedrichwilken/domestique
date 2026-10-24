"""The source-layer check on the way out: every statement names its layer.

A statement is a Markdown bullet or a line that ends a sentence (``.``, ``!``,
``?``). It passes when it carries one of the labels ``output.comments`` renders,
``(your data shows)``, ``(you told me)``, ``(the literature says)``. Text that
arrived from a tool and must be shown unchanged (rail wording, question text)
is passed in as ``exempt`` and passes as it is. Headings, table rows and code
blocks are not statements. The check is textual: it enforces the habit of
naming the layer, not the truth of the statement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from domestique.output.comments import LAYER_LABEL

LABELS: tuple[str, ...] = tuple(f"({label})" for label in LAYER_LABEL.values())
MARK = "**[unlabelled]**"

_BULLET = re.compile(r"^(?P<lead>\s*(?:>\s*)*(?:[-*+]|\d+[.)])\s+)(?P<body>\S.*)$")
_QUOTE = re.compile(r"^(?P<lead>\s*(?:>\s*)*)(?P<body>.*)$")
_CLOSING = "\"')]*_" + "\N{RIGHT DOUBLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
_SENTENCE_END = re.compile(f"[.!?][{re.escape(_CLOSING)}]*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CURLY = (
    "\N{LEFT SINGLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
    "\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}"
)
_WRAPPERS = "\"'*_` " + _CURLY


@dataclass(frozen=True)
class Checked:
    ok: bool
    unlabelled: tuple[str, ...]


@dataclass(frozen=True)
class _Statement:
    line: int
    lead: str  # bullet marker or quote prefix, kept when the line is marked
    text: str


def _normal(text: str) -> str:
    """Whitespace collapsed, wrapping quotes and emphasis removed: how exempt text compares."""
    return " ".join(text.split()).strip(_WRAPPERS)


def _statement(index: int, line: str) -> _Statement | None:
    bullet = _BULLET.match(line)
    if bullet:
        return _Statement(index, bullet["lead"], bullet["body"].rstrip())
    quoted = _QUOTE.match(line)
    body = quoted["body"].rstrip() if quoted else line.rstrip()
    if not body or body.startswith(("#", "|")) or not _SENTENCE_END.search(body):
        return None
    return _Statement(index, quoted["lead"] if quoted else "", body)


def _statements(text: str) -> Iterator[_Statement]:
    in_code = False
    for index, line in enumerate(text.splitlines()):
        if _FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        found = _statement(index, line)
        if found is not None:
            yield found


def _labelled(text: str) -> bool:
    lowered = text.lower()
    return any(label in lowered for label in LABELS)


def _failing(text: str, exempt: Iterable[str]) -> list[_Statement]:
    passes = {_normal(e) for e in exempt if e.strip()}
    return [s for s in _statements(text) if not _labelled(s.text) and _normal(s.text) not in passes]


def check_layers(text: str, exempt: Iterable[str] = ()) -> Checked:
    """Every statement without a layer label and not exempt, in order of appearance."""
    failing = tuple(s.text for s in _failing(text, exempt))
    return Checked(ok=not failing, unlabelled=failing)


def mark_unlabelled(text: str, exempt: Iterable[str] = ()) -> str:
    """``text`` with ``**[unlabelled]**`` in front of every statement that fails the check."""
    lines = text.splitlines()
    for s in _failing(text, exempt):
        lines[s.line] = f"{s.lead}{MARK} {s.text}"
    return "\n".join(lines)
