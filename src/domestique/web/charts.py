"""Table rows and inline SVG for the claims report. Pure functions over ``ReportData``.

Every number shown on the page is computed here or in ``queries``; the
templates only lay the results out. Colour never carries meaning alone: a hit
is a filled circle, a miss a hollow circle with its signed distance to the
range as a text label, a shadow prediction is drawn lighter and marked
``data-shadow="1"``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from domestique.web.queries import ClaimReport, PredictionRow, ReportData

STRIP_LIMIT = 60
EARLY_BELOW = 10  # scored predictions under which a claim is labelled early

# calibration strip geometry (px)
STRIP_WIDTH = 720
LANE_HEIGHT = 90
LANE_GAP = 14
STRIP_LEFT = 64
STRIP_RIGHT = 12
STRIP_TOP = 18
MARKER_R = 4
SHADOW_OPACITY = 0.35

# scatter geometry (px)
SCATTER_SIZE = 360
SCATTER_PAD = 48
MIN_R = 4.0
MAX_R = 14.0


@dataclass(frozen=True)
class Row:
    """One claims-table row, every cell already formatted."""

    number: int
    id: str
    text: str
    status: str
    source_layer: str
    horizon: str
    confidence: str
    scored: str
    hit_rate: str
    error_share: str
    flags: tuple[str, ...]


def _share(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _flags(c: ClaimReport) -> tuple[str, ...]:
    out = []
    if c.uninformative:
        out.append("uninformative")
    if c.overconfident:
        out.append("overconfident")
    return tuple(out)


def claims_table(data: ReportData) -> list[Row]:
    return [
        Row(
            number=i,
            id=c.id,
            text=c.text,
            status=c.status,
            source_layer=c.source_layer,
            horizon=c.horizon,
            confidence=f"{c.confidence:.2f}",
            scored=str(c.scored),
            hit_rate=_rate(c.hit_rate),
            error_share=_share(c.error_share),
            flags=_flags(c),
        )
        for i, c in enumerate(data.claims, start=1)
    ]


# --- calibration strip ---------------------------------------------------------


@dataclass(frozen=True)
class _Scale:
    """Linear map from a metric's values to the y pixels of one lane."""

    lo: float
    hi: float
    top: float
    height: float

    def y(self, value: float) -> float:
        return self.top + (self.hi - value) / (self.hi - self.lo) * self.height


def _scale(rows: Sequence[PredictionRow], top: float) -> _Scale:
    values = [v for p in rows for v in (p.low, p.high, p.actual)]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.08 or max(abs(hi) * 0.05, 1.0)
    return _Scale(lo - pad, hi + pad, top, LANE_HEIGHT)


def _num(value: float) -> str:
    return f"{value:.4g}"


def _tooltip(p: PredictionRow) -> str:
    kind = "official" if p.official else "shadow"
    verdict = "hit" if p.hit else f"miss by {p.miss_by:+.3g}"
    return escape(
        f"{p.day.isoformat()} {p.metric} ({kind}): range {_num(p.low)} to {_num(p.high)}, "
        f"observed {_num(p.actual)}, {verdict}"
    )


def _marker(p: PredictionRow, x: float, y: float) -> str:
    if p.hit:
        return f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="{MARKER_R}" fill="currentColor"/>'
    label_y = y - MARKER_R - 3 if p.actual > p.high else y + MARKER_R + 11
    return (
        f'<circle class="miss" cx="{x:.1f}" cy="{y:.1f}" r="{MARKER_R}" fill="none" '
        f'stroke="currentColor" stroke-width="1.5"/>'
        f'<text class="miss-label" x="{x:.1f}" y="{label_y:.1f}" text-anchor="middle" '
        f'font-size="10" fill="currentColor">{p.miss_by:+.3g}</text>'
    )


def _prediction(p: PredictionRow, x: float, width: float, scale: _Scale) -> str:
    shadow = "" if p.official else f' data-shadow="1" opacity="{SHADOW_OPACITY}"'
    top, bottom = scale.y(p.high), scale.y(p.low)
    band = (
        f'<rect class="band" x="{x - width / 2:.1f}" y="{top:.1f}" width="{width:.1f}" '
        f'height="{max(bottom - top, 1.0):.1f}" rx="2" fill="currentColor" fill-opacity="0.18"/>'
    )
    return (
        f'<g class="pred"{shadow}><title>{_tooltip(p)}</title>'
        f"{band}{_marker(p, x, scale.y(p.actual))}</g>"
    )


def _lane(
    metric: str, shown: Sequence[tuple[int, PredictionRow]], slot: float, top: float
) -> list[str]:
    """One metric's predictions on its own y-scale; x is the position in the shown sequence."""
    placed = [(i, p) for i, p in shown if p.metric == metric]
    scale = _scale([p for _, p in placed], top)
    width = max(min(slot * 0.6, 14.0), 2.0)
    parts = [
        f'<text class="axis" x="4" y="{top + 10:.1f}" font-size="11">{escape(metric)}</text>',
        f'<text class="axis" x="{STRIP_LEFT - 6}" y="{top + 4:.1f}" font-size="10" '
        f'text-anchor="end">{_num(scale.hi)}</text>',
        f'<text class="axis" x="{STRIP_LEFT - 6}" y="{top + LANE_HEIGHT:.1f}" font-size="10" '
        f'text-anchor="end">{_num(scale.lo)}</text>',
        f'<line class="grid" x1="{STRIP_LEFT}" y1="{top + LANE_HEIGHT:.1f}" '
        f'x2="{STRIP_WIDTH - STRIP_RIGHT}" y2="{top + LANE_HEIGHT:.1f}" stroke="currentColor" '
        f'stroke-opacity="0.2"/>',
    ]
    for i, p in placed:
        x = STRIP_LEFT + (i + 0.5) * slot
        parts.append(_prediction(p, x, width, scale))
    return parts


def visible(predictions: Sequence[PredictionRow], shadows: bool = True) -> list[PredictionRow]:
    return [p for p in predictions if shadows or p.official]


def calibration_strip(
    claim: ClaimReport,
    predictions: Sequence[PredictionRow],
    limit: int = STRIP_LIMIT,
    shadows: bool = True,
) -> str:
    """Range band and observed marker per scored prediction, most recent ``limit``.

    One lane per metric the claim predicts (metrics have different units).
    ``shadows=False`` leaves shadow predictions out before the limit is applied.
    """
    rows = visible(predictions, shadows)
    omitted = max(len(rows) - limit, 0)
    shown = rows[omitted:]
    label = escape(f"Calibration strip: {claim.text}")
    if not shown:
        return (
            f'<svg class="strip" xmlns="http://www.w3.org/2000/svg" width="{STRIP_WIDTH}" '
            f'height="28" role="img" aria-label="{label}"><text class="axis" x="4" y="18" '
            f'font-size="12">no scored predictions yet</text></svg>'
        )
    metrics = list(dict.fromkeys(p.metric for p in shown))
    positioned = list(enumerate(shown))
    slot = (STRIP_WIDTH - STRIP_LEFT - STRIP_RIGHT) / len(shown)
    parts: list[str] = []
    top = float(STRIP_TOP)
    for metric in metrics:
        parts.extend(_lane(metric, positioned, slot, top))
        top += LANE_HEIGHT + LANE_GAP
    if omitted:
        parts.append(
            f'<text class="omitted" x="{STRIP_LEFT}" y="12" font-size="11">'
            f"{omitted} earlier omitted, showing the most recent {len(shown)}</text>"
        )
    height = top - LANE_GAP + 16
    return (
        f'<svg class="strip" xmlns="http://www.w3.org/2000/svg" width="{STRIP_WIDTH}" '
        f'height="{height:.0f}" viewBox="0 0 {STRIP_WIDTH} {height:.0f}" role="img" '
        f'aria-label="{label}">{"".join(parts)}</svg>'
    )


# --- confidence against hit rate -----------------------------------------------


def _radius(scored: int) -> float:
    return min(MIN_R + 1.5 * math.sqrt(scored), MAX_R)


def _px(value: float) -> float:
    return SCATTER_PAD + value * (SCATTER_SIZE - 2 * SCATTER_PAD)


def _py(value: float) -> float:
    return SCATTER_SIZE - SCATTER_PAD - value * (SCATTER_SIZE - 2 * SCATTER_PAD)


def _axes() -> list[str]:
    lo, hi = _px(0), _px(1)
    parts = [
        f'<line class="axis-line" x1="{lo}" y1="{_py(0)}" x2="{hi}" y2="{_py(0)}" '
        f'stroke="currentColor" stroke-opacity="0.4"/>',
        f'<line class="axis-line" x1="{lo}" y1="{_py(0)}" x2="{lo}" y2="{_py(1)}" '
        f'stroke="currentColor" stroke-opacity="0.4"/>',
        f'<line class="diagonal" x1="{lo}" y1="{_py(0)}" x2="{hi}" y2="{_py(1)}" '
        f'stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="4 4"/>',
        f'<text class="axis" x="{(lo + hi) / 2}" y="{SCATTER_SIZE - 10}" font-size="12" '
        f'text-anchor="middle">stated confidence</text>',
        f'<text class="axis" x="14" y="{(_py(0) + _py(1)) / 2}" font-size="12" '
        f'text-anchor="middle" transform="rotate(-90 14 {(_py(0) + _py(1)) / 2})">'
        f"observed hit rate</text>",
    ]
    for tick in (0.0, 0.5, 1.0):
        parts.append(
            f'<text class="axis" x="{_px(tick)}" y="{_py(0) + 16}" font-size="10" '
            f'text-anchor="middle">{tick:g}</text>'
        )
        parts.append(
            f'<text class="axis" x="{lo - 6}" y="{_py(tick) + 3}" font-size="10" '
            f'text-anchor="end">{tick:g}</text>'
        )
    return parts


def _point(number: int, c: ClaimReport, rate: float) -> str:
    x, y, r = _px(c.confidence), _py(rate), _radius(c.scored)
    tip = escape(
        f"#{number} {c.text}: confidence {c.confidence:.2f}, hit rate {rate:.0%}, n={c.scored}"
    )
    early = (
        f'<text class="early" x="{x + r + 3:.1f}" y="{y + 4:.1f}" font-size="10" '
        f'fill="currentColor">early</text>'
        if c.scored < EARLY_BELOW
        else ""
    )
    return (
        f'<g class="claim-point"><title>{tip}</title>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="currentColor" fill-opacity="0.55" '
        f'stroke="currentColor"/>'
        f'<text class="claim-no" x="{x:.1f}" y="{y - r - 3:.1f}" font-size="10" '
        f'text-anchor="middle" fill="currentColor">{number}</text>{early}</g>'
    )


def confidence_vs_hit_rate(data: ReportData) -> str:
    """One marker per claim with at least one scored prediction; the diagonal is drawn."""
    parts = _axes()
    for number, c in enumerate(data.claims, start=1):
        if c.hit_rate is not None:
            parts.append(_point(number, c, c.hit_rate))
    return (
        f'<svg class="scatter" xmlns="http://www.w3.org/2000/svg" width="{SCATTER_SIZE}" '
        f'height="{SCATTER_SIZE}" viewBox="0 0 {SCATTER_SIZE} {SCATTER_SIZE}" role="img" '
        f'aria-label="Stated confidence against observed hit rate, one marker per claim">'
        f"{''.join(parts)}</svg>"
    )
