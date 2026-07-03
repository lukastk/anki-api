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

import pytest


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


def test_delete(api):
    nid = api.post("/notetypes", json={"name": "Doomed"}).json()["id"]
    assert api.delete(f"/notetypes/{nid}").status_code == 200
    assert api.get(f"/notetypes/{nid}").status_code == 404


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
