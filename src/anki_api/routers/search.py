"""Search / Browse endpoints [core] + configurable browser columns [parity].

The Anki search DSL is passed through verbatim to the Rust backend. The browse
contract: search returns the full ordered id list (held client-side); the client
then fetches rendered rows for a visible *window* of ids via /browser/rows. This
enables virtualized tables with no server cursor. Rows render the *active*
columns (configurable like the desktop browser), produced by browser_row_for_id.
"""

from __future__ import annotations

from anki.collection import BrowserConfig
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_ids
from ..schemas.common import mutation

router = APIRouter(tags=["search"])


class Search(BaseModel):
    query: str
    reverse: bool = False


class BrowserRows(BaseModel):
    card_ids: list[str]


class ActiveColumns(BaseModel):
    columns: list[str]
    mode: str = "cards"


class FindReplace(BaseModel):
    note_ids: list[str]
    search: str
    replacement: str
    regex: bool = False
    fold_case: bool = True
    field_name: str | None = None


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


@router.get("/browser/columns")
def browser_columns(handle: CollectionHandle = Depends(get_handle)) -> list[dict]:
    """All available browser columns, with their card/note-mode labels."""
    with handle.locked() as col:
        return [
            {
                "key": c.key,
                "cards_label": c.cards_mode_label,
                "notes_label": c.notes_mode_label,
                "sortable_cards": c.sorting_cards != 0,
                "sortable_notes": c.sorting_notes != 0,
            }
            for c in col.all_browser_columns()
        ]


@router.get("/browser/active-columns")
def get_active_columns(mode: str = "cards", handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        cols = col.load_browser_card_columns() if mode == "cards" else col.load_browser_note_columns()
        return {"mode": mode, "columns": list(cols)}


@router.put("/browser/active-columns")
def set_active_columns(body: ActiveColumns, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Persist the active columns for the given mode (stored in collection config)."""
    with handle.locked() as col:
        if body.mode == "cards":
            col.set_config(BrowserConfig.ACTIVE_CARD_COLUMNS_KEY, body.columns)
            cols = col.load_browser_card_columns()
        else:
            col.set_config(BrowserConfig.ACTIVE_NOTE_COLUMNS_KEY, body.columns)
            cols = col.load_browser_note_columns()
        return {"mode": body.mode, "columns": list(cols)}


@router.post("/browser/rows")
def browser_rows(body: BrowserRows, handle: CollectionHandle = Depends(get_handle)) -> list[dict]:
    """Rendered rows for a window of card ids, with cells aligned to the active
    card-mode columns (client slices the full id list to a visible window)."""
    with handle.locked() as col:
        col.load_browser_card_columns()  # ensure card-mode rendering
        rows = []
        for cid in parse_ids(body.card_ids):
            card = col.get_card(cid)
            cells_gen, color, font_name, font_size = col.browser_row_for_id(cid)
            rows.append(
                {
                    "card_id": str(cid),
                    "note_id": str(card.nid),
                    "cells": [text for (text, _rtl, _elide) in cells_gen],
                    "color": int(color),
                    "font_name": font_name,
                    "font_size": font_size,
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
