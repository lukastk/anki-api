"""Type-in-the-answer support [blocker for reviewer parity].

Backs `{{type:Field}}` / `{{type:cloze:Field}}` template cards: compare the typed
answer to the expected value (returns the colored diff HTML Anki renders), and
extract the expected text for a cloze-typing card.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle

router = APIRouter(tags=["typing"])


class CompareAnswer(BaseModel):
    expected: str
    provided: str
    combining: bool = True


class ExtractCloze(BaseModel):
    text: str
    ordinal: int


@router.post("/scheduler/compare-answer")
def compare_answer(body: CompareAnswer, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        html = col.compare_answer(body.expected, body.provided, body.combining)
        return {"comparison_html": html}


@router.post("/notes/extract-cloze-for-typing")
def extract_cloze_for_typing(body: ExtractCloze, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        return {"text": col.extract_cloze_for_typing(body.text, body.ordinal)}
