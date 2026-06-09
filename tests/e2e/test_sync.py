"""Sync [parity] — drive sync against a real self-hosted anki.syncserver over HTTP.

AnkiWeb uses the identical client path (endpoint=null); it just can't be tested
here without real credentials.
"""

import socket
import subprocess
import sys
import time

import pytest

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
