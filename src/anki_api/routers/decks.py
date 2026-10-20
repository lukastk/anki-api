"""Deck endpoints [core]: tree with counts, list, get, create, rename, reparent, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id, parse_ids
from ..schemas.common import Mutation, RequestModel, mutation
from .deck_presets import preset_or_404

router = APIRouter(prefix="/decks", tags=["decks"])


class CreateDeck(RequestModel):
    name: str


class RenameDeck(RequestModel):
    name: str


class Reparent(RequestModel):
    deck_ids: list[str]
    new_parent: str


class AssignPreset(RequestModel):
    preset_id: str


class DeckLimits(RequestModel):
    """Per-deck study limits. An omitted field is left as it is; null clears it."""

    new_limit: int | None = Field(default=None, ge=0, description='"This deck" new cards/day')
    review_limit: int | None = Field(default=None, ge=0, description='"This deck" reviews/day')
    new_limit_today: int | None = Field(default=None, ge=0, description='"Today only" new cards, for the current day')
    review_limit_today: int | None = Field(default=None, ge=0, description='"Today only" reviews, for the current day')


# API field -> the deck dict key Anki 26 stores it under (verified on 26.09.3); the
# *_today keys hold a {"limit", "today"} day-limit object, the others a bare integer.
_LIMIT_KEYS = {
    "new_limit": "newLimit",
    "review_limit": "reviewLimit",
    "new_limit_today": "newLimitToday",
    "review_limit_today": "reviewLimitToday",
}
_TODAY_FIELDS = ("new_limit_today", "review_limit_today")


def _today(col) -> int:
    """Anki's current day number: `sched_timing_today().days_elapsed`, days since the
    collection was created counted in rollover-hour days. It is the day Anki's deck-options
    screen stamps on a "Today only" limit and the day the scheduler compares it with (a
    stored day-limit applies only while its `today` equals this), so reading and writing
    with it agree with what the scheduler does, rollover hour included. The calendar date
    or a local-midnight comparison would disagree with Anki between midnight and the
    rollover hour. The backend caches the value until its `next_day_at` passes."""
    return col._backend.sched_timing_today().days_elapsed


def _deck_view(col, deck: dict) -> dict:
    """One deck as GET /decks/{id} shows it. The four limits are null when unset; a
    "Today only" limit is null unless it was set for the current day (see `_today`) — a
    stale one stays in the deck dict, as Anki leaves it, but no longer applies."""
    today = _today(col)
    view = {
        "id": str(deck["id"]),
        "name": deck["name"],
        "filtered": bool(deck.get("dyn", 0)),
        "config_id": str(deck["conf"]) if "conf" in deck else None,
        "description": deck.get("desc", ""),
    }
    for field, key in _LIMIT_KEYS.items():
        value = deck.get(key)  # a filtered deck has none of these keys
        if field in _TODAY_FIELDS:
            value = value["limit"] if value is not None and value["today"] == today else None
        view[field] = value
    return view


def _deck_or_404(col, did: int, deck_id: str) -> dict:
    deck = col.decks.get_legacy(did)
    if deck is None:
        raise HTTPException(status_code=404, detail=f"deck {deck_id} not found")
    return deck


def _tree_node(node) -> dict:
    return {
        "deck_id": str(node.deck_id),
        "name": node.name,
        "level": node.level,
        "collapsed": node.collapsed,
        "filtered": node.filtered,
        "new_count": node.new_count,
        "learn_count": node.learn_count,
        "review_count": node.review_count,
        "total_in_deck": node.total_in_deck,
        "total_including_children": node.total_including_children,
        "children": [_tree_node(c) for c in node.children],
    }


@router.get("/tree")
def deck_tree(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Deck-browser tree with per-deck due/new/learn counts."""
    with handle.locked() as col:
        return _tree_node(col.sched.deck_due_tree())


@router.get("")
def list_decks(
    include_filtered: bool = True,
    skip_empty_default: bool = False,
    handle: CollectionHandle = Depends(get_handle),
) -> list[dict]:
    with handle.locked() as col:
        return [
            {"id": str(d.id), "name": d.name}
            for d in col.decks.all_names_and_ids(
                skip_empty_default=skip_empty_default, include_filtered=include_filtered
            )
        ]


@router.get("/{deck_id}")
def get_deck(deck_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """One deck, with its "This deck" (new_limit, review_limit) and "Today only"
    (new_limit_today, review_limit_today) study limits: integers, or null when unset. A
    "Today only" limit set on an earlier day reads null (see `_today` for the day used)."""
    did = parse_id(deck_id)
    with handle.locked() as col:
        return _deck_view(col, _deck_or_404(col, did, deck_id))


@router.patch("/{deck_id}/limits")
def set_deck_limits(deck_id: str, body: DeckLimits, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Set or clear the deck's "This deck" / "Today only" study limits — the per-deck
    overrides of the preset's daily limits in Anki's deck options. Only the fields present
    in the body change; null clears one. A "Today only" value is stored as
    {"limit", "today": <Anki's current day>} and stops applying when the day rolls over.
    Written with the backend's own deck update (`decks.update_dict`), so the deck's
    mtime moves and its usn becomes -1 and sync carries it; no other deck field changes.
    Returns the deck as GET /decks/{id} shows it. 404 unknown deck, 409 filtered deck
    (it has no limits), 422 negative value or unknown key."""
    did = parse_id(deck_id)
    with handle.locked() as col:
        deck = _deck_or_404(col, did, deck_id)
        if deck.get("dyn", 0):
            raise HTTPException(status_code=409, detail=f"deck {deck_id} is a filtered deck; it has no study limits")
        if body.model_fields_set:
            today = _today(col)
            for field in body.model_fields_set:
                value = getattr(body, field)
                if value is not None and field in _TODAY_FIELDS:
                    value = {"limit": value, "today": today}
                deck[_LIMIT_KEYS[field]] = value
            col.decks.update_dict(deck)
        return _deck_view(col, _deck_or_404(col, did, deck_id))


@router.get("/{deck_id}/preset")
def get_deck_preset(deck_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """The effective deck-options preset (config group) for this deck."""
    did = parse_id(deck_id)
    with handle.locked() as col:
        if col.decks.get_legacy(did) is None:
            raise HTTPException(status_code=404, detail=f"deck {deck_id} not found")
        cfg = col.decks.config_dict_for_deck_id(did)
        return {"id": str(cfg["id"]), "name": cfg["name"]}


@router.post("/{deck_id}/preset")
def assign_deck_preset(deck_id: str, body: AssignPreset, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    """Assign an existing deck-options preset to this deck (404 if either does not exist)."""
    did = parse_id(deck_id)
    with handle.locked() as col:
        deck = col.decks.get_legacy(did)
        if deck is None:
            raise HTTPException(status_code=404, detail=f"deck {deck_id} not found")
        # anki stores whatever id it is given, and a deck pointing at a preset that does not
        # exist then studies with the Default one
        preset = preset_or_404(col, parse_id(body.preset_id))
        col.decks.set_config_id_for_deck_dict(deck, preset["id"])
        return mutation(col.decks.update_dict(deck))


@router.post("")
def create_deck(body: CreateDeck, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.decks.add_normal_deck_with_name(body.name)
        return mutation(out.changes, id=out.id)


@router.post("/{deck_id}/rename")
def rename_deck(deck_id: str, body: RenameDeck, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    did = parse_id(deck_id)
    with handle.locked() as col:
        return mutation(col.decks.rename(did, body.name))


@router.post("/reparent")
def reparent_decks(body: Reparent, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.decks.reparent(parse_ids(body.deck_ids), parse_id(body.new_parent))
        return mutation(out.changes, count=out.count)


@router.delete("/{deck_id}")
def delete_deck(deck_id: str, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    """Delete the deck and its cards; `count` is the number of cards removed (404 if there is no such deck)."""
    did = parse_id(deck_id)
    with handle.locked() as col:
        # removing an unknown id is a no-op with count 0 — which is also what removing an
        # empty deck reports
        if col.decks.get_legacy(did) is None:
            raise HTTPException(status_code=404, detail=f"deck {deck_id} not found")
        out = col.decks.remove([did])
        return mutation(out.changes, count=out.count)
