"""chat-layer 2.1: the mode prompt is the skill file, behind a short config prefix."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from domestique.chat.modes import (
    MODES,
    ModeContext,
    context_for,
    describe,
    load_mode,
    prefix,
    skills_dir,
)

ROOT = Path(__file__).resolve().parents[1]
CTX = ModeContext(date(2026, 3, 2), "Europe/Berlin", "athlete-synth-1")


@pytest.mark.parametrize("name", MODES)
def test_prompt_ends_with_the_file_and_starts_with_the_prefix(name):
    mode = load_mode(name, CTX)
    content = (ROOT / "skills" / f"{name}.md").read_text(encoding="utf-8")
    assert mode.system.endswith(content)
    assert mode.system.startswith(prefix(CTX))
    assert mode.system == prefix(CTX) + content
    assert mode.name == name


def test_prefix_carries_date_timezone_and_athlete_id_only():
    assert (
        prefix(CTX) == "Date: 2026-03-02\nTimezone: Europe/Berlin\nAthlete id: athlete-synth-1\n\n"
    )


def test_every_mode_has_a_skill_file_and_unknown_modes_are_refused():
    assert sorted(p.stem for p in (ROOT / "skills").glob("*.md")) == sorted(MODES)
    with pytest.raises(ValueError, match="unknown mode"):
        load_mode("free-chat", CTX)


def test_skills_dir_override_and_today_in_the_athletes_timezone(tmp_path):
    (tmp_path / "weekly-review.md").write_text("synthetic skill\n")
    assert load_mode("weekly-review", CTX, tmp_path).system.endswith("synthetic skill\n")
    assert skills_dir({"DOMESTIQUE_SKILLS_DIR": str(tmp_path)}) == tmp_path
    late = datetime(2026, 3, 2, 23, 30, tzinfo=UTC)  # already the 3rd in Berlin
    assert context_for("a", "Europe/Berlin", late).today == date(2026, 3, 3)


def test_description_is_the_skill_files_first_paragraph(tmp_path):
    (tmp_path / "weekly-review.md").write_text(
        "# weekly-review\n\nRuns once\na week.\n\n## Inputs\n"
    )
    assert describe("weekly-review", tmp_path) == "Runs once a week."
    assert all(describe(name) for name in MODES)
