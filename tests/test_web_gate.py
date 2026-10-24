"""web-console 3.2: the human gate as a form, over an injected store."""

import re
from contextlib import contextmanager
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from domestique.claims.store import MemoryStore
from domestique.web.app import DECIDED_BY, WebSettings, create_app
from domestique.web.pages import claims_page
from domestique.web.queries import ReportData, claim_report

ATHLETE = "iTest"
TOKEN = "synthetic-token"


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("DOMESTIQUE_HUMAN_TOKEN", TOKEN)
    return MemoryStore()


@pytest.fixture
def client(store):
    @contextmanager
    def provide():
        yield store

    def report():
        return ReportData(ATHLETE, tuple(claim_report(c, ()) for c in store.query_claims()))

    app = create_app(
        WebSettings(ATHLETE, None),
        report=report,
        day=lambda d: pytest.fail("not used"),
        store=provide,
    )
    with TestClient(app) as c:
        yield c


def candidate(store):
    return store.propose_claim(ATHLETE, "synthetic claim", "prior", "day", [], "test")


def test_correct_token_confirms_a_candidate_and_history_carries_reason_and_by(client, store):
    c = candidate(store)
    r = client.post(
        f"/claims/{c.id}/decide",
        data={"status": "active", "reason": "held up at review", "token": TOKEN},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == f"/claims#row-{c.id}"
    assert store.query_claims()[0].status == "active"
    last = store.history(c.id)[-1]
    assert (last.reason, last.by, last.status) == ("held up at review", DECIDED_BY, "active")


@pytest.mark.parametrize("token", ["wrong", ""])
def test_wrong_or_missing_token_is_403_and_writes_nothing(client, store, token):
    c = candidate(store)
    before = store.history(c.id)
    r = client.post(
        f"/claims/{c.id}/decide", data={"status": "retired", "reason": "r", "token": token}
    )
    assert r.status_code == 403
    assert store.query_claims()[0].status == "candidate"
    assert store.history(c.id) == before


def test_closed_gate_when_the_token_is_not_set(client, store, monkeypatch):
    monkeypatch.delenv("DOMESTIQUE_HUMAN_TOKEN")
    c = candidate(store)
    r = client.post(f"/claims/{c.id}/decide", data={"status": "active", "reason": "r"})
    assert r.status_code == 403 and store.query_claims()[0].status == "candidate"


def test_token_outside_the_form_body_is_not_accepted(client, store):
    c = candidate(store)
    path = f"/claims/{c.id}/decide"
    assert client.get(path, params={"token": TOKEN}).status_code == 405
    r = client.post(
        path, params={"token": TOKEN}, data={"status": "active", "reason": "r"}
    )  # query string
    assert r.status_code == 403
    client.cookies.set("token", TOKEN)
    assert client.post(path, data={"status": "active", "reason": "r"}).status_code == 403
    assert store.query_claims()[0].status == "candidate"


def test_bad_status_empty_reason_and_unknown_claim(client, store):
    c = candidate(store)
    path = f"/claims/{c.id}/decide"
    assert (
        client.post(path, data={"status": "candidate", "reason": "r", "token": TOKEN}).status_code
        == 400
    )
    assert (
        client.post(path, data={"status": "active", "reason": " ", "token": TOKEN}).status_code
        == 400
    )
    missing = {"status": "active", "reason": "r", "token": TOKEN}
    assert client.post("/claims/nope/decide", data=missing).status_code == 404
    assert store.query_claims()[0].status == "candidate"


def test_clear_flags_through_the_form(client, store):
    c = candidate(store)
    store.record_adjustment(replace(c, uninformative=True, calib_scored=12), "flagged", "test")
    path = f"/claims/{c.id}/clear-flags"
    assert client.post(path, data={"reason": "range narrowed", "token": "wrong"}).status_code == 403
    assert store.query_claims()[0].uninformative is True
    r = client.post(path, data={"reason": "range narrowed", "token": TOKEN}, follow_redirects=False)
    assert r.status_code == 303
    cleared = store.query_claims()[0]
    assert cleared.uninformative is False and cleared.calib_scored == 0
    last = store.history(c.id)[-1]
    assert last.by == DECIDED_BY and last.reason.endswith("range narrowed")
    assert client.get(path).status_code == 405


def _row(page, cid):
    return re.search(rf'<tr class="claim" id="row-{cid}">.*?</tr>', page, re.S).group(0)


def test_page_has_a_decide_form_per_candidate_and_a_clear_form_per_flagged_row(store):
    cand = candidate(store)
    act = store.confirm_or_retire(candidate(store).id, "active", "r", "test")
    flagged = store.record_adjustment(replace(act, overconfident=True), "flagged", "test")
    data = ReportData(ATHLETE, tuple(claim_report(c, ()) for c in store.query_claims()))
    page = claims_page(data)
    row = _row(page, cand.id)
    assert f'action="/claims/{cand.id}/decide"' in row and 'method="post"' in row
    assert 'name="token" type="password"' in row and "clear-flags" not in row
    row = _row(page, flagged.id)
    assert f'action="/claims/{flagged.id}/clear-flags"' in row and "/decide" not in row
    assert page.count('type="password"') == 2
