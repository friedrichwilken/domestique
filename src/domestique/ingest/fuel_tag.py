"""Deterministic parser for the ``#fuel`` tag in activity comments.

A tag is a line whose first word is ``#fuel``, followed by any of
``<n>ml``, ``<n>l``, ``<n>g``, ``<n>kcal`` in any order::

    #fuel 1.5l 240g 1100kcal

Fluid is normalised to millilitres, carbohydrate to grams, energy to
kilocalories. Words that are not one of those tokens are kept as free text
and never guessed at ("2 bottles" stays text). The comment itself is not
modified; ``Tag.rest`` only lists the words the parser did not use.

Within one comment the last ``#fuel`` line wins, and within a line the last
token of a unit wins. Decimal commas are accepted (``1,5l``). Matching of
the keyword and the units ignores case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KEYWORD = "#fuel"

_TOKEN = re.compile(r"(?P<n>\d+(?:[.,]\d+)?)(?P<unit>kcal|ml|l|g)", re.IGNORECASE)
_ML_PER_UNIT = {"ml": 1.0, "l": 1000.0}


@dataclass(frozen=True)
class Tag:
    """Intake parsed from one ``#fuel`` line. Absent quantities stay None."""

    fluid_ml: float | None = None
    carbs_g: float | None = None
    kcal: float | None = None
    rest: tuple[str, ...] = field(default=())


def _tag_lines(text: str) -> list[list[str]]:
    """The words after the keyword, for every line that starts with it."""
    found: list[list[str]] = []
    for line in text.splitlines():
        words = line.split()
        if words and words[0].lower() == KEYWORD:
            found.append(words[1:])
    return found


def _parse_words(words: list[str]) -> Tag:
    fluid: float | None = None
    carbs: float | None = None
    kcal: float | None = None
    rest: list[str] = []
    for word in words:
        m = _TOKEN.fullmatch(word)
        if m is None:
            rest.append(word)
            continue
        n = float(m["n"].replace(",", "."))
        unit = m["unit"].lower()
        if unit in _ML_PER_UNIT:
            fluid = n * _ML_PER_UNIT[unit]
        elif unit == "g":
            carbs = n
        else:
            kcal = n
    return Tag(fluid_ml=fluid, carbs_g=carbs, kcal=kcal, rest=tuple(rest))


def parse(text: str) -> Tag | None:
    """The intake stated by the last ``#fuel`` line in ``text``, or None without one."""
    lines = _tag_lines(text)
    if not lines:
        return None
    return _parse_words(lines[-1])
