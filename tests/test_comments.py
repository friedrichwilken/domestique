import json
from pathlib import Path

import httpx
import pytest

from domestique import config
from domestique.claims.rules import SourceLayer
from domestique.ingest import icu, icu_client, icu_comments
from domestique.output import comments

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "evals" / "fixtures" / "icu_nutrition_comments.json").read_text()
)


class FakeIcu:
    """Holds an activity's comments; records every write. Never touches the network."""

    def __init__(self, messages):
        self.messages_by_activity = {"i2002": [dict(m) for m in messages]}
        self.posts = []

    def messages(self, activity_id):
        return [dict(m) for m in self.messages_by_activity.get(activity_id, [])]

    def post_message(self, activity_id, body):
        self.posts.append((activity_id, body))
        created = {"id": 900 + len(self.posts), "created": "2026-09-12T06:00:00Z", **body}
        self.messages_by_activity.setdefault(activity_id, []).append(created)
        return created


def load_cfg(tmp_path, extra=""):
    (tmp_path / "config.yaml").write_text(
        'athlete_id: "i000000"\ntimezone: "UTC"\nbedtime: "22:00"\n' + extra
    )
    return config.load({"DOMESTIQUE_HOME": str(tmp_path)})


SIXTH_INTERVAL = {"type": "WORK", "start_index": 3300, "end_index": 3600}


def interval_remark():
    return comments.Remark(
        statements=(
            comments.Statement("Power held within 2% of the first rep.", SourceLayer.OBSERVED),
            comments.Statement("You said the last reps felt the hardest.", SourceLayer.STATED),
            comments.Statement("Late-rep fade is common in this format.", SourceLayer.PRIOR),
        ),
        pin=comments.Pin.from_interval(SIXTH_INTERVAL),
    )


# --- 2.1 comments in ---------------------------------------------------------


def test_pinned_comment_keeps_both_indices():
    row = icu_comments.map_comment(FIXTURE["messages"][1], "iX", 7)
    assert (row["start_index"], row["end_index"]) == (3600, 4200)
    assert row["external_id"] == "502"
    assert row["activity_id"] == 7
    assert row["author_name"] == "Synthetic Athlete"
    assert row["ts"].utcoffset().total_seconds() == 0


def test_unpinned_comment_has_null_indices():
    row = icu_comments.map_comment(FIXTURE["messages"][0], "iX", 7)
    assert (row["start_index"], row["end_index"]) == (None, None)


def test_comments_api_paths():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[] if request.method == "GET" else {"id": 1})

    api = icu_comments.CommentsApi(
        icu_client.make_client("k", transport=httpx.MockTransport(handler))
    )
    api.messages("i2002")
    api.post_message("i2002", {"content": "x", "start_index": 1, "end_index": 2})
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", "/api/v1/activity/i2002/messages"),
        ("POST", "/api/v1/activity/i2002/messages"),
    ]
    assert json.loads(seen[1].content) == {"content": "x", "start_index": 1, "end_index": 2}


# --- 3.1 write switch --------------------------------------------------------


def test_write_comments_defaults_to_false(tmp_path):
    assert load_cfg(tmp_path).write_comments is False


def test_write_comments_must_be_boolean(tmp_path):
    with pytest.raises(TypeError, match="write_comments"):
        load_cfg(tmp_path, 'write_comments: "yes"\n')


def test_default_configuration_posts_nothing(tmp_path):
    fake = FakeIcu(FIXTURE["messages"])
    bodies = comments.write_debrief(load_cfg(tmp_path), fake, "i2002", [interval_remark()])
    assert fake.posts == []
    assert len(bodies) == 1
    assert bodies[0]["content"].startswith(comments.SYSTEM_MARKER)


# --- 3.2 comment writer ------------------------------------------------------


def test_interval_remark_is_pinned_and_labelled(tmp_path):
    fake = FakeIcu([])
    cfg = load_cfg(tmp_path, "write_comments: true\n")
    comments.write_debrief(cfg, fake, "i2002", [interval_remark()])
    [(activity_id, body)] = fake.posts
    assert activity_id == "i2002"
    assert (body["start_index"], body["end_index"]) == (3300, 3600)
    lines = body["content"].splitlines()
    assert lines[0] == comments.SYSTEM_MARKER
    assert lines[1:] == [
        "- (your data shows) Power held within 2% of the first rep.",
        "- (you told me) You said the last reps felt the hardest.",
        "- (the literature says) Late-rep fade is common in this format.",
    ]


def test_unpinned_remark_has_no_indices():
    remark = comments.Remark((comments.Statement("Steady ride.", SourceLayer.OBSERVED),))
    assert comments.body(remark) == {"content": "[domestique]\n- (your data shows) Steady ride."}


def test_every_layer_has_a_label():
    assert set(comments.LAYER_LABEL) == set(SourceLayer)


def test_remark_without_statements_is_refused():
    with pytest.raises(ValueError, match="statement"):
        comments.Remark(())


def test_athlete_comment_present_is_unchanged_and_system_comment_identifiable(tmp_path):
    fake = FakeIcu(FIXTURE["messages"])
    before = fake.messages("i2002")
    cfg = load_cfg(tmp_path, "write_comments: true\n")
    comments.write_debrief(cfg, fake, "i2002", [interval_remark()])
    after = fake.messages("i2002")
    assert after[: len(before)] == before
    rows = [icu_comments.map_comment(m, "iX", 7) for m in after]
    assert [r["is_system"] for r in rows] == [False, False, True]
    assert "system" in rows[-1]["tags"]
    assert not comments.is_system_comment(before[0]["content"])


# --- CLI settings: config first, environment overrides -----------------------


def test_cli_settings_from_config(tmp_path):
    (tmp_path / "config.yaml").write_text(
        'athlete_id: "i000000"\ntimezone: "UTC"\nbedtime: "22:00"\n'
        'database_url: "postgresql://cfg/db"\n'
    )
    env = {"DOMESTIQUE_HOME": str(tmp_path)}
    assert icu.cli_settings(env) == ("i000000", "postgresql://cfg/db")


def test_cli_settings_environment_overrides(tmp_path):
    (tmp_path / "config.yaml").write_text(
        'athlete_id: "i000000"\ntimezone: "UTC"\nbedtime: "22:00"\n'
        'database_url: "postgresql://cfg/db"\n'
    )
    env = {"DOMESTIQUE_HOME": str(tmp_path), "ICU_ATHLETE_ID": "i999"}
    assert icu.cli_settings(env) == ("i999", "postgresql://cfg/db")


def test_cli_settings_environment_alone_needs_no_config(tmp_path):
    env = {
        "DOMESTIQUE_HOME": str(tmp_path),
        "ICU_ATHLETE_ID": "i999",
        "DOMESTIQUE_DSN": "postgresql://env/db",
    }
    assert icu.cli_settings(env) == ("i999", "postgresql://env/db")


def test_cli_settings_without_config_or_env_names_the_path(tmp_path):
    with pytest.raises(FileNotFoundError, match=str(tmp_path)):
        icu.cli_settings({"DOMESTIQUE_HOME": str(tmp_path)})
