"""Deck options / presets [parity]: the config groups behind the deck-options screen.

These use anki's legacy config CRUD (update_config/remove_config return None,
not OpChanges), so preset-mutating endpoints return the resulting config rather
than a Mutation envelope. Assigning a preset to a deck goes through the deck
(decks.update_dict) and does return OpChanges — that lives in the decks router.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id

router = APIRouter(prefix="/deck-presets", tags=["deck-presets"])

DEFAULT_PRESET_ID = 1


class CreatePreset(BaseModel):
    name: str
    clone_from: str | None = None


def _config(col, pid: int) -> dict:
    # NB: anki's get_config silently returns the Default preset for an unknown id,
    # so we detect "missing" by id mismatch and surface it loudly as a 404.
    cfg = col.decks.get_config(pid)
    if cfg is None or cfg["id"] != pid:
        raise HTTPException(status_code=404, detail=f"deck preset {pid} not found")
    return cfg


def _view(cfg: dict) -> dict:
    out = dict(cfg)
    out["id"] = str(cfg["id"])
    return out


def _deep_merge(base: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


@router.get("")
def list_presets(handle: CollectionHandle = Depends(get_handle)) -> list[dict]:
    with handle.locked() as col:
        return [{"id": str(c["id"]), "name": c["name"]} for c in col.decks.all_config()]


@router.get("/{preset_id}")
def get_preset(preset_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    pid = parse_id(preset_id)
    with handle.locked() as col:
        return _view(_config(col, pid))


@router.post("")
def create_preset(body: CreatePreset, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        clone = _config(col, parse_id(body.clone_from)) if body.clone_from else None
        pid = col.decks.add_config_returning_id(body.name, clone_from=clone)
        return {"id": str(pid)}


@router.put("/{preset_id}")
def update_preset(preset_id: str, body: dict[str, Any], handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Merge a partial config into the preset (deep-merges nested new/rev/lapse)."""
    pid = parse_id(preset_id)
    with handle.locked() as col:
        cfg = _config(col, pid)
        patch = {k: v for k, v in body.items() if k != "id"}
        _deep_merge(cfg, patch)
        col.decks.update_config(cfg)
        return _view(_config(col, pid))


@router.delete("/{preset_id}")
def delete_preset(preset_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    pid = parse_id(preset_id)
    if pid == DEFAULT_PRESET_ID:
        raise HTTPException(status_code=422, detail="the default preset cannot be removed")
    with handle.locked() as col:
        _config(col, pid)  # 404 if missing
        col.decks.remove_config(pid)
        return {"ok": True}


@router.post("/{preset_id}/restore-defaults")
def restore_defaults(preset_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    pid = parse_id(preset_id)
    with handle.locked() as col:
        cfg = _config(col, pid)
        col.decks.restore_to_default(cfg)
        return _view(_config(col, pid))
