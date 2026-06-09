"""Collection / system endpoints: health and collection info."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..collection_handle import CollectionHandle
from ..deps import get_handle

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/collection")
def collection_info(handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        return {
            "path": handle.path,
            "schema_modified": str(col.db.scalar("select scm from col")),
            "modified": str(col.mod),
            "v3_scheduler": col.v3_scheduler(),
            "note_count": col.note_count(),
            "card_count": col.card_count(),
        }
