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

from anki import sync_pb2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle

router = APIRouter(prefix="/sync", tags=["sync"])

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


@router.post("/login")
def login(body: Login, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        auth = col.sync_login(body.username, body.password, body.endpoint or None)
    handle.sync_auth = auth
    return {"logged_in": True, "endpoint": auth.endpoint or "ankiweb"}


@router.post("/logout")
def logout(handle: CollectionHandle = Depends(get_handle)) -> dict:
    handle.sync_auth = None
    return {"logged_in": False}


@router.get("/status")
def status(handle: CollectionHandle = Depends(get_handle)) -> dict:
    auth = _auth(handle)
    with handle.locked() as col:
        st = col.sync_status(auth)
    return {"required": _STATUS.get(st.required, st.required)}


@router.post("")
def sync(body: SyncOptions, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Perform an incremental sync. Reports if a full sync is additionally required."""
    auth = _auth(handle)
    with handle.locked() as col:
        out = col.sync_collection(auth, body.sync_media)
    handle.server_media_usn = out.server_media_usn
    return {
        "required": _REQUIRED.get(out.required, out.required),
        "server_message": out.server_message,
    }


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
