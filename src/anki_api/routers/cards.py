"""Card endpoints [core]: get a card, card-info HTML, and bulk actions
(suspend/bury/set-deck/set-flag) on a card-id selection."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id, parse_ids
from ..schemas.common import Mutation, mutation

router = APIRouter(prefix="/cards", tags=["cards"])


class CardIds(BaseModel):
    card_ids: list[str]


class SetDeck(CardIds):
    deck_id: str


class SetFlag(CardIds):
    flag: int = Field(ge=0, le=7, description="0 clears the flag; 1-7 are the colored flags")


class Forget(CardIds):
    restore_position: bool = False
    reset_counts: bool = False


class RepositionNew(CardIds):
    starting_from: int = 0
    step_size: int = 1
    randomize: bool = False
    shift_existing: bool = False


def _card_view(card) -> dict:
    return {
        "id": str(card.id),
        "note_id": str(card.nid),
        "deck_id": str(card.did),
        "queue": card.queue,
        "type": card.type,
        "due": card.due,
        "interval": card.ivl,
        "reps": card.reps,
        "lapses": card.lapses,
        "flag": card.user_flag(),
        "question": card.question(),
        "answer": card.answer(),
    }


@router.get("/{card_id}")
def get_card(card_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    cid = parse_id(card_id)
    with handle.locked() as col:
        return _card_view(col.get_card(cid))


@router.get("/{card_id}/stats")
def card_stats(card_id: str, include_revlog: bool = True, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """The fully-rendered Card Info HTML that desktop/AnkiDroid show."""
    cid = parse_id(card_id)
    with handle.locked() as col:
        return {"html": col.card_stats(cid, include_revlog)}


@router.post("/actions/suspend")
def suspend(body: CardIds, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.sched.suspend_cards(parse_ids(body.card_ids))
        return mutation(out.changes, count=out.count)


@router.post("/actions/unsuspend")
def unsuspend(body: CardIds, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        return mutation(col.sched.unsuspend_cards(parse_ids(body.card_ids)))


@router.post("/actions/bury")
def bury(body: CardIds, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.sched.bury_cards(parse_ids(body.card_ids))
        return mutation(out.changes, count=out.count)


@router.post("/actions/unbury")
def unbury(body: CardIds, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        return mutation(col.sched.unbury_cards(parse_ids(body.card_ids)))


@router.post("/actions/restore-buried-and-suspended")
def restore_buried_and_suspended(body: CardIds, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    """Clear both buried and suspended states for a selection in one undoable op."""
    with handle.locked() as col:
        return mutation(col._backend.restore_buried_and_suspended_cards(parse_ids(body.card_ids)))


@router.post("/actions/forget")
def forget(body: Forget, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    """Reset cards to the 'new' state (clears scheduling history)."""
    with handle.locked() as col:
        return mutation(col.sched.schedule_cards_as_new(
            parse_ids(body.card_ids),
            restore_position=body.restore_position,
            reset_counts=body.reset_counts,
        ))


@router.post("/actions/reposition")
def reposition(body: RepositionNew, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    """Reposition new cards' due order (only affects cards in the new queue)."""
    with handle.locked() as col:
        out = col.sched.reposition_new_cards(
            parse_ids(body.card_ids), body.starting_from, body.step_size,
            body.randomize, body.shift_existing,
        )
        return mutation(out.changes, count=out.count)


@router.post("/actions/set-deck")
def set_deck(body: SetDeck, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.set_deck(parse_ids(body.card_ids), parse_id(body.deck_id))
        return mutation(out.changes, count=out.count)


@router.post("/actions/set-flag")
def set_flag(body: SetFlag, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.set_user_flag_for_cards(body.flag, parse_ids(body.card_ids))
        return mutation(out.changes, count=out.count)
