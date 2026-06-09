"""Image Occlusion note authoring [parity].

IO notes hide regions of an image. The backend's `occlusions` argument is a
cloze-style string, one occlusion per `{{c<n>::image-occlusion:<shape>:k=v:k=v}}`
group; we accept structured shapes and assemble it. The image is supplied inline
(base64) or by an existing media filename.
"""

from __future__ import annotations

import base64
import os
import tempfile

from google.protobuf.json_format import MessageToDict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id
from ..schemas.common import Mutation, mutation

router = APIRouter(tags=["image-occlusion"])

IO_NOTETYPE = "Image Occlusion"


class Occlusion(BaseModel):
    shape: str  # rect | ellipse | polygon
    properties: dict[str, str | float | int]
    ordinal: int | None = None


class CreateIO(BaseModel):
    occlusions: list[Occlusion]
    header: str = ""
    back_extra: str = ""
    tags: list[str] = []
    image_filename: str | None = None  # an existing media file
    image_data_base64: str | None = None  # or inline image bytes
    image_upload_name: str = "image.png"  # filename used when uploading inline data


class UpdateIO(BaseModel):
    occlusions: list[Occlusion] | None = None
    header: str | None = None
    back_extra: str | None = None
    tags: list[str] | None = None


def _io_notetype_id(col) -> int:
    nt = col.models.by_name(IO_NOTETYPE)
    if nt is None:
        col._backend.add_image_occlusion_notetype()
        nt = col.models.by_name(IO_NOTETYPE)
    return nt["id"]


def _build_occlusions(occlusions: list[Occlusion]) -> str:
    parts = []
    for i, occ in enumerate(occlusions):
        ordinal = occ.ordinal if occ.ordinal is not None else i + 1
        props = ":".join(f"{k}={v}" for k, v in occ.properties.items())
        parts.append(f"{{{{c{ordinal}::image-occlusion:{occ.shape}:{props}}}}}")
    return "".join(parts)


@router.post("/notetypes/image-occlusion")
def ensure_io_notetype(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Ensure the Image Occlusion notetype exists; returns its id."""
    with handle.locked() as col:
        return {"id": str(_io_notetype_id(col))}


@router.post("/notes/image-occlusion")
def create_io_note(body: CreateIO, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    if not body.occlusions:
        raise HTTPException(status_code=422, detail="at least one occlusion is required")
    tmp_path = None
    with handle.locked() as col:
        nt_id = _io_notetype_id(col)
        if body.image_data_base64 is not None:
            try:
                data = base64.b64decode(body.image_data_base64)
            except Exception:
                raise HTTPException(status_code=422, detail="image_data_base64 is not valid base64")
            fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(body.image_upload_name)[1] or ".png")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            image_path = tmp_path
        elif body.image_filename:
            image_path = os.path.join(col.media.dir(), body.image_filename)
            if not os.path.exists(image_path):
                raise HTTPException(status_code=404, detail=f"media file {body.image_filename!r} not found")
        else:
            raise HTTPException(status_code=422, detail="image_filename or image_data_base64 required")

        try:
            before = set(col.find_notes(f'note:"{IO_NOTETYPE}"'))
            out = col.add_image_occlusion_note(
                nt_id, image_path, _build_occlusions(body.occlusions),
                body.header, body.back_extra, list(body.tags),
            )
            after = set(col.find_notes(f'note:"{IO_NOTETYPE}"'))
        finally:
            if tmp_path:
                os.unlink(tmp_path)
        new = after - before
        note_id = new.pop() if new else None
        return mutation(out, id=note_id)


@router.get("/notes/{note_id}/image-occlusion")
def get_io_note(note_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    nid = parse_id(note_id)
    with handle.locked() as col:
        resp = col.get_image_occlusion_note(nid)
        if resp.WhichOneof("value") == "error":
            raise HTTPException(status_code=404, detail=resp.error)
        return MessageToDict(resp.note, preserving_proto_field_name=True)


@router.put("/notes/{note_id}/image-occlusion")
def update_io_note(note_id: str, body: UpdateIO, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(note_id)
    with handle.locked() as col:
        occlusions = _build_occlusions(body.occlusions) if body.occlusions is not None else None
        return mutation(col.update_image_occlusion_note(
            nid, occlusions, body.header, body.back_extra, body.tags,
        ))
