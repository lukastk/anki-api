"""Media endpoints [parity]: store/serve/delete media files + media check.

Files are referenced from note fields by bare filename; the media folder is flat
(no subdirectories), so we reject any path separators to prevent traversal.
"""

from __future__ import annotations

import base64
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle

router = APIRouter(prefix="/media", tags=["media"])


class UploadMedia(BaseModel):
    filename: str
    data_base64: str


def _safe_name(filename: str) -> str:
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid media filename")
    return filename


@router.post("/files")
def upload(body: UploadMedia, handle: CollectionHandle = Depends(get_handle)) -> dict:
    name = _safe_name(body.filename)
    try:
        data = base64.b64decode(body.data_base64)
    except Exception:
        raise HTTPException(status_code=422, detail="data_base64 is not valid base64")
    with handle.locked() as col:
        # write_data may rename to avoid clobbering; it returns the actual name.
        stored = col.media.write_data(name, data)
        return {"filename": stored}


@router.get("/check")
def check(handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        out = col.media.check()
        return {
            "unused": list(out.unused),
            "missing": list(out.missing),
            "report": out.report,
            "have_trash": out.have_trash,
        }


@router.get("/files/{filename}")
def download(filename: str, handle: CollectionHandle = Depends(get_handle)) -> FileResponse:
    name = _safe_name(filename)
    with handle.locked() as col:
        if not col.media.have(name):
            raise HTTPException(status_code=404, detail=f"media file {name!r} not found")
        path = os.path.join(col.media.dir(), name)
    return FileResponse(path, filename=name)


@router.delete("/files/{filename}")
def delete(filename: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    name = _safe_name(filename)
    with handle.locked() as col:
        if not col.media.have(name):
            raise HTTPException(status_code=404, detail=f"media file {name!r} not found")
        col.media.trash_files([name])
        return {"ok": True}
