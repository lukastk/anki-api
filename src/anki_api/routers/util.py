"""UI-chrome helpers [parity].

A full client needs Anki's own locale-aware duration formatting (answer buttons,
intervals, stats) and server-side markdown rendering (deck/preset descriptions),
rather than reimplementing them divergently.
"""

from __future__ import annotations

from anki import i18n_pb2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle

router = APIRouter(tags=["util"])

_TIMESPAN_CONTEXTS = {
    "precise": i18n_pb2.FormatTimespanRequest.PRECISE,
    "answer_buttons": i18n_pb2.FormatTimespanRequest.ANSWER_BUTTONS,
    "intervals": i18n_pb2.FormatTimespanRequest.INTERVALS,
}


class FormatTimespan(BaseModel):
    seconds: float
    context: str = "intervals"


class RenderMarkdown(BaseModel):
    markdown: str
    sanitize: bool = True


@router.post("/format/timespan")
def format_timespan(body: FormatTimespan, handle: CollectionHandle = Depends(get_handle)) -> dict:
    if body.context not in _TIMESPAN_CONTEXTS:
        raise HTTPException(status_code=422, detail=f"context must be one of {list(_TIMESPAN_CONTEXTS)}")
    with handle.locked() as col:
        text = col.format_timespan(body.seconds, _TIMESPAN_CONTEXTS[body.context])
        return {"text": text}


@router.post("/render/markdown")
def render_markdown(body: RenderMarkdown, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        return {"html": col.render_markdown(body.markdown, body.sanitize)}
