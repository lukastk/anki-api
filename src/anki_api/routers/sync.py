"""Sync [parity] — sync this collection against AnkiWeb or a self-hosted server.

The server is a sync *client*, exactly like the desktop app or AnkiDroid (see
experiment 04). Log in once, then sync. AnkiWeb is the same path with no endpoint
(endpoint=null); a self-hosted server passes its URL.

Full sync (first upload/download, or after a schema change) is NOT performed
automatically: an incremental /sync reports `required` as full_upload/
full_download/full_sync, and the client then calls /sync/full-upload or
/sync/full-download explicitly (these overwrite one side, so the direction is a
deliberate choice). Full sync closes+reopens the collection under the writer lock.
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
import time

from anki import sync_pb2
from anki.collection import Collection
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle

router = APIRouter(prefix="/sync", tags=["sync"])

log = logging.getLogger("anki_api.sync")

# How many remote shadow-backups (backup-remote) to keep.
REMOTE_BACKUP_KEEP = 5

_REQUIRED = {
    sync_pb2.SyncCollectionResponse.NO_CHANGES: "no_changes",
    sync_pb2.SyncCollectionResponse.NORMAL_SYNC: "normal_sync",
    sync_pb2.SyncCollectionResponse.FULL_SYNC: "full_sync",
    sync_pb2.SyncCollectionResponse.FULL_DOWNLOAD: "full_download",
    sync_pb2.SyncCollectionResponse.FULL_UPLOAD: "full_upload",
}
_STATUS = {
    sync_pb2.SyncStatusResponse.NO_CHANGES: "no_changes",
    sync_pb2.SyncStatusResponse.NORMAL_SYNC: "normal_sync",
    sync_pb2.SyncStatusResponse.FULL_SYNC: "full_sync",
}


class Login(BaseModel):
    username: str
    password: str
    endpoint: str | None = None  # null -> AnkiWeb; otherwise a self-hosted URL


class SyncOptions(BaseModel):
    sync_media: bool = True


def _auth(handle: CollectionHandle):
    if handle.sync_auth is None:
        raise HTTPException(status_code=401, detail="not logged in; POST /sync/login first")
    return handle.sync_auth


def _incremental_sync(handle: CollectionHandle, sync_media: bool) -> dict:
    """Run one incremental sync, persisting any server endpoint shard change.

    Shared by POST /sync and the background autosync loop. Does NOT perform a full
    sync — it only reports when one is required, so the direction stays a
    deliberate choice."""
    auth = _auth(handle)
    with handle.locked() as col:
        out = col.sync_collection(auth, sync_media)
    handle.server_media_usn = out.server_media_usn
    # AnkiWeb shards by host: a sync can hand back a new endpoint to use from now
    # on. Persist it so subsequent syncs (and restarts) hit the right server.
    if out.new_endpoint and out.new_endpoint != auth.endpoint:
        auth.endpoint = out.new_endpoint
        handle.save_sync_auth(auth)
    return {
        "required": _REQUIRED.get(out.required, out.required),
        "server_message": out.server_message,
    }


def _autosync_full_action(required: str, schema_changed: bool, policy: str) -> str:
    """Decide what the autosync loop does about a REQUIRED full sync.

    Returns "download" (safe to adopt the server) or "blocked" (leave it for a
    deliberate manual /sync/full-{upload,download}). Download is chosen only when
    the policy allows it AND the *server* — not this collection — is the side that
    is ahead: a `full_upload` requirement (this side's schema is ahead) and any
    local `schema_changed` (which includes the never-synced state) are always left
    for a manual call, so no local-only schema change is ever silently discarded.
    """
    if policy == "download" and not schema_changed and required in ("full_download", "full_sync"):
        return "download"
    return "blocked"


def _local_backup(handle: CollectionHandle) -> None:
    """Best-effort .colpkg backup of the live collection before an automatic
    overwrite (possession, not inference — mirrors POST /collection/backup). A
    failure is logged, not fatal: the overwrite still proceeds (the local state is
    also covered by the host's own backups, and — for a replica — re-derivable)."""
    try:
        with handle.locked() as col:
            folder = os.path.join(os.path.dirname(handle.path), "backups")
            os.makedirs(folder, exist_ok=True)
            col.create_backup(backup_folder=folder, force=True, wait_for_completion=True)
    except Exception as e:  # noqa: BLE001 - backup must never block the sync loop
        log.warning("autosync: pre-download backup failed: %s (proceeding)", e)


def _notify(handle: CollectionHandle, title: str, body: str) -> None:
    """Run the configured notifier as `<cmd> <title> <body>` (argv, never a shell
    string). Best-effort — a notifier must never break the sync loop."""
    cmd = handle.settings.autosync_notify_cmd
    if not cmd:
        return
    try:
        subprocess.run([cmd, title, body], timeout=15, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        log.warning("autosync: notify command failed: %s", e)


def run_autosync(handle: CollectionHandle) -> dict:
    """One autosync tick (called from the background loop in app.py).

    Logs in from configured credentials if needed, then runs an incremental sync.
    If a full sync is REQUIRED, the ANKI_API_AUTOSYNC_FULL policy decides: "off"
    (default) logs it and leaves the direction for a manual call — no silent data
    loss; "download" auto-resolves by adopting the server when that is safe (see
    _autosync_full_action), taking a local backup first. Auto-resolution and
    blocked states fire the optional notifier once per transition (never per tick).
    """
    if not handle.ensure_logged_in():
        return {"skipped": "not logged in"}
    result = _incremental_sync(handle, sync_media=True)
    required = result["required"]
    if required in ("no_changes", "normal_sync"):
        handle.autosync_last_required = required  # clear any prior alert state
        return result

    # A full sync is required. Read whether THIS collection has an un-synced schema
    # change of its own (scm > ls — same fact GET /sync/health exposes).
    with handle.locked() as col:
        schema_changed = col.db.scalar("select scm from col") > col.db.scalar("select ls from col")
    action = _autosync_full_action(required, schema_changed, handle.settings.autosync_full)
    is_transition = handle.autosync_last_required != required
    handle.autosync_last_required = required

    if action == "download":
        log.warning("autosync: full sync required (%s); AUTOSYNC_FULL=download → "
                    "backing up locally, then full-downloading from the server", required)
        _local_backup(handle)
        _perform_full_download(handle)
        try:
            required = _incremental_sync(handle, sync_media=True)["required"]
        except Exception as e:  # noqa: BLE001 - the download already succeeded
            log.warning("autosync: post-download sync failed: %s", e)
            required = "no_changes"
        handle.autosync_last_required = required
        _notify(handle, "anki-api: auto-resolved a full sync",
                "Adopted the server via full-download; the local collection now "
                "matches AnkiWeb.")
        return {"required": required, "resolved": "full_download"}

    log.warning("autosync: full sync required (%s), NOT auto-resolved "
                "(AUTOSYNC_FULL=%s, schema_changed=%s); resolve the direction via "
                "/sync/full-upload or /sync/full-download", required,
                handle.settings.autosync_full, schema_changed)
    if is_transition:
        _notify(handle, "anki-api: full sync needs a manual decision",
                f"Sync is blocked needing a full {required}; resolve the direction "
                "via /sync/full-upload or /sync/full-download.")
    return result


@router.post("/login")
def login(body: Login, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        auth = col.sync_login(body.username, body.password, body.endpoint or None)
    handle.save_sync_auth(auth)
    return {"logged_in": True, "endpoint": auth.endpoint or "ankiweb"}


@router.post("/logout")
def logout(handle: CollectionHandle = Depends(get_handle)) -> dict:
    handle.clear_sync_auth()
    return {"logged_in": False}


@router.get("/health")
def sync_health(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Local sync-health facts — no server contact, no auth required.

    Exposes the col table's `scm` (schema-modified, ms) and `ls` (last successful
    full/first sync, ms). `schema_changed` (scm > ls) means the next sync must be a
    one-way full sync; `never_synced` (ls == 0) means this collection has never
    synced with a server at all — full-uploading it would overwrite unknown remote
    state (this exact state preceded the 2026-07-03 collection wipe). Clients use
    these to gate full-sync direction decisions.
    """
    with handle.locked() as col:
        scm = col.db.scalar("select scm from col")
        ls = col.db.scalar("select ls from col")
        crt = col.db.scalar("select crt from col")
        return {
            "schema_modified": str(scm),
            "last_sync": str(ls),
            "never_synced": ls == 0,
            "schema_changed": scm > ls,
            "logged_in": handle.sync_auth is not None,
            "collection_created": str(crt),  # epoch seconds (scm/ls are ms)
            "note_count": col.note_count(),
            "card_count": col.card_count(),
        }


@router.get("/status")
def status(handle: CollectionHandle = Depends(get_handle)) -> dict:
    auth = _auth(handle)
    with handle.locked() as col:
        st = col.sync_status(auth)
    return {"required": _STATUS.get(st.required, st.required)}


@router.post("")
def sync(body: SyncOptions, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Perform an incremental sync. Reports if a full sync is additionally required."""
    return _incremental_sync(handle, body.sync_media)


@router.post("/full-upload")
def full_upload(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Overwrite the server's collection with this one (full upload)."""
    auth = _auth(handle)
    with handle.locked() as col:
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=handle.server_media_usn, upload=True)
        col.reopen(after_full_sync=True)
    return {"ok": True, "direction": "upload"}


def _perform_full_download(handle: CollectionHandle) -> None:
    """Overwrite this collection with the server's. Shared by the endpoint and the
    autosync loop; the caller decides *when* it is appropriate."""
    auth = _auth(handle)
    with handle.locked() as col:
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=handle.server_media_usn, upload=False)
        col.reopen(after_full_sync=True)


@router.post("/full-download")
def full_download(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Overwrite this collection with the server's (full download)."""
    _perform_full_download(handle)
    return {"ok": True, "direction": "download"}


@router.post("/media")
def sync_media(handle: CollectionHandle = Depends(get_handle)) -> dict:
    auth = _auth(handle)
    with handle.locked() as col:
        col.sync_media(auth)
    return {"ok": True}


def _prune_remote_backups(folder: str, keep: int) -> None:
    """Keep the newest `keep` ankiweb-*.anki2 backups; remove older ones (plus any
    sidecar files/dirs the throwaway collection created next to them)."""
    backups = sorted(glob.glob(os.path.join(folder, "ankiweb-*.anki2")))
    for path in backups[:-keep] if keep else backups:
        prefix = path[: -len(".anki2")]
        for stale in glob.glob(prefix + "*"):
            if os.path.isdir(stale):
                shutil.rmtree(stale, ignore_errors=True)
            else:
                os.remove(stale)


@router.post("/backup-remote")
def backup_remote(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Shadow-download the server's collection into a timestamped backup file.

    Possession, not inference: run this BEFORE any full-upload so the remote's
    pre-overwrite state is on local disk even if the upload turns out to be wrong.
    Uses a THROWAWAY collection at backups/ankiweb-<utc>.anki2 — the live collection
    is never touched (no writer lock, no close/reopen, no 503 window). Collection DB
    only; media syncs separately. Keeps the newest REMOTE_BACKUP_KEEP backups.
    """
    auth = _auth(handle)
    folder = os.path.join(os.path.dirname(handle.path), "backups")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, time.strftime("ankiweb-%Y%m%d-%H%M%S.anki2", time.gmtime()))

    col = Collection(path)
    try:
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=None, upload=False)
        col.reopen(after_full_sync=True)
        note_count = col.note_count()
        card_count = col.card_count()
    finally:
        col.close()

    _prune_remote_backups(folder, REMOTE_BACKUP_KEEP)
    log.info("backup-remote: %s (%d notes / %d cards)", path, note_count, card_count)
    return {"path": path, "note_count": note_count, "card_count": card_count}
