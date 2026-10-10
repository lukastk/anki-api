"""FSRS controls [parity]: enable/disable + parameter optimization/evaluation.

Per-preset FSRS params (desiredRetention, fsrsParams*) are edited via the
deck-presets router; this router covers the collection-wide toggle and the
compute/evaluate operations that need review history.
"""

from __future__ import annotations

from google.protobuf.json_format import MessageToDict
from fastapi import APIRouter, Depends, HTTPException

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_ids
from ..schemas.common import Mutation, RequestModel, mutation

router = APIRouter(prefix="/fsrs", tags=["fsrs"])


class SetEnabled(RequestModel):
    enabled: bool


class ComputeParams(RequestModel):
    search: str
    current_params: list[float] = []
    ignore_revlogs_before_ms: int = 0
    num_of_relearning_steps: int = 0
    health_check: bool = False


class MemoryState(RequestModel):
    card_ids: list[str]


class EvaluateParams(RequestModel):
    search: str
    ignore_revlogs_before_ms: int = 0
    num_of_relearning_steps: int = 0


@router.get("")
def get_fsrs(handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        return {"enabled": bool(col.get_config("fsrs", False))}


@router.put("")
def set_fsrs(body: SetEnabled, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        return mutation(col.set_config("fsrs", body.enabled))


@router.post("/compute-params")
def compute_params(body: ComputeParams, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Optimize FSRS parameters from review history. Returns an empty params list
    when there is insufficient history (a legitimate result, not an error)."""
    with handle.locked() as col:
        resp = col._backend.compute_fsrs_params(
            search=body.search,
            current_params=body.current_params,
            ignore_revlogs_before_ms=body.ignore_revlogs_before_ms,
            num_of_relearning_steps=body.num_of_relearning_steps,
            health_check=body.health_check,
        )
        return {"params": list(resp.params)}


@router.post("/evaluate")
def evaluate(body: EvaluateParams, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Evaluate current params against review history (400 if history is too thin)."""
    with handle.locked() as col:
        resp = col._backend.evaluate_params(
            search=body.search,
            ignore_revlogs_before_ms=body.ignore_revlogs_before_ms,
            num_of_relearning_steps=body.num_of_relearning_steps,
        )
        return MessageToDict(resp, preserving_proto_field_name=True)


@router.post("/memory-state")
def memory_state(body: MemoryState, handle: CollectionHandle = Depends(get_handle)) -> list[dict]:
    """Recompute each card's FSRS memory state from its review log (the backend's
    compute_memory_state) and STORE it on the card, with the desired retention and decay
    it was computed for. A card with no usable history gets a null state, stored as null.
    409 when FSRS is off; 404 for an unknown card, before any card is written."""
    cids = parse_ids(body.card_ids)
    with handle.locked() as col:
        if not col.get_config("fsrs", False):
            raise HTTPException(status_code=409, detail="FSRS is not enabled on this collection")
        cards = [col.get_card(cid) for cid in cids]
        for card in cards:
            resp = col._backend.compute_memory_state(card.id)
            card.memory_state = resp.state if resp.HasField("state") else None
            card.desired_retention = resp.desired_retention
            card.decay = resp.decay
        col.update_cards(cards)
        # Report what was STORED: the backend rounds the state on write (stability to 4
        # decimals, difficulty to 3), so the computed floats are not what the card holds.
        out = []
        for cid in cids:
            card = col.get_card(cid)
            state = card.memory_state
            out.append({
                "card_id": str(cid),
                "stability": state.stability if state is not None else None,
                "difficulty": state.difficulty if state is not None else None,
                "desired_retention": card.desired_retention,
                "decay": card.decay,
            })
        return out
