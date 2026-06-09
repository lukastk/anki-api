"""Undo / redo endpoints [core]."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..schemas.common import mutation

router = APIRouter(prefix="/undo", tags=["undo"])


@router.get("/status")
def undo_status(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """What undo/redo would do next (empty strings mean nothing to undo/redo)."""
    with handle.locked() as col:
        status = col.undo_status()
        return {
            "undo": status.undo,
            "redo": status.redo,
            "last_step": status.last_step,
        }


@router.post("")
def undo(handle: CollectionHandle = Depends(get_handle)):
    """Undo the last operation (409 undo_empty if nothing to undo)."""
    with handle.locked() as col:
        out = col.undo()
        return mutation(out.changes)


@router.post("/redo")
def redo(handle: CollectionHandle = Depends(get_handle)):
    with handle.locked() as col:
        out = col.redo()
        return mutation(out.changes)
