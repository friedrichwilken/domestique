"""intervals.icu API client.

Thin client over the public intervals.icu API (adapted from the author's earlier helper,
docs/stack.md). Changes: the athlete id comes from configuration instead of
being hardcoded, errors raise instead of exiting, and the API key is read
from ICU_API_KEY first, then ~/.icu_api_key. The key is never stored here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://intervals.icu"

# A JSON object exactly as intervals.icu returns it: the external-API boundary.
type IcuPayload = dict[str, Any]


class MissingCredentialsError(RuntimeError):
    pass


def get_api_key() -> str:
    key = os.environ.get("ICU_API_KEY", "").strip()
    if key:
        return key
    key_file = Path.home() / ".icu_api_key"
    if key_file.exists():
        return key_file.read_text().strip()
    raise MissingCredentialsError(
        "No intervals.icu API key. Set ICU_API_KEY or write it to ~/.icu_api_key "
        "(intervals.icu -> Settings -> Developer Settings)."
    )


def get_athlete_id() -> str:
    athlete_id = os.environ.get("ICU_ATHLETE_ID", "").strip()
    if not athlete_id:
        raise MissingCredentialsError(
            "Set ICU_ATHLETE_ID (e.g. i12345, see the intervals.icu URL)."
        )
    return athlete_id


def make_client(
    api_key: str | None = None, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        auth=("API_KEY", api_key or get_api_key()),
        timeout=30.0,
        headers={"Accept": "application/json"},
        transport=transport,
    )


class IcuClient:
    """Thin wrapper over the three endpoints the ingest needs."""

    def __init__(self, athlete_id: str, http: httpx.Client) -> None:
        self.athlete_id = athlete_id
        self.http = http

    def _get(self, path: str, **params: str | None) -> Any:
        r = self.http.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    def activities(self, oldest: str, newest: str) -> list[IcuPayload]:
        rows: list[IcuPayload] = self._get(
            f"/api/v1/athlete/{self.athlete_id}/activities", oldest=oldest, newest=newest
        )
        return rows

    def intervals(self, activity_id: str) -> IcuPayload | list[IcuPayload]:
        payload: IcuPayload | list[IcuPayload] = self._get(
            f"/api/v1/activity/{activity_id}/intervals"
        )
        return payload

    def streams(self, activity_id: str, types: str) -> list[IcuPayload]:
        rows: list[IcuPayload] = self._get(f"/api/v1/activity/{activity_id}/streams", types=types)
        return rows

    def wellness(self, oldest: str, newest: str) -> list[IcuPayload]:
        rows: list[IcuPayload] = self._get(
            f"/api/v1/athlete/{self.athlete_id}/wellness", oldest=oldest, newest=newest
        )
        return rows
