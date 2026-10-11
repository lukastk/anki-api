def test_create_and_get(api):
    created = api.make_note(front="capital of France?", back="Paris", tags=["geo"])
    assert created["changes"]["note"] is True
    assert len(created["card_ids"]) == 1

    note = api.get(f"/notes/{created['id']}").json()
    assert note["fields"] == {"Front": "capital of France?", "Back": "Paris"}
    assert note["tags"] == ["geo"]
    assert note["notetype"] == "Basic"
    assert note["card_ids"] == created["card_ids"]


def test_update_fields_and_tags(api):
    nid = api.make_note(front="q", back="a")["id"]
    out = api.put(f"/notes/{nid}", json={"fields": {"Front": "Q!", "Back": "A!"}, "tags": ["x", "y"]}).json()
    assert out["changes"]["note"] is True
    note = api.get(f"/notes/{nid}").json()
    assert note["fields"]["Front"] == "Q!"
    assert note["tags"] == ["x", "y"]


def test_partial_update_tags_only_keeps_fields(api):
    nid = api.make_note(front="keep", back="me")["id"]
    api.put(f"/notes/{nid}", json={"tags": ["only"]})
    note = api.get(f"/notes/{nid}").json()
    assert note["fields"]["Front"] == "keep"
    assert note["tags"] == ["only"]


def test_note_cards_endpoint(api):
    created = api.make_note()
    cards = api.get(f"/notes/{created['id']}/cards").json()
    assert cards == created["card_ids"]


def test_delete(api):
    nid = api.make_note()["id"]
    out = api.delete(f"/notes/{nid}").json()
    assert out["count"] == 1
    assert api.get(f"/notes/{nid}").status_code == 404


# --- POST /notes/views ------------------------------------------------------------------

def test_views_is_the_single_read_for_each_note_in_the_order_asked(api):
    """Each element is byte-for-byte what GET /notes/{id} returns, in request order (not id
    order); a note with two cards and tags shows both, and an unrequested note is absent."""
    first = api.make_note(front="a", back="1", tags=["t1"])["id"]
    second = api.post("/notes", json={"deck": "T", "notetype": "Basic (and reversed card)",
                                      "fields": {"Front": "b", "Back": "2"}, "tags": ["x", "y"]}).json()["id"]
    third = api.make_note(front="c", back="3")["id"]
    unrequested = api.make_note(front="d", back="4")["id"]
    asked = [third, first, second]
    out = api.post("/notes/views", json={"note_ids": asked})
    assert out.status_code == 200, out.text
    notes = out.json()["notes"]
    assert [n["id"] for n in notes] == asked
    assert notes == [api.get(f"/notes/{nid}").json() for nid in asked]
    assert len(notes[2]["card_ids"]) == 2 and notes[2]["tags"] == ["x", "y"]
    assert unrequested not in {n["id"] for n in notes}


def test_views_single_note_matches_the_single_read(api):
    nid = api.make_note(front="only", back="one", tags=["solo"])["id"]
    assert api.post("/notes/views", json={"note_ids": [nid]}).json() == {"notes": [api.get(f"/notes/{nid}").json()]}


def test_views_unknown_id_is_404_naming_it(api):
    nid = api.make_note()["id"]
    out = api.post("/notes/views", json={"note_ids": [nid, "777777777"]})
    assert out.status_code == 404
    assert "777777777" in out.text


def test_views_bad_id_is_400(api):
    assert api.post("/notes/views", json={"note_ids": ["abc"]}).status_code == 400


def test_views_empty_list_is_empty(api):
    api.make_note()
    assert api.post("/notes/views", json={"note_ids": []}).json() == {"notes": []}


def test_views_cap_is_1000(api):
    nid = api.make_note()["id"]
    at_cap = api.post("/notes/views", json={"note_ids": [nid] * 1000})
    assert at_cap.status_code == 200 and len(at_cap.json()["notes"]) == 1000
    over = api.post("/notes/views", json={"note_ids": [nid] * 1001})
    assert over.status_code == 400
    assert "1000" in over.text
