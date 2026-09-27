"""Card endpoints [core]: get a card, card-info HTML, and bulk actions
(suspend/bury/set-deck/set-flag) on a card-id selection."""

from __future__ import annotations

from anki.utils import ids2str
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


class PatchCard(BaseModel):
    interval: int | None = Field(default=None, ge=0, description="interval in days (ivl)")
    factor: int | None = Field(default=None, ge=0, description="ease per-mille, e.g. 2500")
    reps: int | None = Field(default=None, ge=0)
    lapses: int | None = Field(default=None, ge=0)


REVLOG_BOUNDS_CHUNK = 5000
"""Card ids per `revlog` query in `_review_bounds`. The ids are inlined into the SQL
(`ids2str`, as Anki's own code does), so SQLite's bound-variable limit is not in play; the
chunk only keeps one statement's text bounded for a very large selection."""


def _review_bounds(col, cids: list[int]) -> dict[int, tuple[int, int]]:
    """card id → (first, latest) revlog entry time in epoch SECONDS, for every card in
    `cids` that has a revlog row at all — one grouped query per chunk of ids, never a query
    per card.

    The numbers are the ones `GET /v1/stats/card/{id}` (`Collection.card_stats_data`)
    reports as `first_review` / `latest_review`, so a caller can check one against the
    other: revlog ids are milliseconds, floored to seconds, over EVERY row of the card's
    revlog — MANUAL rows (revlog `type` 4: set-due-date, forget) included, because Anki's
    own card info counts them (verified on a card rescheduled before it was ever answered:
    `card_stats_data` reports `first_review` set and `reviews` 0). So `first_review` is the
    first time the scheduler touched the card, which is the first time it was shown for
    every card the learner answered before anyone rescheduled it; a caller that needs
    "has the learner answered it" reads `reps`, and one that needs the rows themselves
    reads the stats endpoint's `revlog`."""
    out: dict[int, tuple[int, int]] = {}
    for start in range(0, len(cids), REVLOG_BOUNDS_CHUNK):
        chunk = cids[start:start + REVLOG_BOUNDS_CHUNK]
        rows = col.db.all(f"select cid, min(id) / 1000, max(id) / 1000 from revlog where cid in {ids2str(chunk)} group by cid")
        for cid, first, latest in rows:
            out[cid] = (first, latest)
    return out


def _card_view(card, review_bounds: tuple[int, int] | None) -> dict:
    """One card's view. `review_bounds` is `_review_bounds(...)` for this card, or None when
    it has no revlog row, in which case `first_review` and `latest_review` are null."""
    first_review, latest_review = review_bounds if review_bounds is not None else (None, None)
    return {
        "id": str(card.id),
        "note_id": str(card.nid),
        "deck_id": str(card.did),
        "ord": card.ord,
        "queue": card.queue,
        "type": card.type,
        "due": card.due,
        "interval": card.ivl,
        "factor": card.factor,
        "reps": card.reps,
        "lapses": card.lapses,
        "flag": card.user_flag(),
        "first_review": first_review,
        "latest_review": latest_review,
        "question": card.question(),
        "answer": card.answer(),
    }


@router.post("/views")
def card_views(body: CardIds, handle: CollectionHandle = Depends(get_handle)) -> list[dict]:
    """Bulk card views for a card-id selection, with each card's first_review/latest_review (epoch seconds, null when never reviewed).

    Avoids N round-trips — e.g. when snapshotting scheduling state for a whole search, or
    when replaying the order a learner met a deck's cards: `first_review` and
    `latest_review` are the same numbers `GET /v1/stats/card/{id}` reports (MANUAL revlog
    rows included, see `_review_bounds`), computed for the whole selection with one grouped
    query against the revlog rather than one stats call per card."""
    with handle.locked() as col:
        cids = parse_ids(body.card_ids)
        bounds = _review_bounds(col, cids)
        return [_card_view(col.get_card(cid), bounds.get(cid)) for cid in cids]


@router.get("/{card_id}")
def get_card(card_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """One card's view — the same shape as an element of POST /cards/views, first_review/latest_review included."""
    cid = parse_id(card_id)
    with handle.locked() as col:
        return _card_view(col.get_card(cid), _review_bounds(col, [cid]).get(cid))


@router.patch("/{card_id}")
def patch_card(card_id: str, body: PatchCard, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    """Write scheduling columns directly (mutate-then-update_card). Meant for
    restoring scheduling onto recreated cards; an incremental (non-schema) change.
    `due`/`queue`/`type` are deliberately NOT writable here — use
    /review/set-due-date, which converts state safely."""
    cid = parse_id(card_id)
    with handle.locked() as col:
        card = col.get_card(cid)
        if body.interval is not None:
            card.ivl = body.interval
        if body.factor is not None:
            card.factor = body.factor
        if body.reps is not None:
            card.reps = body.reps
        if body.lapses is not None:
            card.lapses = body.lapses
        return mutation(col.update_card(card))


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
