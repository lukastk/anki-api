"""Note endpoints [core]: create, get, update, delete, and a note's cards.

Notetypes are referenced by name in v1 (the notetypes router is [parity], later).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id
from ..schemas.common import Mutation, mutation

router = APIRouter(prefix="/notes", tags=["notes"])


class CreateNote(BaseModel):
    deck: str
    notetype: str = "Basic"
    fields: dict[str, str]
    tags: list[str] = []


class CreatedNote(Mutation):
    """Create response: the mutation envelope (id = note id) plus the generated cards."""

    card_ids: list[str] = []


class UpdateNote(BaseModel):
    fields: dict[str, str] | None = None
    tags: list[str] | None = None


def _note_view(col, note) -> dict:
    notetype = note.note_type()
    return {
        "id": str(note.id),
        "notetype": notetype["name"] if notetype else None,
        "notetype_id": str(note.mid),
        "fields": dict(note.items()),
        "tags": list(note.tags),
        "card_ids": [str(c.id) for c in note.cards()],
    }


def _apply_fields(note, fields: dict[str, str]) -> None:
    for name, value in fields.items():
        if name not in note:
            raise HTTPException(status_code=422, detail=f"field {name!r} not in notetype")
        note[name] = value


@router.post("")
def create_note(body: CreateNote, handle: CollectionHandle = Depends(get_handle)) -> CreatedNote:
    with handle.locked() as col:
        notetype = col.models.by_name(body.notetype)
        if notetype is None:
            raise HTTPException(status_code=404, detail=f"notetype {body.notetype!r} not found")
        did = col.decks.id(body.deck)  # create-or-get
        note = col.new_note(notetype)
        _apply_fields(note, body.fields)
        note.tags = list(body.tags)
        out = col.add_note(note, did)
        m = mutation(out.changes, id=note.id)
        return CreatedNote(id=m.id, count=m.count, changes=m.changes,
                           card_ids=[str(c.id) for c in note.cards()])


@router.get("/find-duplicates")
def find_duplicates(field: str, search: str = "", handle: CollectionHandle = Depends(get_handle)) -> list[dict]:
    """Notes sharing the same value in `field` (Notes > Find Duplicates)."""
    with handle.locked() as col:
        return [
            {"value": value, "note_ids": [str(nid) for nid in nids]}
            for value, nids in col.find_dupes(field, search)
        ]


@router.get("/{note_id}")
def get_note(note_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    nid = parse_id(note_id)
    with handle.locked() as col:
        note = col.get_note(nid)  # raises NotFoundError if missing
        return _note_view(col, note)


@router.put("/{note_id}")
def update_note(note_id: str, body: UpdateNote, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(note_id)
    with handle.locked() as col:
        note = col.get_note(nid)
        if body.fields is not None:
            _apply_fields(note, body.fields)
        if body.tags is not None:
            note.tags = list(body.tags)
        return mutation(col.update_note(note))


@router.delete("/{note_id}")
def delete_note(note_id: str, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(note_id)
    with handle.locked() as col:
        out = col.remove_notes([nid])
        return mutation(out.changes, count=out.count)


@router.get("/{note_id}/cards")
def note_cards(note_id: str, handle: CollectionHandle = Depends(get_handle)) -> list[str]:
    nid = parse_id(note_id)
    with handle.locked() as col:
        note = col.get_note(nid)
        return [str(c.id) for c in note.cards()]
