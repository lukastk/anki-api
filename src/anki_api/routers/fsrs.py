"""FSRS controls [parity]: enable/disable + parameter optimization/evaluation.

Per-preset FSRS params (desiredRetention, fsrsParams*) are edited via the
deck-presets router; this router covers the collection-wide toggle and the
compute/evaluate operations that need review history.
"""

from __future__ import annotations

from google.protobuf.json_format import MessageToDict
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..schemas.common import Mutation, mutation

router = APIRouter(prefix="/fsrs", tags=["fsrs"])


class SetEnabled(BaseModel):
    enabled: bool


class ComputeParams(BaseModel):
    search: str
    current_params: list[float] = []
    ignore_revlogs_before_ms: int = 0
    num_of_relearning_steps: int = 0
    health_check: bool = False


class EvaluateParams(BaseModel):
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
