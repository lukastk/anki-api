"""Filtered (dynamic) decks & custom study [parity].

A filtered deck temporarily gathers cards matching a search; rebuild re-gathers,
empty returns them to their home decks. Custom study builds a one-off filtered
deck for extra new/review/ahead/preview sessions.
"""

from __future__ import annotations

from anki import scheduler_pb2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id
from ..schemas.common import Mutation, mutation

router = APIRouter(prefix="/filtered-decks", tags=["filtered-decks"])

_CUSTOM_STUDY_FIELDS = {
    "new_limit": "new_limit_delta",
    "review_limit": "review_limit_delta",
    "forgot": "forgot_days",
    "ahead": "review_ahead_days",
    "preview": "preview_days",
}


class CreateFiltered(BaseModel):
    name: str
    search: str
    limit: int = 100
    order: int = 0  # SortOrder enum index (0 = order added)


class CustomStudy(BaseModel):
    deck_id: str
    mode: str  # new_limit | review_limit | forgot | ahead | preview
    value: int


@router.post("")
def create_filtered(body: CreateFiltered, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        fid = col.decks.new_filtered(body.name)
        deck = col.decks.get(fid)
        deck["terms"] = [[body.search, body.limit, body.order]]
        col.decks.save(deck)
        out = col.sched.rebuild_filtered_deck(fid)
        return {"id": str(fid), "count": out.count}


@router.post("/{deck_id}/rebuild")
def rebuild(deck_id: str, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    did = parse_id(deck_id)
    with handle.locked() as col:
        out = col.sched.rebuild_filtered_deck(did)
        return mutation(out.changes, count=out.count)


@router.post("/{deck_id}/empty")
def empty(deck_id: str, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    did = parse_id(deck_id)
    with handle.locked() as col:
        return mutation(col.sched.empty_filtered_deck(did))


@router.post("/custom-study")
def custom_study(body: CustomStudy, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    field = _CUSTOM_STUDY_FIELDS.get(body.mode)
    if field is None:
        raise HTTPException(status_code=422, detail=f"mode must be one of {list(_CUSTOM_STUDY_FIELDS)}")
    with handle.locked() as col:
        req = scheduler_pb2.CustomStudyRequest(deck_id=parse_id(body.deck_id))
        setattr(req, field, body.value)
        return mutation(col.sched.custom_study(req))
