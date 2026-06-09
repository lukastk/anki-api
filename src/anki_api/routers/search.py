"""Search / Browse endpoints [core].

The Anki search DSL is passed through verbatim to the Rust backend. The browse
contract (per the surface doc): search returns the full ordered id list (held
client-side); the client then fetches rendered rows for a visible *window* of
ids via /browser/rows. This enables virtualized tables with no server cursor.

Full configurable browser columns are [parity] (later); v1 returns a compact
per-card summary for the window.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_ids
from ..schemas.common import mutation

router = APIRouter(tags=["search"])

_BLOCKS = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class Search(BaseModel):
    query: str
    reverse: bool = False


class BrowserRows(BaseModel):
    card_ids: list[str]


class FindReplace(BaseModel):
    note_ids: list[str]
    search: str
    replacement: str
    regex: bool = False
    fold_case: bool = True
    field_name: str | None = None


def _strip(html: str) -> str:
    return _WS.sub(" ", _TAGS.sub("", _BLOCKS.sub("", html))).strip()


@router.post("/search/cards")
def search_cards(body: Search, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        ids = col.find_cards(body.query, reverse=body.reverse)
        return {"card_ids": [str(i) for i in ids], "count": len(ids)}


@router.post("/search/notes")
def search_notes(body: Search, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        ids = col.find_notes(body.query, reverse=body.reverse)
        return {"note_ids": [str(i) for i in ids], "count": len(ids)}


@router.post("/browser/rows")
def browser_rows(body: BrowserRows, handle: CollectionHandle = Depends(get_handle)) -> list[dict]:
    """Compact rendered summary for a window of card ids (client slices the id list)."""
    with handle.locked() as col:
        rows = []
        for cid in parse_ids(body.card_ids):
            card = col.get_card(cid)
            rows.append(
                {
                    "card_id": str(card.id),
                    "note_id": str(card.nid),
                    "deck": col.decks.name(card.did),
                    "question": _strip(card.question()),
                    "answer": _strip(card.answer()),
                    "due": card.due,
                    "flag": card.user_flag(),
                }
            )
        return rows


@router.post("/search/find-replace")
def find_replace(body: FindReplace, handle: CollectionHandle = Depends(get_handle)):
    with handle.locked() as col:
        out = col.find_and_replace(
            note_ids=parse_ids(body.note_ids),
            search=body.search,
            replacement=body.replacement,
            regex=body.regex,
            match_case=not body.fold_case,
            field_name=body.field_name,
        )
        return mutation(out.changes, count=out.count)
