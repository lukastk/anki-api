"""Shared test fixtures.

Tests run the app in-process via Starlette's TestClient (no uvicorn/port):
the TestClient context manager triggers the lifespan, which opens a fresh
throwaway collection per test, so every test is isolated and order-independent.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from anki_api.app import create_app
from anki_api.collection_handle import CollectionHandle
from anki_api.config import Settings


class V1Client:
    """Thin wrapper that prefixes /v1 and adds a few helpers for tests."""

    def __init__(self, client: TestClient) -> None:
        self._c = client

    def get(self, path: str, **kw):
        return self._c.get("/v1" + path, **kw)

    def post(self, path: str, **kw):
        return self._c.post("/v1" + path, **kw)

    def put(self, path: str, **kw):
        return self._c.put("/v1" + path, **kw)

    def delete(self, path: str, **kw):
        return self._c.delete("/v1" + path, **kw)

    # --- convenience builders used across e2e tests ---
    def make_deck(self, name: str = "T") -> str:
        return self.post("/decks", json={"name": name}).json()["id"]

    def make_note(self, deck: str = "T", front: str = "q", back: str = "a", tags=None) -> dict:
        r = self.post(
            "/notes",
            json={"deck": deck, "notetype": "Basic", "fields": {"Front": front, "Back": back}, "tags": tags or []},
        )
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(collection_path=str(tmp_path / "collection.anki2"))


@pytest.fixture
def api(settings: Settings) -> Iterator[V1Client]:
    app = create_app(settings)
    with TestClient(app) as client:
        yield V1Client(client)


@pytest.fixture
def handle(settings: Settings) -> Iterator[CollectionHandle]:
    h = CollectionHandle(settings)
    try:
        yield h
    finally:
        h.close()
