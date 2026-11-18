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
from anki.utils import ids2str
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id, parse_ids
from ..schemas.common import Mutation, RequestModel, mutation

router = APIRouter(prefix="/notetypes", tags=["notetypes"])


# --- request models ---

class NewTemplate(RequestModel):
    name: str
    qfmt: str
    afmt: str


class CreateNotetype(RequestModel):
    name: str
    stock: str = "Basic"
    # Extra fields to include AT creation. Adding a brand-new notetype is an
    # incrementally-syncable change, but add_field on an existing notetype modifies
    # the schema (forces a full sync) — so callers that want extra fields should
    # pass them here and get a fully-formed notetype in one schema-neutral op.
    fields: list[str] = []
    # Optional exact final order, including the stock fields. This is applied to the
    # in-memory notetype before its one add_dict(), so an editor-first field does not
    # cost a later schema-changing reposition.
    field_order: list[str] | None = None
    # Name, not index: the caller's order above decides the final index.
    sort_field: str | None = None
    # Card templates to include AT creation, for the same reason and with the same
    # payoff: add_template on an existing notetype modifies the schema, creation does
    # not, so a notetype that needs several card templates has to be born with them.
    # These REPLACE the stock notetype's own template, in the order given, so the
    # caller owns the ordinals (templates[0] is ord 0). Omit the key to keep the
    # stock's; an empty list is refused rather than read as "no cards at all".
    templates: list[NewTemplate] | None = None


class CloneNotetype(RequestModel):
    name: str


class PatchNotetype(RequestModel):
    name: str | None = None
    css: str | None = None
    sort_field_index: int | None = None


class AddField(RequestModel):
    name: str


class RenameField(RequestModel):
    new_name: str


class Reposition(RequestModel):
    index: int


class AddTemplate(RequestModel):
    name: str
    qfmt: str
    afmt: str


class UpdateTemplate(RequestModel):
    qfmt: str | None = None
    afmt: str | None = None


class ChangeInfo(RequestModel):
    old_notetype_id: str
    new_notetype_id: str


class ChangeNotetype(RequestModel):
    note_ids: list[str]
    old_notetype_id: str
    new_notetype_id: str
    new_fields: list[int] | None = None
    new_templates: list[int] | None = None


class ChangeIdenticalNotetype(RequestModel):
    note_ids: list[str]
    expected_source_notetype_id: str
    target_notetype_id: str


class ChangeMappedNotetype(RequestModel):
    note_ids: list[str]
    expected_source_notetype_id: str
    target_notetype_id: str
    # Every TARGET field, by name -> the SOURCE field that fills it, or null to start it empty.
    field_map: dict[str, str | None]
    # A source field with text may be dropped only when named here. Empty unaccounted fields are safe.
    discard_fields: list[str]
    # Every TARGET template, by name -> the SOURCE template whose card it keeps, or null for no old card.
    template_map: dict[str, str | None]
    # A source template that has a card may be dropped only when named here.
    discard_templates: list[str] = []


class ChangedMappedNote(BaseModel):
    note_id: str
    card_ids: list[str]


class ChangeMappedResult(Mutation):
    schema_modified: bool  # the collection's scm moved during the change
    full_sync_required: bool  # scm > ls afterwards: the next sync must be a full one
    notes: list[ChangedMappedNote]  # actual note/card ids read after Anki's native operation


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
        # Checked before anything is applied, as in patch_notetype: a request that half-built
        # a notetype and then raised would leave the caller guessing which half landed.
        if body.templates is not None:
            names = [t.name for t in body.templates]
            if not names:
                raise HTTPException(
                    status_code=422,
                    detail="templates must not be empty: a notetype has at least one card template",
                )
            if len(set(names)) != len(names):
                raise HTTPException(status_code=422, detail=f"duplicate template name in {names}")
            if nt["type"] == MODEL_CLOZE and len(names) > 1:
                raise HTTPException(
                    status_code=422,
                    detail=f"a cloze notetype has exactly one card template, asked for {len(names)}",
                )
        # Extra fields and templates are added to the in-memory dict BEFORE add_dict, so the
        # whole creation is one incremental (non-schema-modifying) operation.
        for field_name in body.fields:
            col.models.add_field(nt, col.models.new_field(field_name))
        field_names = [field["name"] for field in nt["flds"]]
        if body.field_order is not None:
            if len(body.field_order) != len(field_names) or set(body.field_order) != set(field_names):
                raise HTTPException(
                    status_code=422,
                    detail=f"field_order must contain exactly {field_names}, got {body.field_order}",
                )
            by_name = {field["name"]: field for field in nt["flds"]}
            nt["flds"] = [by_name[name] for name in body.field_order]
            for index, field in enumerate(nt["flds"]):
                field["ord"] = index
            field_names = list(body.field_order)
        if body.sort_field is not None:
            if body.sort_field not in field_names:
                raise HTTPException(
                    status_code=422,
                    detail=f"sort_field {body.sort_field!r} is not one of {field_names}",
                )
            nt["sortf"] = field_names.index(body.sort_field)
        if body.templates is not None:
            nt["tmpls"] = []
            for spec in body.templates:
                tmpl = col.models.new_template(spec.name)
                tmpl["qfmt"] = spec.qfmt
                tmpl["afmt"] = spec.afmt
                col.models.add_template(nt, tmpl)
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
        # checked before anything is applied: `nt` is anki's cached dict, so a PATCH that
        # set the name and then failed here would leave the unsaved name in the cache
        if body.sort_field_index is not None and not 0 <= body.sort_field_index < len(nt["flds"]):
            raise HTTPException(status_code=422, detail=f"sort_field_index must be within 0..{len(nt['flds']) - 1}")
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
        _get(col, nid)  # 404 if missing; anki removes an unknown id without complaint
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

@router.post("/actions/change-identical")
def change_identical_notetype(
    body: ChangeIdenticalNotetype, handle: CollectionHandle = Depends(get_handle),
) -> Mutation:
    """Move explicitly named notes only between byte-identical notetype schemas.

    This migration-safe form validates every note's current notetype and compares
    ordered fields, templates, CSS and type before calling Anki's native operation.
    """
    note_ids = parse_ids(body.note_ids)
    if not note_ids:
        raise HTTPException(status_code=422, detail="note_ids must not be empty")
    if len(note_ids) != len(set(note_ids)):
        raise HTTPException(status_code=422, detail="note_ids contains duplicates")
    old_id = parse_id(body.expected_source_notetype_id)
    new_id = parse_id(body.target_notetype_id)
    if old_id == new_id:
        raise HTTPException(status_code=422, detail="source and target notetype must differ")
    with handle.locked() as col:
        old, new = _get(col, old_id), _get(col, new_id)
        old_view, new_view = _view(old), _view(new)
        schema_keys = ("type", "sort_field_index", "css", "fields", "templates")
        if any(old_view[key] != new_view[key] for key in schema_keys):
            raise HTTPException(
                status_code=409, detail="source and target fields, templates, CSS, or type differ",
            )
        rows = dict(col.db.all(f"select id, mid from notes where id in {ids2str(note_ids)}"))
        missing = next((nid for nid in note_ids if nid not in rows), None)
        if missing is not None:
            raise HTTPException(status_code=404, detail=f"note {missing} not found")
        wrong = next((nid for nid in note_ids if rows[nid] != old_id), None)
        if wrong is not None:
            raise HTTPException(
                status_code=409,
                detail=f"note {wrong} has notetype {rows[wrong]}, expected source {old_id}",
            )
        info = col.models.change_notetype_info(old_notetype_id=old_id, new_notetype_id=new_id)
        req = info.input
        req.note_ids[:] = note_ids
        req.new_fields[:] = range(len(new_view["fields"]))
        req.new_templates[:] = range(len(new_view["templates"]))
        return mutation(col.models.change_notetype_of_notes(req), count=len(note_ids))


@router.post("/actions/change-mapped")
def change_mapped_notetype(
    body: ChangeMappedNotetype, handle: CollectionHandle = Depends(get_handle),
) -> ChangeMappedResult:
    """Move explicitly named notes to a notetype with a different schema, by explicit name maps.

    Every target field is named (filled from one source field, or empty); every source field is mapped or
    listed in `discard_fields`; templates map one-to-one, so card ids, scheduling and revlog are kept and no
    card is deleted or generated. Every note must be on the expected source. All checks run before Anki's
    native change, which is a single operation. A notetype change modifies the schema: the result reports
    `schema_modified` and `full_sync_required` as read from the collection before and after.
    """
    note_ids = parse_ids(body.note_ids)
    if not note_ids:
        raise HTTPException(status_code=422, detail="note_ids must not be empty")
    if len(note_ids) != len(set(note_ids)):
        raise HTTPException(status_code=422, detail="note_ids contains duplicates")
    old_id = parse_id(body.expected_source_notetype_id)
    new_id = parse_id(body.target_notetype_id)
    if old_id == new_id:
        raise HTTPException(status_code=422, detail="source and target notetype must differ")
    with handle.locked() as col:
        old, new = _get(col, old_id), _get(col, new_id)
        if old["type"] != new["type"]:
            raise HTTPException(status_code=422, detail="source and target differ in type (standard/cloze)")
        old_fields = [f["name"] for f in old["flds"]]
        new_fields = [f["name"] for f in new["flds"]]
        old_tmpls = [t["name"] for t in old["tmpls"]]
        new_tmpls = [t["name"] for t in new["tmpls"]]

        if set(body.field_map) != set(new_fields):
            raise HTTPException(status_code=422, detail=(
                f"field_map must name every target field exactly: missing {sorted(set(new_fields) - set(body.field_map))}, "
                f"not on the target {sorted(set(body.field_map) - set(new_fields))}"))
        sources = [s for s in body.field_map.values() if s is not None]
        unknown = sorted(set(sources) - set(old_fields))
        if unknown:
            raise HTTPException(status_code=422, detail=f"field_map names source fields the source lacks: {unknown}")
        twice = sorted({s for s in sources if sources.count(s) > 1})
        if twice:
            raise HTTPException(status_code=422, detail=f"source fields mapped more than once: {twice}")
        discard = list(body.discard_fields)
        if len(discard) != len(set(discard)) or set(discard) - set(old_fields):
            raise HTTPException(status_code=422, detail=f"discard_fields must be distinct source fields: {discard}")
        both = sorted(set(discard) & set(sources))
        if both:
            raise HTTPException(status_code=422, detail=f"fields both mapped and discarded: {both}")

        if set(body.template_map) != set(new_tmpls):
            raise HTTPException(status_code=422, detail=(
                f"template_map must name every target template exactly: missing "
                f"{sorted(set(new_tmpls) - set(body.template_map))}, not on the target "
                f"{sorted(set(body.template_map) - set(new_tmpls))}"))
        template_sources = [s for s in body.template_map.values() if s is not None]
        unknown_templates = sorted(set(template_sources) - set(old_tmpls))
        if unknown_templates:
            raise HTTPException(status_code=422, detail=(
                f"template_map names source templates the source lacks: {unknown_templates}"))
        repeated_templates = sorted({s for s in template_sources if template_sources.count(s) > 1})
        if repeated_templates:
            raise HTTPException(status_code=422, detail=(
                f"source templates mapped more than once: {repeated_templates}"))
        discard_templates = list(body.discard_templates)
        if (len(discard_templates) != len(set(discard_templates))
                or set(discard_templates) - set(old_tmpls)):
            raise HTTPException(status_code=422, detail=(
                f"discard_templates must be distinct source templates: {discard_templates}"))
        templates_both = sorted(set(discard_templates) & set(template_sources))
        if templates_both:
            raise HTTPException(status_code=422, detail=(
                f"templates both mapped and discarded: {templates_both}"))

        rows = dict(col.db.all(f"select id, mid from notes where id in {ids2str(note_ids)}"))
        missing = next((nid for nid in note_ids if nid not in rows), None)
        if missing is not None:
            raise HTTPException(status_code=404, detail=f"note {missing} not found")
        wrong = next((nid for nid in note_ids if rows[nid] != old_id), None)
        if wrong is not None:
            raise HTTPException(
                status_code=409,
                detail=f"note {wrong} has notetype {rows[wrong]}, expected source {old_id}",
            )

        unaccounted_fields = [field for field in old_fields if field not in sources and field not in discard]
        for note_id in note_ids:
            note = col.get_note(note_id)
            holding_text = [field for field in unaccounted_fields if note[field]]
            if holding_text:
                raise HTTPException(status_code=409, detail=(
                    f"note {note_id} has text in source field(s) {holding_text} that the map drops; "
                    "name them in discard_fields to authorize losing that text"))

        card_rows = col.db.all(f"select id, nid, ord from cards where nid in {ids2str(note_ids)}")
        unaccounted_templates = [
            template for template in old_tmpls
            if template not in template_sources and template not in discard_templates
        ]
        cards_by_unaccounted_template = {
            template: [str(card_id) for card_id, _note_id, ord_ in card_rows
                       if ord_ == old_tmpls.index(template)]
            for template in unaccounted_templates
        }
        cards_by_unaccounted_template = {
            template: card_ids for template, card_ids in cards_by_unaccounted_template.items() if card_ids
        }
        if cards_by_unaccounted_template:
            raise HTTPException(status_code=409, detail=(
                f"source template(s) have cards that the map drops: {cards_by_unaccounted_template}; "
                "name them in discard_templates to authorize deleting those cards"))

        info = col.models.change_notetype_info(old_notetype_id=old_id, new_notetype_id=new_id)
        req = info.input
        req.note_ids[:] = note_ids
        req.new_fields[:] = [
            -1 if body.field_map[name] is None else old_fields.index(body.field_map[name]) for name in new_fields
        ]
        req.new_templates[:] = [
            -1 if body.template_map[name] is None else old_tmpls.index(body.template_map[name]) for name in new_tmpls
        ]
        scm_before = col.db.scalar("select scm from col")
        changes = col.models.change_notetype_of_notes(req)
        scm_after = col.db.scalar("select scm from col")
        ls = col.db.scalar("select ls from col")
        result = mutation(changes, count=len(note_ids))
        changed = [
            ChangedMappedNote(
                note_id=str(note_id),
                card_ids=[str(card_id) for card_id in col.db.list(
                    "select id from cards where nid = ? order by ord, id", note_id
                )],
            )
            for note_id in note_ids
        ]
        return ChangeMappedResult(**result.model_dump(), schema_modified=scm_after != scm_before,
                                  full_sync_required=scm_after > ls, notes=changed)


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
