"""web-console 1.1, 2.2, 2.3: routes through the test client, the page, the replay page."""

import html
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domestique.claims.seed import read_seed
from domestique.replay.fixture import FixtureSeason
from domestique.replay.harness import run_replay
from domestique.replay.run import main
from domestique.web.app import WebSettings, create_app
from domestique.web.pages import CANNOT_LEARN, claims_page
from domestique.web.queries import ClaimReport, PredictionRow, ReportData, from_replay

ROOT = Path(__file__).resolve().parents[1]
PRIORS = ROOT / "evals/priors.yaml"
DAY = date(2026, 3, 2)


def pred(i, actual, official=True):
    return PredictionRow(DAY + timedelta(days=i), "peak_hr", 90.0, 110.0, 100.0, actual, official)


def claim(cid, preds, **kw):
    fields = {
        "id": cid,
        "text": f"synthetic claim {cid}",
        "source_layer": "prior",
        "horizon": "day",
        "confidence": 0.4,
        "status": "active",
        "scored": len(preds),
        "hits": sum(p.hit for p in preds),
        "calib_scored": len(preds),
        "calib_hits": sum(p.hit for p in preds),
        "calib_abs_error": 0.0,
        "calib_half_range": 0.0,
        "uninformative": False,
        "overconfident": False,
        "predictions": tuple(preds),
    }
    fields.update(kw)
    return ClaimReport(**fields)


REPORT = ReportData(
    "athlete-synth-1",
    (
        claim("a", [pred(0, 100.0), pred(1, 125.0), pred(2, 101.0, official=False)]),
        claim(
            "b",
            [pred(i, 100.0) for i in range(12)],
            uninformative=True,
            calib_abs_error=12.0,
            calib_half_range=120.0,
        ),
        claim("c", [], status="candidate"),
    ),
)


@pytest.fixture
def client():
    app = create_app(
        WebSettings("athlete-synth-1", None),
        report=lambda: REPORT,
        day=lambda d: pytest.fail("not used"),
        store=lambda: pytest.fail("not used"),
    )
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_claims_json_carries_every_prediction_and_the_derived_numbers(client):
    body = client.get("/claims.json").json()
    assert body["athlete_id"] == "athlete-synth-1"
    by_id = {c["id"]: c for c in body["claims"]}
    assert len(by_id["a"]["predictions"]) == 3
    assert by_id["a"]["predictions"][1] == {
        "day": "2026-03-03",
        "metric": "peak_hr",
        "low": 90.0,
        "high": 110.0,
        "expected": 100.0,
        "actual": 125.0,
        "official": True,
        "hit": False,
    }
    assert by_id["b"]["error_share"] == pytest.approx(0.1)
    assert by_id["c"]["hit_rate"] is None


def test_page_has_one_row_and_one_strip_per_claim(client):
    page = client.get("/claims").text
    assert page.count('<tr class="claim"') == 3
    assert page.count('<svg class="strip"') == 3
    assert page.count('<svg class="scatter"') == 1


def test_flagged_claim_shows_flag_and_error_share_in_its_row(client):
    page = client.get("/claims").text
    row = re.search(r'<tr class="claim" id="row-b">.*?</tr>', page, re.S).group(0)
    assert '<span class="flag">uninformative</span>' in row and ">0.10<" in row


def test_shadows_query_hides_shadow_markers(client):
    assert client.get("/claims").text.count('data-shadow="1"') == 1
    hidden = client.get("/claims", params={"shadows": 0}).text
    assert 'data-shadow="1"' not in hidden
    assert hidden.count('<tr class="claim"') == 3


def test_footer_quotes_design_md_verbatim():
    design = " ".join((ROOT / "DESIGN.md").read_text().split())
    page = html.unescape(claims_page(REPORT))
    footer = page[page.index("<footer>") :]
    for title, sentence in CANNOT_LEARN:
        assert f"**{title}** {sentence}" in design
        assert title in footer and sentence in footer


def test_renderer_is_the_same_for_both_sources():
    result = run_replay(FixtureSeason(ROOT / "evals/fixtures/season_a"), read_seed(PRIORS))
    data = from_replay(result)
    assert len(data.claims) == len(read_seed(PRIORS).claims)
    assert sum(len(c.predictions) for c in data.claims) == len(result.scored) + len(
        result.shadow_scored
    )
    for c in data.claims:
        assert c.predictions == tuple(sorted(c.predictions, key=lambda p: (p.day, p.metric)))
    page = claims_page(data)
    assert page.count('<tr class="claim"') == len(data.claims)


def test_replay_html_writes_the_fixture_page(tmp_path, capsys):
    out = tmp_path / "claims.html"
    written = main(["--out", str(tmp_path), "--html", str(out)], repo=ROOT)
    page = out.read_text()
    assert page.count('<tr class="claim"') == len(read_seed(PRIORS).claims)
    assert out in written.files
    printed = capsys.readouterr().out.strip().splitlines()
    assert f"wrote {out}" in printed and printed[-1].startswith("Headline:")
