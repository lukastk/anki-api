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


class DeleteUnusedForFullSync(RequestModel):
    expected_name: str


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
def delete_preset(preset_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Remove a preset only from a collection that has never been synced.

    Anki's ``DeckManager.remove_config`` calls ``mod_schema``. Once a collection has
    a sync history, that turns its next sync into a one-way full sync, so deletion is
    refused rather than exposing an acknowledgement switch that can recreate the loss.
    An unused preset is harmless and can remain until a choreographed full-sync sitting.
    """
    pid = parse_id(preset_id)
    if pid == DEFAULT_PRESET_ID:
        raise HTTPException(status_code=422, detail="the default preset cannot be removed")
    with handle.locked() as col:
        preset_or_404(col, pid)  # 404 before the sync-history guard
        last_sync = col.db.scalar("select ls from col")
        if last_sync != 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"refusing to remove preset {preset_id} from a synced collection: Anki's "
                    "remove_config modifies the schema, so the next sync would require a one-way full sync. "
                    "Leave the unused preset in place until a choreographed full-sync sitting."
                ),
            )
        col.decks.remove_config(pid)
        scm = col.db.scalar("select scm from col")
        return {"ok": True, "schema_changed": True, "schema_modified": str(scm)}


@router.post("/{preset_id}/delete-unused-for-full-sync")
def delete_unused_for_full_sync(
    preset_id: str,
    body: DeleteUnusedForFullSync,
    handle: CollectionHandle = Depends(get_handle),
) -> dict:
    """Delete one verified-unused preset while another write already requires a full sync.

    This is deliberately not an acknowledgement switch on DELETE. It is a separate operation
    for a recorded full-sync choreography: the preset's identity is compare-and-swap guarded,
    no deck may use it, and the collection must already carry an unsynced schema change.
    """
    pid = parse_id(preset_id)
    if pid == DEFAULT_PRESET_ID:
        raise HTTPException(status_code=422, detail="the default preset cannot be removed")
    if not body.expected_name.strip():
        raise HTTPException(status_code=422, detail="expected_name must be nonempty")
    with handle.locked() as col:
        cfg = preset_or_404(col, pid)
        if cfg["name"] != body.expected_name:
            raise HTTPException(
                status_code=409,
                detail=f"preset {preset_id} has name {cfg['name']!r}, expected name {body.expected_name!r}",
            )
        scm = col.db.scalar("select scm from col")
        last_sync = col.db.scalar("select ls from col")
        if scm <= last_sync:
            raise HTTPException(
                status_code=409,
                detail=(
                    "the collection does not already require a full sync; add the choreographed "
                    "schema fields before deleting parked presets"
                ),
            )
        assigned = []
        for row in col.decks.all_names_and_ids(include_filtered=True):
            deck = col.decks.get_legacy(row.id)
            if deck is not None and deck.get("conf") == pid:
                assigned.append(row.name)
        if assigned:
            raise HTTPException(
                status_code=409,
                detail=f"preset {preset_id} is still assigned to deck(s): {sorted(assigned)}",
            )
        col.decks.remove_config(pid)
        scm_after = col.db.scalar("select scm from col")
        return {
            "ok": True,
            "id": str(pid),
            "name": body.expected_name,
            "schema_changed": scm_after > last_sync,
            "schema_modified": str(scm_after),
        }


@router.post("/{preset_id}/restore-defaults")
def restore_defaults(preset_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    pid = parse_id(preset_id)
    with handle.locked() as col:
        cfg = preset_or_404(col, pid)
        col.decks.restore_to_default(cfg)
        return _view(preset_or_404(col, pid))
