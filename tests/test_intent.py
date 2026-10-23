import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from domestique import intent
from domestique.intent import IntentError, Override, append_override, load_intent

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def intent_dir(tmp_path: Path) -> Path:
    target = tmp_path / "intent"
    shutil.copytree(EXAMPLES / "intent", target)
    return target


def test_example_intent_loads(intent_dir):
    loaded = load_intent(intent_dir)
    assert [g.id for g in loaded.goals] == ["ftp-target", "a-race"]
    assert {r.action for r in loaded.rails} == {
        "stop_plan",
        "downgrade_day",
        "refuse_additional_load",
        "no_intensity",
    }
    assert loaded.overrides[0].prediction_at_time == {"next_morning_hrv": 65, "sleep_h": 6.5}


def test_loads_through_config(tmp_path, intent_dir):
    (tmp_path / "config.yaml").write_text(
        f"athlete_id: x\ntimezone: UTC\nbedtime: '22:00'\nintent_dir: {intent_dir}\n"
    )
    loaded = intent.load_intent_from_config({"DOMESTIQUE_HOME": str(tmp_path)})
    assert len(loaded.constraints) == 3


def test_missing_set_by_names_file_and_field(intent_dir):
    goals = yaml.safe_load((intent_dir / "goals.yaml").read_text())
    del goals[0]["set_by"]
    (intent_dir / "goals.yaml").write_text(yaml.safe_dump(goals))
    with pytest.raises(IntentError, match=r"goals\.yaml.*set_by"):
        load_intent(intent_dir)


def test_unknown_field_and_bad_action_are_rejected(intent_dir):
    (intent_dir / "rails.yaml").write_text("- id: x\n  trigger: t\n  action: shrug\n")
    with pytest.raises(IntentError, match=r"rails\.yaml.*action"):
        load_intent(intent_dir)
    (intent_dir / "rails.yaml").write_text("- id: x\n  trigger: t\n  action: stop_plan\n  y: 1\n")
    with pytest.raises(IntentError, match=r"rails\.yaml.*'y'"):
        load_intent(intent_dir)


def test_missing_files_load_empty(tmp_path):
    loaded = load_intent(tmp_path)
    assert loaded.goals == loaded.constraints == loaded.overrides == loaded.rails == ()


def test_append_override_keeps_existing_entries(intent_dir):
    before = {p.name: p.read_bytes() for p in intent_dir.iterdir()}
    existing = load_intent(intent_dir).overrides
    new = Override(
        ts=date(2026, 10, 20),
        by="athlete",
        text="Rode the long session as planned despite the low readiness call",
        overruled="Suggestion to shorten the long session",
        prediction_at_time={"next_morning_hrv": 58, "sleep_h": 7.0},
    )
    append_override(intent_dir, new)
    after = (intent_dir / "overrides.yaml").read_bytes()
    assert after.startswith(before["overrides.yaml"])
    loaded = load_intent(intent_dir).overrides
    assert loaded[: len(existing)] == existing
    assert loaded[-1] == new
    assert loaded[-1].prediction_at_time == {"next_morning_hrv": 58, "sleep_h": 7.0}
    for name in ("goals.yaml", "constraints.yaml", "rails.yaml"):
        assert (intent_dir / name).read_bytes() == before[name]


def test_append_override_creates_file(tmp_path):
    entry = Override(ts=date(2026, 10, 20), by="athlete", text="t", overruled="o")
    append_override(tmp_path, entry)
    assert load_intent(tmp_path).overrides == (entry,)


def test_append_refuses_on_invalid_overrides(intent_dir):
    (intent_dir / "overrides.yaml").write_text("- by: athlete\n")
    entry = Override(ts=date(2026, 10, 20), by="athlete", text="t", overruled="o")
    with pytest.raises(IntentError, match=r"overrides\.yaml"):
        append_override(intent_dir, entry)
    assert (intent_dir / "overrides.yaml").read_text() == "- by: athlete\n"
