from pathlib import Path

import pytest

from domestique import config

REPO = Path(__file__).resolve().parents[1]


def test_example_config_loads_from_a_custom_home(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text((REPO / "examples" / "config.yaml").read_text())
    cfg = config.load({"DOMESTIQUE_HOME": str(tmp_path)})
    assert cfg.athlete_id == "i000000"
    assert cfg.bedtime == "22:30"
    assert cfg.baselines["hrv"] == 80.0


def test_missing_config_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=str(tmp_path)):
        config.load({"DOMESTIQUE_HOME": str(tmp_path)})


def test_missing_required_field(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("athlete_id: x\n")
    with pytest.raises(ValueError, match="timezone"):
        config.load({"DOMESTIQUE_HOME": str(tmp_path)})


def test_repo_contains_no_real_intent_files() -> None:
    assert not (REPO / "intent").exists()
