from datetime import UTC, date, datetime

from domestique.claims.rules import Horizon, SourceLayer, Status
from domestique.claims.store import Claim
from domestique.intent import Constraint
from domestique.intent.conflicts import conflicts
from domestique.loop.model import Binding, Metric

TS = datetime(2026, 9, 1, tzinfo=UTC)


def claim(cid, text, layer=SourceLayer.OBSERVED, status=Status.ACTIVE, confidence=0.6):
    return Claim(
        id=cid,
        athlete_id="iT0000",
        text=text,
        source_layer=layer,
        horizon=Horizon.DAY,
        confidence=confidence,
        status=status,
        created_by="test",
        created_at=TS,
    )


CONSTRAINT = Constraint(
    id="work-hr-cap",
    text="Work intervals stay under 85% of max heart rate",
    set_by="athlete",
    set_on=date(2026, 9, 1),
    tags=("peak_hr",),
)


def test_observed_tolerance_vs_stated_constraint():
    tolerance = claim("c-obs", "Tolerates work HR up to 92% of max")
    rows = conflicts([CONSTRAINT], [tolerance], [Binding("c-obs", Metric.PEAK_HR, range_abs=5.0)])
    assert len(rows) == 1
    row = rows[0]
    assert row.winner == "constraint"
    assert row.constraint is CONSTRAINT
    assert row.claim_id == "c-obs"
    assert row.claim_source_layer == "observed"
    assert row.claim_confidence == 0.6
    assert row.metrics == ("peak_hr",)
    assert "work-hr-cap" in row.wording
    assert "observed" in row.wording
    assert "constraint applies" in row.wording


def test_text_alone_never_links():
    same_words = claim("c-txt", "Work intervals under 85% of max heart rate")
    rows = conflicts(
        [CONSTRAINT], [same_words], [Binding("c-txt", Metric.SLEEP_HOURS, range_abs=0.5)]
    )
    assert rows == []


def test_inactive_claims_and_untagged_constraints_are_quiet():
    retired = claim("c-old", "Tolerates work HR up to 95% of max", status=Status.RETIRED)
    untagged = Constraint(id="hours", value=8, set_by="athlete")
    bindings = [
        Binding("c-old", Metric.PEAK_HR, range_abs=5.0),
        Binding("c-new", Metric.PEAK_HR, range_abs=5.0),
    ]
    fresh = claim("c-new", "Peak HR runs high outdoors", layer=SourceLayer.PRIOR)
    rows = conflicts([CONSTRAINT, untagged], [retired, fresh], bindings)
    assert [(r.constraint.id, r.claim_id, r.claim_source_layer) for r in rows] == [
        ("work-hr-cap", "c-new", "prior")
    ]
