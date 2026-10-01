"""Search / Browse endpoints [core] + configurable browser columns [parity].

The Anki search DSL is passed through verbatim to the Rust backend. The browse
contract: search returns the full ordered id list (held client-side); the client
then fetches rendered rows for a visible *window* of ids via /browser/rows. This
enables virtualized tables with no server cursor. Rows render the *active*
columns (configurable like the desktop browser), produced by browser_row_for_id.
"""

from __future__ import annotations

from typing import Literal

from anki.collection import BrowserColumns, BrowserConfig
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_ids
from ..schemas.common import mutation

router = APIRouter(tags=["search"])


BrowserMode = Literal["cards", "notes"]


class Search(BaseModel):
    query: str
    order: str | None = None  # a sortable column key from GET /browser/columns; null = unsorted
    reverse: bool = False  # reverse `order` (meaningless, and refused, without one)


class BrowserRows(BaseModel):
    card_ids: list[str]


class ActiveColumns(BaseModel):
    columns: list[str]
    mode: BrowserMode = "cards"


class FindReplace(BaseModel):
    note_ids: list[str]
    search: str
    replacement: str
    regex: bool = False
    fold_case: bool = True
    field_name: str | None = None


def _sort_order(col, body: Search, mode: BrowserMode) -> BrowserColumns.Column | Literal[False]:
    """The `order` argument for `find_cards` / `find_notes`: the browser column to sort by,
    or False for an unsorted search. 422 for an order the backend cannot honour.

    The check is here because Anki's `_build_sort_mode` does not make it: handed a column
    that is not sortable (or anything else it does not recognise) it prints "is not a valid
    sort order" and searches UNSORTED. And `reverse` only ever reverses an order — with
    none, the backend never sees it; this endpoint used to accept it and do nothing."""
    if body.order is None:
        if body.reverse:
            raise HTTPException(status_code=422, detail="reverse needs an order to reverse; pass a sortable column key as `order`")
        return False
    column = col.get_browser_column(body.order)
    if column is None:
        raise HTTPException(status_code=422, detail=f"unknown browser column {body.order!r}; see GET /browser/columns")
    sorting = column.sorting_cards if mode == "cards" else column.sorting_notes
    if sorting == BrowserColumns.SORTING_NONE:
        raise HTTPException(status_code=422, detail=f"browser column {body.order!r} is not sortable in {mode} mode")
    return column


@router.post("/search/cards")
def search_cards(body: Search, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Card ids matching the Anki search `query`, sorted by the browser column `order` if given (`reverse` flips it), unsorted otherwise."""
    with handle.locked() as col:
        ids = col.find_cards(body.query, order=_sort_order(col, body, "cards"), reverse=body.reverse)
        return {"card_ids": [str(i) for i in ids], "count": len(ids)}


@router.post("/search/notes")
def search_notes(body: Search, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Note ids matching the Anki search `query`, sorted by the browser column `order` if given (`reverse` flips it), unsorted otherwise."""
    with handle.locked() as col:
        ids = col.find_notes(body.query, order=_sort_order(col, body, "notes"), reverse=body.reverse)
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
def get_active_columns(mode: BrowserMode = "cards", handle: CollectionHandle = Depends(get_handle)) -> dict:
    """The active browser columns for `mode` (cards | notes)."""
    with handle.locked() as col:
        cols = col.load_browser_card_columns() if mode == "cards" else col.load_browser_note_columns()
        return {"mode": mode, "columns": list(cols)}


@router.put("/browser/active-columns")
def set_active_columns(body: ActiveColumns, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Persist the active columns for the given mode (stored in collection config). 422 for a key that is not a browser column."""
    with handle.locked() as col:
        known = {c.key for c in col.all_browser_columns()}
        unknown = [key for key in body.columns if key not in known]
        if unknown:
            # stored as given, an unknown key renders as an empty cell in every row
            raise HTTPException(status_code=422, detail=f"unknown browser columns {unknown}; see GET /browser/columns")
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
