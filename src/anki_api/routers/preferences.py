"""Config & preferences [parity].

Two layers: arbitrary collection config key/values, and the structured
Preferences proto (scheduling/reviewing/editing/backups) behind the Preferences
screen.
"""

from __future__ import annotations

from typing import Any

from google.protobuf.json_format import MessageToDict, ParseDict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..schemas.common import Mutation, mutation

router = APIRouter(tags=["preferences"])

_MISSING = object()


class ConfigValue(BaseModel):
    value: Any


@router.get("/config/{key}")
def get_config(key: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        value = col.get_config(key, _MISSING)
        if value is _MISSING:
            raise HTTPException(status_code=404, detail=f"config key {key!r} not set")
        return {"key": key, "value": value}


@router.put("/config/{key}")
def set_config(key: str, body: ConfigValue, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        return mutation(col.set_config(key, body.value))


@router.delete("/config/{key}")
def remove_config(key: str, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        if col.get_config(key, _MISSING) is _MISSING:
            raise HTTPException(status_code=404, detail=f"config key {key!r} not set")
        return mutation(col.remove_config(key))


@router.get("/preferences")
def get_preferences(handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        return MessageToDict(col.get_preferences(), preserving_proto_field_name=True)


@router.put("/preferences")
def set_preferences(body: dict[str, Any], handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Partial update: merges the given fields into the current preferences."""
    with handle.locked() as col:
        prefs = col.get_preferences()
        ParseDict(body, prefs)  # merges into the existing message
        col.set_preferences(prefs)
        return MessageToDict(col.get_preferences(), preserving_proto_field_name=True)
