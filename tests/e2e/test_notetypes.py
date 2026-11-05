"""Notetypes & templates [parity] — written tests-first against the planned contract.

Contract:
  GET    /notetypes                      -> [{id,name}]
  GET    /notetypes/stock                -> [name]
  GET    /notetypes/{id}                 -> {id,name,type,sort_field_index,css,fields[],templates[]}
  POST   /notetypes                      {name, stock="Basic"} -> Mutation(id=new notetype id)
  POST   /notetypes/{id}/clone           {name} -> Mutation(id=new id)
  PATCH  /notetypes/{id}                 {name?, css?, sort_field_index?} -> Mutation
  DELETE /notetypes/{id}                 -> Mutation
  POST   /notetypes/{id}/fields          {name} -> Mutation
  POST   /notetypes/{id}/fields/{name}/rename     {new_name} -> Mutation
  POST   /notetypes/{id}/fields/{name}/reposition {index} -> Mutation
  DELETE /notetypes/{id}/fields/{name}   -> Mutation
  POST   /notetypes/{id}/templates       {name, qfmt, afmt} -> Mutation
  PUT    /notetypes/{id}/templates/{name} {qfmt?, afmt?} -> Mutation
  POST   /notetypes/{id}/templates/{name}/reposition {index} -> Mutation
  DELETE /notetypes/{id}/templates/{name} -> Mutation
  POST   /notetypes/change-info          {old_notetype_id, new_notetype_id} -> mapping info
  POST   /notetypes/change               {note_ids, old_notetype_id, new_notetype_id, ...} -> Mutation
"""


def _id_by_name(api, name: str) -> str:
    return next(n["id"] for n in api.get("/notetypes").json() if n["name"] == name)


# --- listing / reading ---

def test_list_includes_builtins(api):
    names = {n["name"] for n in api.get("/notetypes").json()}
    assert {"Basic", "Cloze"} <= names


def test_stock_list(api):
    stock = api.get("/notetypes/stock").json()
    assert "Basic" in stock and "Cloze" in stock and "Image Occlusion" in stock


def test_get_basic_shape(api):
    nt = api.get(f"/notetypes/{_id_by_name(api, 'Basic')}").json()
    assert nt["name"] == "Basic"
    assert nt["type"] == "standard"
    assert [f["name"] for f in nt["fields"]] == ["Front", "Back"]
    assert len(nt["templates"]) == 1
    assert "{{" in nt["templates"][0]["qfmt"]
    assert isinstance(nt["css"], str)


def test_get_cloze_is_cloze_type(api):
    nt = api.get(f"/notetypes/{_id_by_name(api, 'Cloze')}").json()
    assert nt["type"] == "cloze"


def test_get_missing_is_404(api):
    assert api.get("/notetypes/123456").status_code == 404


# --- create / clone / update / delete ---

def test_create_from_stock(api):
    out = api.post("/notetypes", json={"name": "MyCloze", "stock": "Cloze"}).json()
    assert out["id"]
    assert out["changes"]["notetype"] is True
    nt = api.get(f"/notetypes/{out['id']}").json()
    assert nt["name"] == "MyCloze"
    assert nt["type"] == "cloze"


def test_create_defaults_to_basic(api):
    out = api.post("/notetypes", json={"name": "PlainNew"}).json()
    nt = api.get(f"/notetypes/{out['id']}").json()
    assert [f["name"] for f in nt["fields"]] == ["Front", "Back"]


def test_create_with_extra_fields(api):
    """Extra fields are included AT creation (one incremental op — no schema bump;
    the sync e2e proves the schema semantics)."""
    out = api.post("/notetypes", json={"name": "WithHidden", "fields": ["h_id", "h_meta"]}).json()
    nt = api.get(f"/notetypes/{out['id']}").json()
    assert [f["name"] for f in nt["fields"]] == ["Front", "Back", "h_id", "h_meta"]


def test_create_unknown_stock_is_400(api):
    assert api.post("/notetypes", json={"name": "X", "stock": "Nope"}).status_code == 400


# --- templates at creation ---
#
# Adding a template to an EXISTING notetype modifies the schema and forces a full sync, while
# creating a notetype does not. So a notetype that needs more than one card template has to be
# born with them, the same reason `fields` is accepted at creation.

_SLOW_FIELDS = ["Slow08", "Slow05"]
_AFMT = "{{FrontSide}}<hr id=answer>{{Back}}"
_LISTENING_TEMPLATES = [
    {"name": "1.0x", "qfmt": "{{Front}}", "afmt": _AFMT},
    {"name": "0.8x", "qfmt": "{{#Slow08}}{{Slow08}}{{/Slow08}}", "afmt": _AFMT},
    {"name": "0.5x", "qfmt": "{{#Slow05}}{{Slow05}}{{/Slow05}}", "afmt": _AFMT},
]


def _listening(name):
    return {"name": name, "fields": _SLOW_FIELDS, "templates": _LISTENING_TEMPLATES}


def test_create_with_templates_are_the_notetypes_own_templates_in_order(api):
    """Templates given at creation ARE the notetype's templates, replacing the stock one.

    The caller owns the ordinals: a listening notetype's full-speed card has to be ord 0, and
    appending to the stock template would leave "Card 1" at ord 0 generating a card nobody
    asked for.
    """
    out = api.post("/notetypes", json=_listening("ThreeCard"))
    assert out.status_code == 200, out.text
    nt = api.get(f"/notetypes/{out.json()['id']}").json()
    assert [t["name"] for t in nt["templates"]] == ["1.0x", "0.8x", "0.5x"]
    assert [f["name"] for f in nt["fields"]] == ["Front", "Back", "Slow08", "Slow05"]
    assert nt["templates"][0]["qfmt"] == "{{Front}}"


def test_create_with_templates_does_not_modify_the_schema(api):
    """The whole reason the parameter exists."""
    scm_before = api.get("/sync/health").json()["schema_modified"]
    assert api.post("/notetypes", json=_listening("ThreeCardScm")).status_code == 200
    assert api.get("/sync/health").json()["schema_modified"] == scm_before


def test_a_conditional_template_generates_its_card_only_once_its_field_is_filled(api):
    """A free creation whose later field write cost a full sync would be no gain, so the write
    that generates the siblings is measured too."""
    api.post("/notetypes", json=_listening("ThreeCardGen"))
    note = api.post("/notes", json={
        "deck": "D", "notetype": "ThreeCardGen",
        "fields": {"Front": "f", "Back": "b", "Slow08": "", "Slow05": ""},
    }).json()
    assert len(note["card_ids"]) == 1

    scm_before = api.get("/sync/health").json()["schema_modified"]
    api.put(f"/notes/{note['id']}", json={"fields": {
        "Front": "f", "Back": "b", "Slow08": "[sound:slow08.mp3]", "Slow05": "[sound:slow05.mp3]",
    }})
    after = api.get(f"/notes/{note['id']}").json()
    assert len(after["card_ids"]) == 3
    assert api.get("/sync/health").json()["schema_modified"] == scm_before
    for card_id in after["card_ids"]:
        card = api.get(f"/cards/{card_id}").json()
        assert card["type"] == 0 and card["queue"] == 0


def test_create_with_an_empty_templates_list_is_422(api):
    """`templates` absent means "the stock notetype's own"; `templates: []` would mean a
    notetype with no card template at all, which is not a thing."""
    body = {"name": "NoTmpl", "templates": []}
    assert api.post("/notetypes", json=body).status_code == 422


def test_create_with_a_duplicate_template_name_is_422(api):
    body = {"name": "DupTmpl", "templates": [
        {"name": "same", "qfmt": "{{Front}}", "afmt": _AFMT},
        {"name": "same", "qfmt": "{{Back}}", "afmt": _AFMT},
    ]}
    assert api.post("/notetypes", json=body).status_code == 422


def test_create_a_cloze_with_several_templates_is_422(api):
    """A cloze notetype has exactly one template, whatever the caller asks for.

    The detail is asserted, not just the status: anki refuses this by itself further down, so a
    test that only checked for 422 passed with this guard disabled and proved nothing about it.
    """
    # The two fronts differ: anki refuses two templates with IDENTICAL fronts whatever the
    # notetype, which is what this test was accidentally proving before.
    body = {"name": "ClozeMany", "stock": "Cloze", "templates": [
        {"name": "a", "qfmt": "{{cloze:Text}}", "afmt": "{{cloze:Text}}"},
        {"name": "b", "qfmt": "second: {{cloze:Text}}", "afmt": "{{cloze:Text}}"},
    ]}
    out = api.post("/notetypes", json=body)
    assert out.status_code == 422, out.text
    assert "exactly one card template" in out.text, out.text


def test_clone(api):
    src = _id_by_name(api, "Basic")
    out = api.post(f"/notetypes/{src}/clone", json={"name": "BasicCopy"}).json()
    assert out["id"] != src
    nt = api.get(f"/notetypes/{out['id']}").json()
    assert nt["name"] == "BasicCopy"
    assert [f["name"] for f in nt["fields"]] == ["Front", "Back"]


def test_update_css_and_name(api):
    nid = api.post("/notetypes", json={"name": "Styled"}).json()["id"]
    out = api.patch(f"/notetypes/{nid}", json={"css": ".card { color: red; }", "name": "Restyled"}).json()
    assert out["changes"]["notetype"] is True
    nt = api.get(f"/notetypes/{nid}").json()
    assert nt["css"] == ".card { color: red; }"
    assert nt["name"] == "Restyled"


def test_set_sort_field_index(api):
    nid = api.post("/notetypes", json={"name": "Sorted"}).json()["id"]
    api.patch(f"/notetypes/{nid}", json={"sort_field_index": 1})
    assert api.get(f"/notetypes/{nid}").json()["sort_field_index"] == 1


def test_set_sort_field_index_out_of_range_is_422_and_changes_nothing(api):
    """Used to be a 500 — and the name/css in the same PATCH, already applied to anki's
    cached notetype, were then served by GET without ever having been saved."""
    nid = api.post("/notetypes", json={"name": "Sorted"}).json()["id"]
    resp = api.patch(f"/notetypes/{nid}", json={"name": "Renamed", "sort_field_index": 2})
    assert resp.status_code == 422
    nt = api.get(f"/notetypes/{nid}").json()
    assert (nt["name"], nt["sort_field_index"]) == ("Sorted", 0)


def test_delete(api):
    nid = api.post("/notetypes", json={"name": "Doomed"}).json()["id"]
    assert api.delete(f"/notetypes/{nid}").status_code == 200
    assert api.get(f"/notetypes/{nid}").status_code == 404


def test_delete_unknown_is_404(api):
    """Used to answer 200 with an all-false change set."""
    assert api.delete("/notetypes/123456").status_code == 404


# --- fields ---

def test_add_field_appears_on_notes(api):
    nid = api.post("/notetypes", json={"name": "WithExtra"}).json()["id"]
    out = api.post(f"/notetypes/{nid}/fields", json={"name": "Extra"}).json()
    assert out["changes"]["notetype"] is True
    nt = api.get(f"/notetypes/{nid}").json()
    assert [f["name"] for f in nt["fields"]] == ["Front", "Back", "Extra"]
    # a note of this type should now accept the new field
    note = api.post("/notes", json={
        "deck": "D", "notetype": "WithExtra", "fields": {"Front": "a", "Back": "b", "Extra": "c"},
    })
    assert note.status_code == 200


def test_rename_field(api):
    nid = api.post("/notetypes", json={"name": "Renamable"}).json()["id"]
    api.post(f"/notetypes/{nid}/fields/Back/rename", json={"new_name": "Reverse"})
    nt = api.get(f"/notetypes/{nid}").json()
    assert [f["name"] for f in nt["fields"]] == ["Front", "Reverse"]


def test_reposition_field(api):
    nid = api.post("/notetypes", json={"name": "Reorder"}).json()["id"]
    api.post(f"/notetypes/{nid}/fields/Back/reposition", json={"index": 0})
    nt = api.get(f"/notetypes/{nid}").json()
    assert [f["name"] for f in nt["fields"]] == ["Back", "Front"]


def test_remove_field(api):
    nid = api.post("/notetypes", json={"name": "Trimmable"}).json()["id"]
    api.post(f"/notetypes/{nid}/fields", json={"name": "Temp"})
    out = api.delete(f"/notetypes/{nid}/fields/Temp").json()
    assert out["changes"]["notetype"] is True
    nt = api.get(f"/notetypes/{nid}").json()
    assert "Temp" not in [f["name"] for f in nt["fields"]]


def test_remove_unknown_field_is_404(api):
    nid = api.post("/notetypes", json={"name": "NF"}).json()["id"]
    assert api.delete(f"/notetypes/{nid}/fields/Ghost").status_code == 404


# --- templates ---

def test_add_template_generates_cards(api):
    nid = api.post("/notetypes", json={"name": "TwoCard"}).json()["id"]
    note = api.post("/notes", json={"deck": "D", "notetype": "TwoCard", "fields": {"Front": "f", "Back": "b"}}).json()
    assert len(note["card_ids"]) == 1
    out = api.post(f"/notetypes/{nid}/templates", json={
        "name": "Card 2", "qfmt": "{{Back}}", "afmt": "{{Front}}",
    }).json()
    assert out["changes"]["notetype"] is True
    nt = api.get(f"/notetypes/{nid}").json()
    assert [t["name"] for t in nt["templates"]] == ["Card 1", "Card 2"]
    # existing note now has a second card
    assert len(api.get(f"/notes/{note['id']}").json()["card_ids"]) == 2


def test_update_template(api):
    nid = api.post("/notetypes", json={"name": "EditTmpl"}).json()["id"]
    api.put(f"/notetypes/{nid}/templates/Card 1", json={"qfmt": "Q: {{Front}}", "afmt": "A: {{Back}}"})
    tmpl = api.get(f"/notetypes/{nid}").json()["templates"][0]
    assert tmpl["qfmt"] == "Q: {{Front}}"
    assert tmpl["afmt"] == "A: {{Back}}"


def test_reposition_template(api):
    nid = api.post("/notetypes", json={"name": "ReorderTmpl"}).json()["id"]
    api.post(f"/notetypes/{nid}/templates", json={"name": "Card 2", "qfmt": "{{Back}}", "afmt": "{{Front}}"})
    api.post(f"/notetypes/{nid}/templates/Card 2/reposition", json={"index": 0})
    names = [t["name"] for t in api.get(f"/notetypes/{nid}").json()["templates"]]
    assert names == ["Card 2", "Card 1"]


def test_remove_template(api):
    nid = api.post("/notetypes", json={"name": "DelTmpl"}).json()["id"]
    api.post(f"/notetypes/{nid}/templates", json={"name": "Card 2", "qfmt": "{{Back}}", "afmt": "{{Front}}"})
    assert api.delete(f"/notetypes/{nid}/templates/Card 2").status_code == 200
    assert [t["name"] for t in api.get(f"/notetypes/{nid}").json()["templates"]] == ["Card 1"]


def test_remove_last_template_fails(api):
    nid = api.post("/notetypes", json={"name": "OneTmpl"}).json()["id"]
    assert api.delete(f"/notetypes/{nid}/templates/Card 1").status_code >= 400


# --- change notetype ---

def test_change_notetype_info(api):
    old = _id_by_name(api, "Basic")
    new = _id_by_name(api, "Basic (and reversed card)")
    info = api.post("/notetypes/change-info", json={"old_notetype_id": old, "new_notetype_id": new}).json()
    assert info["old_field_names"] == ["Front", "Back"]
    assert info["new_field_names"] == ["Front", "Back"]
    assert "Card 1" in info["new_template_names"]
    assert len(info["default_field_map"]) == 2


def test_change_notetype_remaps_and_regenerates_cards(api):
    note = api.make_note(deck="D", front="f", back="b")  # Basic, 1 card
    assert len(note["card_ids"]) == 1
    old = _id_by_name(api, "Basic")
    new = _id_by_name(api, "Basic (and reversed card)")
    out = api.post("/notetypes/change", json={
        "note_ids": [note["id"]], "old_notetype_id": old, "new_notetype_id": new,
    }).json()
    assert out["changes"]
    refetched = api.get(f"/notes/{note['id']}").json()
    assert refetched["notetype"] == "Basic (and reversed card)"
    assert len(refetched["card_ids"]) == 2  # reversed card generated


def test_change_notetype_applies_an_explicit_field_map(api):
    """`new_fields[i]` is the OLD field that fills new field i; the default map is the
    identity, so only a non-identity map shows the map is used at all."""
    note = api.make_note(deck="D", front="was-front", back="was-back")
    old = _id_by_name(api, "Basic")
    new = _id_by_name(api, "Basic (and reversed card)")
    api.post("/notetypes/change", json={
        "note_ids": [note["id"]], "old_notetype_id": old, "new_notetype_id": new, "new_fields": [1, 0],
    })
    assert api.get(f"/notes/{note['id']}").json()["fields"] == {"Front": "was-back", "Back": "was-front"}


def _note_on_cloned_basic(api, clone_name="ImportedBasic"):
    basic = _id_by_name(api, "Basic")
    cloned = api.post(f"/notetypes/{basic}/clone", json={"name": clone_name}).json()["id"]
    note = api.post("/notes", json={
        "deck": "D", "notetype": clone_name, "fields": {"Front": "f", "Back": "b"},
    }).json()
    return basic, cloned, note


def test_change_identical_moves_explicit_notes_without_changing_cards_or_history(api):
    basic, imported, note = _note_on_cloned_basic(api)
    card = note["card_ids"][0]
    api.post("/review/grade-now", json={"card_ids": [card], "rating": "good"})
    before_card = api.get(f"/cards/{card}").json()
    before_revlog = api.get("/revlog", params={"card_ids": card}).json()["entries"]

    out = api.post("/notetypes/actions/change-identical", json={
        "note_ids": [note["id"]],
        "expected_source_notetype_id": imported,
        "target_notetype_id": basic,
    })
    assert out.status_code == 200, out.text
    assert out.json()["count"] == 1
    assert api.get(f"/notes/{note['id']}").json()["notetype"] == "Basic"
    assert api.get(f"/cards/{card}").json() == before_card
    assert api.get("/revlog", params={"card_ids": card}).json()["entries"] == before_revlog


def test_change_identical_refuses_mixed_source_notetypes_atomically(api):
    basic, imported, source_note = _note_on_cloned_basic(api)
    other = api.make_note(deck="D", front="other")
    out = api.post("/notetypes/actions/change-identical", json={
        "note_ids": [source_note["id"], other["id"]],
        "expected_source_notetype_id": imported,
        "target_notetype_id": basic,
    })
    assert out.status_code == 409
    assert api.get(f"/notes/{source_note['id']}").json()["notetype"] == "ImportedBasic"


def test_change_identical_refuses_a_schema_difference(api):
    basic, imported, note = _note_on_cloned_basic(api)
    api.patch(f"/notetypes/{imported}", json={"css": ".card { color: red; }"})
    out = api.post("/notetypes/actions/change-identical", json={
        "note_ids": [note["id"]],
        "expected_source_notetype_id": imported,
        "target_notetype_id": basic,
    })
    assert out.status_code == 409
    assert api.get(f"/notes/{note['id']}").json()["notetype"] == "ImportedBasic"


# --- change-mapped: a field-mapping change that keeps cards and history, all-or-nothing ---

def _rsh_like(api):
    """A source notetype (cloned Basic with an extra field) and a target with two more fields."""
    basic = _id_by_name(api, "Basic")
    source = api.post(f"/notetypes/{basic}/clone", json={"name": "Src"}).json()["id"]
    assert api.post(f"/notetypes/{source}/fields", json={"name": "Story"}).status_code == 200
    target = api.post(f"/notetypes/{source}/clone", json={"name": "Dst"}).json()["id"]
    for name in ("Key", "Atoms"):
        assert api.post(f"/notetypes/{target}/fields", json={"name": name}).status_code == 200
    note = api.post("/notes", json={
        "deck": "D", "notetype": "Src", "fields": {"Front": "横", "Back": "horizontal", "Story": "tree and yellow"},
    }).json()
    return source, target, note


def _mapped_body(note_ids, source, target, **over):
    body = {
        "note_ids": note_ids, "expected_source_notetype_id": source, "target_notetype_id": target,
        "field_map": {"Front": "Front", "Back": "Back", "Story": "Story", "Key": None, "Atoms": None},
        "discard_fields": [], "template_map": {"Card 1": "Card 1"},
    }
    body.update(over)
    return body


def test_change_mapped_moves_notes_by_name_keeping_cards_history_and_scheduling(api):
    source, target, note = _rsh_like(api)
    card = note["card_ids"][0]
    api.post("/review/grade-now", json={"card_ids": [card], "rating": "good"})
    before_card = api.get(f"/cards/{card}").json()
    before_revlog = api.get("/revlog", params={"card_ids": card}).json()["entries"]

    scm_before = api.get("/sync/health").json()["schema_modified"]
    out = api.post("/notetypes/actions/change-mapped", json=_mapped_body([note["id"]], source, target))
    assert out.status_code == 200, out.text
    health = api.get("/sync/health").json()
    assert out.json()["count"] == 1
    # The report is read from the collection; it agrees with what /sync/health reads independently.
    assert health["schema_modified"] != scm_before
    assert out.json()["schema_modified"] is True
    assert out.json()["full_sync_required"] is health["schema_changed"] is True
    after = api.get(f"/notes/{note['id']}").json()
    assert after["notetype"] == "Dst"
    assert after["fields"] == {"Front": "横", "Back": "horizontal", "Story": "tree and yellow", "Key": "", "Atoms": ""}
    assert after["card_ids"] == [card]
    after_card = api.get(f"/cards/{card}").json()
    assert {k: v for k, v in after_card.items() if k not in ("notetype", "mtime", "usn")} == \
        {k: v for k, v in before_card.items() if k not in ("notetype", "mtime", "usn")}
    assert api.get("/revlog", params={"card_ids": card}).json()["entries"] == before_revlog


def test_change_mapped_follows_the_name_map_not_field_order(api):
    source, target, note = _rsh_like(api)
    body = _mapped_body([note["id"]], source, target,
                        field_map={"Front": "Back", "Back": "Front", "Story": None, "Key": "Story", "Atoms": None})
    assert api.post("/notetypes/actions/change-mapped", json=body).status_code == 200
    assert api.get(f"/notes/{note['id']}").json()["fields"] == {
        "Front": "horizontal", "Back": "横", "Story": "", "Key": "tree and yellow", "Atoms": ""}


def test_change_mapped_refuses_a_note_of_another_notetype_and_moves_nothing(api):
    source, target, note = _rsh_like(api)
    other = api.make_note(deck="D", front="other")
    out = api.post("/notetypes/actions/change-mapped", json=_mapped_body([note["id"], other["id"]], source, target))
    assert out.status_code == 409
    assert "expected source" in out.text
    assert api.get(f"/notes/{note['id']}").json()["notetype"] == "Src"


def test_change_mapped_refuses_a_target_field_the_map_does_not_name(api):
    source, target, note = _rsh_like(api)
    body = _mapped_body([note["id"]], source, target,
                        field_map={"Front": "Front", "Back": "Back", "Story": "Story", "Key": None})
    out = api.post("/notetypes/actions/change-mapped", json=body)
    assert out.status_code == 422
    assert "Atoms" in out.text
    assert api.get(f"/notes/{note['id']}").json()["notetype"] == "Src"


def test_change_mapped_refuses_a_source_field_neither_mapped_nor_discarded(api):
    source, target, note = _rsh_like(api)
    body = _mapped_body([note["id"]], source, target,
                        field_map={"Front": "Front", "Back": "Back", "Story": None, "Key": None, "Atoms": None})
    out = api.post("/notetypes/actions/change-mapped", json=body)
    assert out.status_code == 422
    assert "Story" in out.text
    body["discard_fields"] = ["Story"]
    assert api.post("/notetypes/actions/change-mapped", json=body).status_code == 200


def test_change_mapped_refuses_a_discarded_field_that_is_also_mapped(api):
    source, target, note = _rsh_like(api)
    out = api.post("/notetypes/actions/change-mapped",
                   json=_mapped_body([note["id"]], source, target, discard_fields=["Story"]))
    assert out.status_code == 422


def test_change_mapped_refuses_an_unknown_source_field_and_a_field_used_twice(api):
    source, target, note = _rsh_like(api)
    unknown = _mapped_body([note["id"]], source, target,
                           field_map={"Front": "Front", "Back": "Back", "Story": "Story", "Key": "Nope", "Atoms": None})
    assert api.post("/notetypes/actions/change-mapped", json=unknown).status_code == 422
    twice = _mapped_body([note["id"]], source, target,
                         field_map={"Front": "Front", "Back": "Back", "Story": "Story", "Key": "Front", "Atoms": None})
    out = api.post("/notetypes/actions/change-mapped", json=twice)
    assert out.status_code == 422
    assert "Front" in out.text
    assert api.get(f"/notes/{note['id']}").json()["notetype"] == "Src"


def test_change_mapped_refuses_a_template_map_that_would_delete_or_create_cards(api):
    source, target, note = _rsh_like(api)
    assert api.post(f"/notetypes/{target}/templates",
                    json={"name": "Card 2", "qfmt": "{{Back}}", "afmt": "{{Front}}"}).status_code == 200
    # the target's second template is not mapped: Anki would generate cards for it
    out = api.post("/notetypes/actions/change-mapped", json=_mapped_body([note["id"]], source, target))
    assert out.status_code == 422
    assert "Card 2" in out.text
    # every target template mapped, but from one source template twice
    out = api.post("/notetypes/actions/change-mapped", json=_mapped_body(
        [note["id"]], source, target, template_map={"Card 1": "Card 1", "Card 2": "Card 1"}))
    assert out.status_code == 422
    assert api.get(f"/notes/{note['id']}").json()["notetype"] == "Src"


def test_change_mapped_refuses_empty_or_duplicate_notes_and_one_notetype_for_both(api):
    source, target, note = _rsh_like(api)
    assert api.post("/notetypes/actions/change-mapped", json=_mapped_body([], source, target)).status_code == 422
    assert api.post("/notetypes/actions/change-mapped",
                    json=_mapped_body([note["id"], note["id"]], source, target)).status_code == 422
    assert api.post("/notetypes/actions/change-mapped",
                    json=_mapped_body([note["id"]], source, source)).status_code == 422
