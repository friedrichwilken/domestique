"""chat-layer 2.4: the Chainlit wiring imports and offers one profile per mode."""

import asyncio
import importlib
import os

import pytest

from domestique.chat.modes import MODES, describe


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # chainlit writes its config directory under CHAINLIT_APP_ROOT at import time
    root = tmp_path_factory.mktemp("chainlit")
    previous = os.environ.get("CHAINLIT_APP_ROOT")
    os.environ["CHAINLIT_APP_ROOT"] = str(root)
    try:
        yield importlib.import_module("domestique.chat.app")
    finally:
        if previous is None:
            os.environ.pop("CHAINLIT_APP_ROOT", None)
        else:
            os.environ["CHAINLIT_APP_ROOT"] = previous


def test_one_chat_profile_per_mode_described_by_its_skill_file(app):
    profiles = asyncio.run(app.chat_profiles(None))
    assert [p.name for p in profiles] == list(MODES)
    assert [p.markdown_description for p in profiles] == [describe(m) for m in MODES]
    assert [p.default for p in profiles] == [True, False, False, False]


def test_only_the_weekly_review_runs_the_summary_pass(app):
    assert sorted(app.SUMMARY_MODES) == ["weekly-review"]
