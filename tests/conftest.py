import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "evals" / "fixtures"


def load_ride(name: str) -> dict:
    raw = json.loads((FIXTURES / f"{name}.json").read_text())
    keys = ("t_s", "watts", "hr", "cadence", "lr")
    raw["samples"] = [
        dict(zip(keys, row, strict=True)) for row in zip(*(raw[k] for k in keys), strict=True)
    ]
    return raw


@pytest.fixture(scope="session")
def endurance():
    return load_ride("endurance_3h")


@pytest.fixture(scope="session")
def intervals():
    return load_ride("intervals_6x5")
