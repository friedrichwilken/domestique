"""web-console 1.2: the app service publishes on loopback only and mounts config read-only."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _app_raw():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["app"]


def test_compose_file_declares_loopback_port_and_read_only_config():
    app = _app_raw()
    assert app["ports"] == ["127.0.0.1:${DOMESTIQUE_WEB_PORT:-8000}:8000"]
    assert app["volumes"] == ["${DOMESTIQUE_HOME:-~/.config/domestique}:/config:ro"]
    env = app["environment"]
    assert env["DOMESTIQUE_HOME"] == "/config"
    assert env["DOMESTIQUE_DSN"].endswith("@db:5432/domestique")
    assert env["ICU_API_KEY"] is None and env["DOMESTIQUE_HUMAN_TOKEN"] is None  # pass-through
    assert app["depends_on"] == {"db": {"condition": "service_healthy"}}


def _rendered():
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker not installed")
    done = subprocess.run(
        [docker, "compose", "config", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("docker compose plugin not installed")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["services"]["app"]


def test_rendered_compose_publishes_on_loopback_only_and_mounts_read_only():
    app = _rendered()
    assert [p["host_ip"] for p in app["ports"]] == ["127.0.0.1"]
    assert [p["target"] for p in app["ports"]] == [8000]
    (volume,) = app["volumes"]
    assert volume["target"] == "/config" and volume["read_only"] is True
