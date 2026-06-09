"""Review (scheduler) endpoints [core]: counts, the next due card, answering, set-due-date.

The answer flow uses an opaque `review_token` — the base64 of the card's
serialized SchedulingStates handed out by /review/next — passed back to
/review/answer. This threads the exact states through (avoiding a queue-shift
race) and keeps any future custom-scheduling `key` intact.
"""

from __future__ import annotations

import base64
import re

from anki.scheduler_pb2 import CardAnswer, SchedulingStates
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id, parse_ids
from ..schemas.common import Mutation, mutation

router = APIRouter(prefix="/review", tags=["review"])

_ISOLATES = re.compile("[⁨⁩]")  # bidi marks Anki wraps interval labels in
_RATINGS = {
    "again": CardAnswer.AGAIN,
    "hard": CardAnswer.HARD,
    "good": CardAnswer.GOOD,
    "easy": CardAnswer.EASY,
}
_BUTTON_ORDER = ("again", "hard", "good", "easy")


class Answer(BaseModel):
    card_id: str
    rating: str
    review_token: str
    time_taken_ms: int | None = None


class SetDueDate(BaseModel):
    card_ids: list[str]
    days: str  # Anki's set-due-date DSL, e.g. "0", "1", "3-7", "1!"


def _encode_states(states: SchedulingStates) -> str:
    return base64.b64encode(states.SerializeToString()).decode("ascii")


def _decode_states(token: str) -> SchedulingStates:
    try:
        return SchedulingStates.FromString(base64.b64decode(token))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid review_token")


@router.get("/counts")
def counts(deck: str | None = None, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        if deck:
            col.decks.select(col.decks.id(deck))
        new, learn, review = col.sched.counts()
        return {"new": new, "learn": learn, "review": review}


@router.get("/next")
def next_card(deck: str | None = None, handle: CollectionHandle = Depends(get_handle)) -> dict | None:
    """The next card due for review, or null if the queue is empty."""
    with handle.locked() as col:
        if deck:
            col.decks.select(col.decks.id(deck))
        queued = col.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards:
            return None
        entry = queued.cards[0]
        card = col.get_card(entry.card.id)
        labels = [_ISOLATES.sub("", s) for s in col.sched.describe_next_states(entry.states)]
        return {
            "card_id": str(card.id),
            "note_id": str(card.nid),
            "question": card.question(),
            "answer": card.answer(),
            "buttons": dict(zip(_BUTTON_ORDER, labels)),
            "review_token": _encode_states(entry.states),
        }


@router.post("/answer")
def answer(body: Answer, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    if body.rating not in _RATINGS:
        raise HTTPException(status_code=422, detail=f"rating must be one of {list(_RATINGS)}")
    states = _decode_states(body.review_token)
    cid = parse_id(body.card_id)
    with handle.locked() as col:
        card = col.get_card(cid)
        card.start_timer()  # required headless before build_answer (see exp 01)
        ans = col.sched.build_answer(card=card, states=states, rating=_RATINGS[body.rating])
        if body.time_taken_ms is not None:
            ans.milliseconds_taken = body.time_taken_ms
        return mutation(col.sched.answer_card(ans))


@router.post("/set-due-date")
def set_due_date(body: SetDueDate, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        return mutation(col.sched.set_due_date(parse_ids(body.card_ids), body.days))
