"""Deck options / presets [parity]: the config groups behind the deck-options screen.

These use anki's legacy config CRUD (update_config/remove_config return None,
not OpChanges), so preset-mutating endpoints return the resulting config rather
than a Mutation envelope. Assigning a preset to a deck goes through the deck
(decks.update_dict) and does return OpChanges — that lives in the decks router.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id
from ..schemas.common import RequestModel

router = APIRouter(prefix="/deck-presets", tags=["deck-presets"])

DEFAULT_PRESET_ID = 1


class CreatePreset(RequestModel):
    name: str
    clone_from: str | None = None


def preset_or_404(col, pid: int) -> dict:
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


def _deep_merge(base: dict, patch: dict, path: str = "") -> None:
    """Merge `patch` into the preset `base`, key by key, nested dicts recursively. A key the
    preset does not have (at any level) is a 422: Anki keeps unknown keys in the config JSON
    without complaint, so `{"new": {"perday": 5}}` used to be stored, change nothing, and
    answer 200."""
    for key, value in patch.items():
        here = f"{path}.{key}" if path else key
        if key not in base:
            raise HTTPException(status_code=422, detail=f"unknown preset key {here!r}; see GET /deck-presets/{{id}} for the keys")
        if isinstance(value, dict) and isinstance(base[key], dict):
            _deep_merge(base[key], value, here)
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
        return _view(preset_or_404(col, pid))


@router.post("")
def create_preset(body: CreatePreset, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        clone = preset_or_404(col, parse_id(body.clone_from)) if body.clone_from else None
        pid = col.decks.add_config_returning_id(body.name, clone_from=clone)
        return {"id": str(pid)}


@router.put("/{preset_id}")
def update_preset(preset_id: str, body: dict[str, Any], handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Merge a partial config into the preset (deep-merges nested new/rev/lapse). 422 for a key the preset does not have."""
    pid = parse_id(preset_id)
    with handle.locked() as col:
        cfg = preset_or_404(col, pid)
        patch = {k: v for k, v in body.items() if k != "id"}
        _deep_merge(cfg, patch)
        col.decks.update_config(cfg)
        return _view(preset_or_404(col, pid))


@router.delete("/{preset_id}")
def delete_preset(preset_id: str, accept_schema_change: bool = False,
                  handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Remove a preset. This MODIFIES THE SCHEMA, so it is refused until the caller accepts that.

    Anki's `DeckManager.remove_config` calls `mod_schema`, which stamps the collection's `scm` and makes the
    NEXT SYNC a one-way full sync. Three unused presets were removed from a synced collection on 2026-10-30
    and its next sync answered `full_sync`, which cost a full download of the server's side and redoing the
    work that had been done since: the hazard is recognised here, before the write, rather than read off the
    sync's answer afterwards.

    `accept_schema_change=true` is the caller saying it has choreographed that full sync. The response then
    reports the schema state in the words `/sync/health` uses, so the write's own receipt carries it.

    A missing preset is still a 404 and the default preset still a 422: neither is a reason to touch the
    schema, and the default can never be removed however the call is made.
    """
    pid = parse_id(preset_id)
    if pid == DEFAULT_PRESET_ID:
        raise HTTPException(status_code=422, detail="the default preset cannot be removed")
    with handle.locked() as col:
        preset_or_404(col, pid)  # 404 if missing, before anything has touched the schema
        if not accept_schema_change:
            raise HTTPException(
                status_code=409,
                detail=(f"removing preset {preset_id} modifies the collection's schema (Anki's "
                        f"remove_config calls mod_schema), so the next sync will be a one-way full sync. "
                        f"Pass accept_schema_change=true once that full sync is choreographed, or leave the "
                        f"preset in place: an unused preset costs nothing."),
            )
        col.decks.remove_config(pid)
        scm = col.db.scalar("select scm from col")
        ls = col.db.scalar("select ls from col")
        return {"ok": True, "schema_changed": scm > ls, "schema_modified": str(scm)}


@router.post("/{preset_id}/restore-defaults")
def restore_defaults(preset_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    pid = parse_id(preset_id)
    with handle.locked() as col:
        cfg = preset_or_404(col, pid)
        col.decks.restore_to_default(cfg)
        return _view(preset_or_404(col, pid))
