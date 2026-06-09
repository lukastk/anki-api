"""Statistics [parity]: the data behind the stats graphs + structured card info.

The backend computes all graph data in one call (future due, reviews, intervals,
hours, card counts, true retention, FSRS, etc.); we serialize the protobuf to
JSON so a UI can render charts. Field names are kept snake_case to match the
rest of the API.
"""

from __future__ import annotations

from google.protobuf.json_format import MessageToDict, ParseDict
from anki import stats_pb2
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id

router = APIRouter(prefix="/stats", tags=["stats"])


def _to_dict(msg) -> dict:
    return MessageToDict(msg, preserving_proto_field_name=True)


@router.get("/graphs")
def graphs(search: str = "", days: int = 365, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """All stats-graph data for cards matching `search` over the last `days`."""
    with handle.locked() as col:
        return _to_dict(col._backend.graphs(search=search, days=days))


@router.get("/today")
def studied_today(handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        return {"summary": col.studied_today()}


@router.get("/card/{card_id}")
def card_stats_data(card_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Structured card info (complements the rendered HTML at /cards/{id}/stats)."""
    cid = parse_id(card_id)
    with handle.locked() as col:
        return _to_dict(col.card_stats_data(cid))


@router.get("/graph-preferences")
def get_graph_preferences(handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        return _to_dict(col._backend.get_graph_preferences())


@router.put("/graph-preferences")
def set_graph_preferences(body: dict[str, Any], handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        prefs = ParseDict(body, stats_pb2.GraphPreferences())
        col._backend.set_graph_preferences(prefs)
        return _to_dict(col._backend.get_graph_preferences())
