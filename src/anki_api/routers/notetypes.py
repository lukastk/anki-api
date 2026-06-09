"""Notetype & template endpoints [parity].

Field/template mutators in anki are in-memory (new_field/add_field/rename_field/
add_template/...); they mutate the NotetypeDict, which we then persist with
update_dict() (-> OpChanges). Creating a notetype uses a stock template + add_dict.
Most of these ops modify the schema (forcing a full sync next time).
"""

from __future__ import annotations

import copy

from anki import stdmodels
from anki.consts import MODEL_CLOZE
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id, parse_ids
from ..schemas.common import Mutation, mutation

router = APIRouter(prefix="/notetypes", tags=["notetypes"])


# --- request models ---

class CreateNotetype(BaseModel):
    name: str
    stock: str = "Basic"


class CloneNotetype(BaseModel):
    name: str


class PatchNotetype(BaseModel):
    name: str | None = None
    css: str | None = None
    sort_field_index: int | None = None


class AddField(BaseModel):
    name: str


class RenameField(BaseModel):
    new_name: str


class Reposition(BaseModel):
    index: int


class AddTemplate(BaseModel):
    name: str
    qfmt: str
    afmt: str


class UpdateTemplate(BaseModel):
    qfmt: str | None = None
    afmt: str | None = None


class ChangeInfo(BaseModel):
    old_notetype_id: str
    new_notetype_id: str


class ChangeNotetype(BaseModel):
    note_ids: list[str]
    old_notetype_id: str
    new_notetype_id: str
    new_fields: list[int] | None = None
    new_templates: list[int] | None = None


# --- helpers ---

def _get(col, nid: int) -> dict:
    nt = col.models.get(nid)
    if nt is None:
        raise HTTPException(status_code=404, detail=f"notetype {nid} not found")
    return nt


def _find_field(nt: dict, name: str) -> dict:
    for field in nt["flds"]:
        if field["name"] == name:
            return field
    raise HTTPException(status_code=404, detail=f"field {name!r} not found")


def _find_template(nt: dict, name: str) -> dict:
    for tmpl in nt["tmpls"]:
        if tmpl["name"] == name:
            return tmpl
    raise HTTPException(status_code=404, detail=f"template {name!r} not found")


def _view(nt: dict) -> dict:
    return {
        "id": str(nt["id"]),
        "name": nt["name"],
        "type": "cloze" if nt["type"] == MODEL_CLOZE else "standard",
        "sort_field_index": nt["sortf"],
        "css": nt["css"],
        "fields": [
            {"name": f["name"], "ord": f["ord"], "sticky": f["sticky"],
             "rtl": f["rtl"], "font": f["font"], "size": f["size"], "description": f.get("description", "")}
            for f in nt["flds"]
        ],
        "templates": [
            {"name": t["name"], "ord": t["ord"], "qfmt": t["qfmt"], "afmt": t["afmt"]}
            for t in nt["tmpls"]
        ],
    }


# --- notetype CRUD ---

@router.get("")
def list_notetypes(handle: CollectionHandle = Depends(get_handle)) -> list[dict]:
    with handle.locked() as col:
        return [{"id": str(n.id), "name": n.name} for n in col.models.all_names_and_ids()]


@router.get("/stock")
def stock_notetypes(handle: CollectionHandle = Depends(get_handle)) -> list[str]:
    with handle.locked() as col:
        return [name for name, _ in stdmodels.get_stock_notetypes(col)]


@router.get("/{notetype_id}")
def get_notetype(notetype_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        return _view(_get(col, nid))


@router.get("/{notetype_id}/default-deck")
def default_deck(notetype_id: str, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """The deck last used with this notetype (Add screen picks it on notetype switch)."""
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        _get(col, nid)  # 404 if missing
        did = col.default_deck_for_notetype(nid)
        return {"deck_id": str(did) if did is not None else None}


@router.post("")
def create_notetype(body: CreateNotetype, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        stocks = dict(stdmodels.get_stock_notetypes(col))
        if body.stock not in stocks:
            raise HTTPException(status_code=400, detail=f"unknown stock notetype {body.stock!r}")
        nt = stocks[body.stock](col)
        nt["name"] = body.name
        out = col.models.add_dict(nt)
        return mutation(out.changes, id=out.id)


@router.post("/{notetype_id}/clone")
def clone_notetype(notetype_id: str, body: CloneNotetype, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        clone = copy.deepcopy(_get(col, nid))
        clone["id"] = 0  # let the backend assign a fresh id
        clone["name"] = body.name
        out = col.models.add_dict(clone)
        return mutation(out.changes, id=out.id)


@router.patch("/{notetype_id}")
def patch_notetype(notetype_id: str, body: PatchNotetype, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        nt = _get(col, nid)
        if body.name is not None:
            nt["name"] = body.name
        if body.css is not None:
            nt["css"] = body.css
        if body.sort_field_index is not None:
            col.models.set_sort_index(nt, body.sort_field_index)
        return mutation(col.models.update_dict(nt))


@router.delete("/{notetype_id}")
def delete_notetype(notetype_id: str, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        return mutation(col.models.remove(nid))


# --- fields ---

@router.post("/{notetype_id}/fields")
def add_field(notetype_id: str, body: AddField, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        nt = _get(col, nid)
        col.models.add_field(nt, col.models.new_field(body.name))
        return mutation(col.models.update_dict(nt))


@router.post("/{notetype_id}/fields/{field_name}/rename")
def rename_field(notetype_id: str, field_name: str, body: RenameField, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        nt = _get(col, nid)
        col.models.rename_field(nt, _find_field(nt, field_name), body.new_name)
        return mutation(col.models.update_dict(nt))


@router.post("/{notetype_id}/fields/{field_name}/reposition")
def reposition_field(notetype_id: str, field_name: str, body: Reposition, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        nt = _get(col, nid)
        col.models.reposition_field(nt, _find_field(nt, field_name), body.index)
        return mutation(col.models.update_dict(nt))


@router.delete("/{notetype_id}/fields/{field_name}")
def remove_field(notetype_id: str, field_name: str, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        nt = _get(col, nid)
        field = _find_field(nt, field_name)  # 404 if missing
        if len(nt["flds"]) <= 1:
            raise HTTPException(status_code=422, detail="a notetype must have at least one field")
        col.models.remove_field(nt, field)
        return mutation(col.models.update_dict(nt))


# --- templates ---

@router.post("/{notetype_id}/templates")
def add_template(notetype_id: str, body: AddTemplate, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        nt = _get(col, nid)
        tmpl = col.models.new_template(body.name)
        tmpl["qfmt"] = body.qfmt
        tmpl["afmt"] = body.afmt
        col.models.add_template(nt, tmpl)
        return mutation(col.models.update_dict(nt))


@router.put("/{notetype_id}/templates/{template_name}")
def update_template(notetype_id: str, template_name: str, body: UpdateTemplate, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        nt = _get(col, nid)
        tmpl = _find_template(nt, template_name)
        if body.qfmt is not None:
            tmpl["qfmt"] = body.qfmt
        if body.afmt is not None:
            tmpl["afmt"] = body.afmt
        return mutation(col.models.update_dict(nt))


@router.post("/{notetype_id}/templates/{template_name}/reposition")
def reposition_template(notetype_id: str, template_name: str, body: Reposition, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        nt = _get(col, nid)
        col.models.reposition_template(nt, _find_template(nt, template_name), body.index)
        return mutation(col.models.update_dict(nt))


@router.delete("/{notetype_id}/templates/{template_name}")
def remove_template(notetype_id: str, template_name: str, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    nid = parse_id(notetype_id)
    with handle.locked() as col:
        nt = _get(col, nid)
        tmpl = _find_template(nt, template_name)  # 404 if missing
        if len(nt["tmpls"]) <= 1:
            raise HTTPException(status_code=422, detail="a notetype must have at least one template")
        col.models.remove_template(nt, tmpl)
        return mutation(col.models.update_dict(nt))


# --- change notetype ---

@router.post("/change-info")
def change_info(body: ChangeInfo, handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        info = col.models.change_notetype_info(
            old_notetype_id=parse_id(body.old_notetype_id),
            new_notetype_id=parse_id(body.new_notetype_id),
        )
        return {
            "old_field_names": list(info.old_field_names),
            "new_field_names": list(info.new_field_names),
            "old_template_names": list(info.old_template_names),
            "new_template_names": list(info.new_template_names),
            "default_field_map": list(info.input.new_fields),
            "default_template_map": list(info.input.new_templates),
            "is_cloze": info.input.is_cloze,
        }


@router.post("/change")
def change_notetype(body: ChangeNotetype, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        # change_notetype_info pre-fills current_schema, is_cloze and default maps;
        # we override note_ids and (optionally) the field/template maps.
        info = col.models.change_notetype_info(
            old_notetype_id=parse_id(body.old_notetype_id),
            new_notetype_id=parse_id(body.new_notetype_id),
        )
        req = info.input
        req.note_ids[:] = parse_ids(body.note_ids)
        if body.new_fields is not None:
            req.new_fields[:] = body.new_fields
        if body.new_templates is not None:
            req.new_templates[:] = body.new_templates
        return mutation(col.models.change_notetype_of_notes(req))
