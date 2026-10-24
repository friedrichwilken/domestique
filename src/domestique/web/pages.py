"""Render the pages from Jinja2 templates. The templates lay out; they compute nothing."""

from __future__ import annotations

from dataclasses import dataclass

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from domestique.web import charts
from domestique.web.queries import ReportData

# DESIGN.md, "What this cannot learn": each bullet's title and its first sentence,
# quoted, not paraphrased (tests/test_web_app.py checks them against DESIGN.md).
CANNOT_LEARN: tuple[tuple[str, str], ...] = (
    (
        "Slow adaptations at n=1.",
        "Which kind of training raises one athlete's threshold more, whether a block "
        '"worked", how they respond to altitude or heat over a season.',
    ),
    (
        "Responder typing.",
        "Placing an athlete in a category of responders would need large, clean population "
        "datasets that do not exist openly; published studies are small and specific.",
    ),
    (
        "Causal credit for a result.",
        "A good race after a block is one confounded sample.",
    ),
)

_ENV = Environment(
    loader=PackageLoader("domestique.web", "templates"),
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=True,
)


@dataclass(frozen=True)
class ClaimSection:
    row: charts.Row
    strip: Markup


def claims_page(data: ReportData, shadows: bool = True) -> str:
    """The claims report: table, one calibration strip per claim, the scatter, the footer."""
    rows = charts.claims_table(data)
    # Markup: charts builds the SVG itself and escapes every text value it puts in.
    sections = [
        ClaimSection(row, Markup(charts.calibration_strip(c, c.predictions, shadows=shadows)))
        for row, c in zip(rows, data.claims, strict=True)
    ]
    return _ENV.get_template("claims.html").render(
        rows=rows,
        sections=sections,
        scatter=Markup(charts.confidence_vs_hit_rate(data)),
        shadows=shadows,
        cannot_learn=CANNOT_LEARN,
    )
