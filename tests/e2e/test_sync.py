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


# --- sync health (local-only facts; no auth, no server contact) ---

def test_sync_health_never_synced(api):
    """Health needs no login and flags the never-synced state (the state that
    preceded the 2026-07-03 wipe: full-uploading such a collection overwrites
    unknown remote state)."""
    h = api.get("/sync/health").json()
    assert h["never_synced"] is True
    assert h["schema_changed"] is True  # scm > ls == 0
    assert h["logged_in"] is False
    assert int(h["collection_created"]) > 0
    assert int(api.get("/collection").json()["created"]) > 0


def test_new_fully_formed_notetype_stays_incremental(api, sync_server):
    """THE regression that keeps mysrs bootstraps from breaking sync: creating a
    brand-new notetype WITH extra fields must not flag a schema change."""
    api.post("/sync/login", json={"username": USER, "password": PASS, "endpoint": sync_server})
    api.post("/sync/full-upload")
    h = api.get("/sync/health").json()
    assert h["never_synced"] is False and h["schema_changed"] is False

    api.post("/notetypes", json={"name": "mysrs Basic", "fields": ["mysrs_id", "mysrs_source", "mysrs_meta"]})
    h = api.get("/sync/health").json()
    assert h["schema_changed"] is False, "fully-formed notetype creation must be incremental"
    assert api.post("/sync", json={"sync_media": False}).json()["required"] in ("no_changes", "normal_sync")


def test_add_field_to_existing_notetype_forces_full_sync(api, sync_server):
    """The counterpart: add_field on an EXISTING notetype modifies the schema —
    which is exactly why fully-formed creation matters."""
    api.post("/sync/login", json={"username": USER, "password": PASS, "endpoint": sync_server})
    api.post("/sync/full-upload")
    ntid = api.post("/notetypes", json={"name": "Grows"}).json()["id"]
    api.post("/sync", json={"sync_media": False})  # push the creation incrementally
    assert api.get("/sync/health").json()["schema_changed"] is False

    api.post(f"/notetypes/{ntid}/fields", json={"name": "Extra"})
    assert api.get("/sync/health").json()["schema_changed"] is True


# --- defensive backups (possession, not inference) ---

def test_backup_remote_requires_login(api):
    assert api.post("/sync/backup-remote").status_code == 401


def test_backup_remote_captures_server_state_without_touching_live(api, sync_server, settings):
    api.make_note(deck="D", front="precious-one")
    api.make_note(deck="D", front="precious-two")
    api.post("/sync/login", json={"username": USER, "password": PASS, "endpoint": sync_server})
    api.post("/sync/full-upload")

    mod_before = api.get("/collection").json()["modified"]
    out = api.post("/sync/backup-remote").json()
    assert out["note_count"] == 2
    assert out["card_count"] == 2
    assert os.path.exists(out["path"])
    assert os.path.basename(out["path"]).startswith("ankiweb-")
    # the live collection was never opened/closed/modified
    assert api.get("/collection").json()["modified"] == mod_before
    assert api.get("/collection").json()["note_count"] == 2


def test_backup_remote_prunes_old_backups(api, sync_server, settings):
    api.post("/sync/login", json={"username": USER, "password": PASS, "endpoint": sync_server})
    api.post("/sync/full-upload")

    folder = os.path.join(os.path.dirname(settings.collection_path), "backups")
    os.makedirs(folder, exist_ok=True)
    # seed 5 fake older backups (lexically older than any real timestamp)
    for i in range(5):
        with open(os.path.join(folder, f"ankiweb-00000000-00000{i}.anki2"), "w") as f:
            f.write("stale")

    api.post("/sync/backup-remote")
    import glob as _glob
    remaining = sorted(_glob.glob(os.path.join(folder, "ankiweb-*.anki2")))
    assert len(remaining) == 5  # REMOTE_BACKUP_KEEP
    assert not os.path.basename(remaining[0]).startswith("ankiweb-00000000-000000"), "oldest pruned"


def test_collection_backup_creates_colpkg(api, settings):
    out = api.post("/collection/backup").json()
    assert out["created"] is True
    assert any(name.endswith(".colpkg") for name in os.listdir(out["folder"]))
