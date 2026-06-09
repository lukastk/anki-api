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
