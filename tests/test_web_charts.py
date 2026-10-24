"""web-console 2.1: table rows and SVG charts from a synthetic ReportData."""

import re
from datetime import date, timedelta

from domestique.web.charts import calibration_strip, claims_table, confidence_vs_hit_rate
from domestique.web.queries import ClaimReport, PredictionRow, ReportData

DAY = date(2026, 3, 2)


def pred(i, actual, low=90.0, high=110.0, official=True, metric="peak_hr"):
    return PredictionRow(
        day=DAY + timedelta(days=i),
        metric=metric,
        low=low,
        high=high,
        expected=(low + high) / 2,
        actual=actual,
        official=official,
    )


def claim(cid="c1", preds=(), confidence=0.5, scored=None, hits=None, **kw):
    n = len(preds) if scored is None else scored
    h = sum(p.hit for p in preds) if hits is None else hits
    fields = {
        "id": cid,
        "text": f"claim {cid}",
        "source_layer": "observed",
        "horizon": "day",
        "confidence": confidence,
        "status": "active",
        "scored": n,
        "hits": h,
        "calib_scored": n,
        "calib_hits": h,
        "calib_abs_error": 0.0,
        "calib_half_range": 0.0,
        "uninformative": False,
        "overconfident": False,
        "predictions": tuple(preds),
    }
    fields.update(kw)
    return ClaimReport(**fields)


def count(svg, pattern):
    return len(re.findall(pattern, svg))


# --- claims table ----------------------------------------------------------------


def test_flagged_row_shows_the_flag_and_the_share_that_caused_it():
    flagged = claim(
        "u",
        [pred(i, 100.0) for i in range(12)],
        uninformative=True,
        calib_abs_error=24.0,
        calib_half_range=120.0,
    )
    (row,) = claims_table(ReportData("synthetic", (flagged,)))
    assert row.flags == ("uninformative",)
    assert row.error_share == "0.20"
    assert row.hit_rate == "100%" and row.scored == "12"


def test_unscored_row_reads_not_available():
    (row,) = claims_table(ReportData("synthetic", (claim("x"),)))
    assert (row.hit_rate, row.error_share, row.flags) == ("n/a", "n/a", ())


# --- calibration strip -----------------------------------------------------------


def test_miss_renders_a_hollow_marker_and_a_label():
    preds = [pred(0, 100.0), pred(1, 115.0), pred(2, 85.5)]
    svg = calibration_strip(claim("c", preds), preds)
    assert count(svg, r'<rect class="band"') == 3
    assert count(svg, r'<circle class="hit"[^>]*fill="currentColor"') == 1
    assert count(svg, r'<circle class="miss"[^>]*fill="none"') == 2
    labels = re.findall(r'<text class="miss-label"[^>]*>([^<]*)</text>', svg)
    assert labels == ["+5", "-4.5"]  # signed distance to the range, not to the expectation


def test_strip_truncates_to_the_last_sixty_and_says_so():
    preds = [pred(i, 100.0 + i % 3) for i in range(75)]
    svg = calibration_strip(claim("c", preds), preds)
    assert count(svg, r'<g class="pred"') == 60
    assert "15 earlier omitted" in svg
    assert DAY.isoformat() not in svg  # the oldest is gone
    assert (DAY + timedelta(days=74)).isoformat() in svg  # the newest is drawn


def test_no_omission_note_at_sixty_or_fewer():
    preds = [pred(i, 100.0) for i in range(60)]
    svg = calibration_strip(claim("c", preds), preds)
    assert count(svg, r'<g class="pred"') == 60 and "omitted" not in svg


def test_shadows_are_lighter_and_can_be_left_out():
    preds = [pred(0, 100.0), pred(1, 100.0, official=False), pred(2, 120.0, official=False)]
    svg = calibration_strip(claim("c", preds), preds)
    assert count(svg, r'data-shadow="1" opacity="0\.35"') == 2
    hidden = calibration_strip(claim("c", preds), preds, shadows=False)
    assert 'data-shadow="1"' not in hidden and count(hidden, r'<g class="pred"') == 1


def test_each_metric_gets_its_own_lane():
    preds = [pred(0, 100.0), pred(1, 7.5, low=7.0, high=8.0, metric="sleep_hours")]
    svg = calibration_strip(claim("c", preds), preds)
    assert ">peak_hr</text>" in svg and ">sleep_hours</text>" in svg


def test_claim_text_is_escaped():
    preds = [pred(0, 100.0)]
    svg = calibration_strip(claim("c", preds, text="a <b> & c"), preds)
    assert "a &lt;b&gt; &amp; c" in svg and "<b>" not in svg


def test_strip_without_predictions_says_so():
    assert "no scored predictions yet" in calibration_strip(claim("c"), [])


# --- confidence against hit rate -------------------------------------------------


def _report():
    many = [pred(i, 100.0 if i % 4 else 130.0) for i in range(20)]
    few = [pred(i, 100.0) for i in range(3)]
    return ReportData(
        "synthetic",
        (
            claim("many", many, confidence=0.8),
            claim("few", few, confidence=0.3),
            claim("none", confidence=0.5),
        ),
    )


def test_scatter_omits_unscored_claims_and_labels_early_ones():
    svg = confidence_vs_hit_rate(_report())
    assert count(svg, r"<circle ") == 2
    assert count(svg, r">early</text>") == 1
    assert "claim none" not in svg  # unscored: in the table, not in the chart
    assert len(claims_table(_report())) == 3


def test_scatter_draws_the_diagonal_axes_labels_and_sizes_by_count():
    svg = confidence_vs_hit_rate(_report())
    assert count(svg, r'<line class="diagonal"') == 1
    assert "stated confidence" in svg and "observed hit rate" in svg
    radii = [float(r) for r in re.findall(r'<circle [^>]*r="([0-9.]+)"', svg)]
    assert radii[0] > radii[1]  # 20 scored against 3


def test_scatter_places_by_confidence_and_hit_rate():
    svg = confidence_vs_hit_rate(_report())
    (x, y) = re.findall(r'<circle cx="([0-9.]+)" cy="([0-9.]+)"', svg)[0]
    # many: confidence 0.8, hit rate 15/20 = 0.75 on a 360px plot with 48px padding
    assert float(x) == round(48 + 0.8 * 264, 1)
    assert float(y) == round(360 - 48 - 0.75 * 264, 1)
