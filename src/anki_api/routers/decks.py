"""Deck endpoints [core]: tree with counts, list, get, create, rename, reparent, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id, parse_ids
from ..schemas.common import Mutation, mutation

router = APIRouter(prefix="/decks", tags=["decks"])


class CreateDeck(BaseModel):
    name: str


class RenameDeck(BaseModel):
    name: str


class Reparent(BaseModel):
    deck_ids: list[str]
    new_parent: str


class AssignPreset(BaseModel):
    preset_id: str


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
    did = parse_id(deck_id)
    with handle.locked() as col:
        deck = col.decks.get_legacy(did)
        if deck is None:
            raise HTTPException(status_code=404, detail=f"deck {deck_id} not found")
        return {
            "id": str(deck["id"]),
            "name": deck["name"],
            "filtered": bool(deck.get("dyn", 0)),
            "config_id": str(deck["conf"]) if "conf" in deck else None,
            "description": deck.get("desc", ""),
        }


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
    did = parse_id(deck_id)
    with handle.locked() as col:
        deck = col.decks.get_legacy(did)
        if deck is None:
            raise HTTPException(status_code=404, detail=f"deck {deck_id} not found")
        col.decks.set_config_id_for_deck_dict(deck, parse_id(body.preset_id))
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
    did = parse_id(deck_id)
    with handle.locked() as col:
        out = col.decks.remove([did])
        return mutation(out.changes, count=out.count)
