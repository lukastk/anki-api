"""Sync [parity] — drive sync against a real self-hosted anki.syncserver over HTTP.

AnkiWeb uses the identical client path (endpoint=null); it just can't be tested
here without real credentials.
"""

import os
import socket
import stat
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from anki_api.app import create_app
from anki_api.collection_handle import CollectionHandle
from anki_api.config import Settings
from anki_api.routers import sync as sync_router

HOST, PORT = "127.0.0.1", 28117
ENDPOINT = f"http://{HOST}:{PORT}/"
USER, PASS = "tester", "secret"


def _wait_for_port(timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.5)
            try:
                s.connect((HOST, PORT))
                return
            except OSError:
                time.sleep(0.2)
    raise RuntimeError("sync server did not start")


@pytest.fixture
def sync_server(tmp_path):
    import os

    env = dict(os.environ)
    env.update(SYNC_USER1=f"{USER}:{PASS}", SYNC_BASE=str(tmp_path / "syncbase"),
               SYNC_HOST=HOST, SYNC_PORT=str(PORT))
    proc = subprocess.Popen([sys.executable, "-m", "anki.syncserver"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for_port()
        yield ENDPOINT
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_sync_requires_login(api):
    assert api.get("/sync/status").status_code == 401
    assert api.post("/sync", json={}).status_code == 401


def test_login_and_full_upload_then_in_sync(api, sync_server):
    api.make_note(deck="D", front="synced-note")

    login = api.post("/sync/login", json={"username": USER, "password": PASS, "endpoint": sync_server})
    assert login.status_code == 200
    assert login.json()["logged_in"] is True

    # fresh server -> a full sync is required
    assert api.get("/sync/status").json()["required"] == "full_sync"
    first = api.post("/sync", json={"sync_media": False}).json()
    assert first["required"] in ("full_upload", "full_sync")

    # push our collection up, then we should be fully in sync
    up = api.post("/sync/full-upload").json()
    assert up == {"ok": True, "direction": "upload"}
    assert api.post("/sync", json={"sync_media": False}).json()["required"] == "no_changes"

    # collection is still usable after the full-sync close/reopen
    assert api.get("/collection").json()["note_count"] == 1


def test_login_bad_credentials(api, sync_server):
    resp = api.post("/sync/login", json={"username": USER, "password": "wrong", "endpoint": sync_server})
    assert resp.status_code == 502
    assert resp.json()["error"] in ("sync_error", "network_error")


# --- persistence + auto-login + autosync ---

def test_sync_auth_persists_across_restart(settings, sync_server):
    app1 = create_app(settings)
    with TestClient(app1) as c1:
        assert c1.post("/v1/sync/login", json={
            "username": USER, "password": PASS, "endpoint": sync_server}).status_code == 200
    assert os.path.exists(settings.resolved_sync_auth_path)

    # a fresh process (same settings) loads the token from disk — no re-login
    app2 = create_app(settings)
    with TestClient(app2) as c2:
        assert c2.get("/v1/sync/status").status_code == 200


def test_logout_clears_persisted_auth(settings, sync_server):
    app = create_app(settings)
    with TestClient(app) as c:
        c.post("/v1/sync/login", json={"username": USER, "password": PASS, "endpoint": sync_server})
        assert os.path.exists(settings.resolved_sync_auth_path)
        c.post("/v1/sync/logout")
        assert not os.path.exists(settings.resolved_sync_auth_path)
        assert c.get("/v1/sync/status").status_code == 401


def test_auth_file_is_0600(settings, sync_server):
    app = create_app(settings)
    with TestClient(app) as c:
        c.post("/v1/sync/login", json={"username": USER, "password": PASS, "endpoint": sync_server})
    mode = stat.S_IMODE(os.stat(settings.resolved_sync_auth_path).st_mode)
    assert mode == 0o600


def _creds_settings(tmp_path, endpoint) -> Settings:
    return Settings(
        collection_path=str(tmp_path / "collection.anki2"),
        sync_username=USER, sync_password=PASS, sync_endpoint=endpoint,
    )


def test_auto_login_from_credentials_on_startup(tmp_path, sync_server):
    """With creds configured and no persisted token, the server logs in on boot."""
    app = create_app(_creds_settings(tmp_path, sync_server))
    with TestClient(app) as c:
        assert c.get("/v1/sync/status").status_code == 200  # authed without explicit /login


def test_run_autosync_logs_in_and_runs(tmp_path, sync_server):
    handle = CollectionHandle(_creds_settings(tmp_path, sync_server))
    try:
        result = sync_router.run_autosync(handle)
        assert "skipped" not in result  # creds present -> it logged in and synced
        assert handle.sync_auth is not None
        # fresh server -> a full sync is required (and left for manual direction)
        assert result["required"] in ("full_upload", "full_sync", "no_changes", "normal_sync")
    finally:
        handle.close()
