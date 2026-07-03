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

import logging

from anki import sync_pb2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle

router = APIRouter(prefix="/sync", tags=["sync"])

log = logging.getLogger("anki_api.sync")

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


def run_autosync(handle: CollectionHandle) -> dict:
    """One autosync tick (called from the background loop in app.py).

    Logs in from configured credentials if needed, then runs an incremental sync.
    A required full sync is reported and left alone (no silent data loss)."""
    if not handle.ensure_logged_in():
        return {"skipped": "not logged in"}
    result = _incremental_sync(handle, sync_media=True)
    if result["required"] not in ("no_changes", "normal_sync"):
        log.warning("autosync: full sync required (%s); resolve direction manually "
                    "via /sync/full-upload or /sync/full-download", result["required"])
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


@router.post("/full-download")
def full_download(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Overwrite this collection with the server's (full download)."""
    auth = _auth(handle)
    with handle.locked() as col:
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=handle.server_media_usn, upload=False)
        col.reopen(after_full_sync=True)
    return {"ok": True, "direction": "download"}


@router.post("/media")
def sync_media(handle: CollectionHandle = Depends(get_handle)) -> dict:
    auth = _auth(handle)
    with handle.locked() as col:
        col.sync_media(auth)
    return {"ok": True}
