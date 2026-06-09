def test_search_cards_and_notes(api):
    a = api.make_note(deck="S", front="alpha", back="1")
    api.make_note(deck="S", front="beta", back="2")

    cards = api.post("/search/cards", json={"query": "deck:S"}).json()
    assert cards["count"] == 2
    assert a["card_ids"][0] in cards["card_ids"]

    notes = api.post("/search/notes", json={"query": "front:alpha"}).json()
    assert notes["count"] == 1
    assert notes["note_ids"] == [a["id"]]


def test_browser_rows_render_active_columns(api):
    api.make_note(deck="S", front="What is 2+2?", back="4")
    ids = api.post("/search/cards", json={"query": "deck:S"}).json()["card_ids"]
    rows = api.post("/browser/rows", json={"card_ids": ids}).json()
    row = rows[0]
    assert row["card_id"] == ids[0]
    # cells are rendered text (no HTML/CSS leakage) aligned to active columns
    assert "What is 2+2?" in row["cells"]
    assert "S" in row["cells"]  # the deck column
    assert not any("font-family" in c for c in row["cells"])


def test_browser_columns_and_active_columns(api):
    columns = api.get("/browser/columns").json()
    keys = {c["key"] for c in columns}
    assert {"noteFld", "deck", "cardDue"} <= keys

    active = api.get("/browser/active-columns").json()
    assert active["mode"] == "cards"
    assert isinstance(active["columns"], list) and active["columns"]

    # set a custom column set and read it back
    api.put("/browser/active-columns", json={"columns": ["noteFld", "deck", "tags"]})
    assert api.get("/browser/active-columns").json()["columns"] == ["noteFld", "deck", "tags"]


def test_find_replace(api):
    nid = api.make_note(deck="S", front="colour", back="x")["id"]
    out = api.post("/search/find-replace", json={
        "note_ids": [nid], "search": "colour", "replacement": "color",
    }).json()
    assert out["count"] == 1
    assert api.get(f"/notes/{nid}").json()["fields"]["Front"] == "color"


def test_search_reverse_returns_same_set(api):
    # Configurable sort columns are [parity]; v1 only exposes `reverse`. Assert it
    # returns the same result set (ordering semantics covered by the browser work).
    api.make_note(deck="S", front="a")
    api.make_note(deck="S", front="b")
    fwd = api.post("/search/cards", json={"query": "deck:S", "reverse": False}).json()["card_ids"]
    rev = api.post("/search/cards", json={"query": "deck:S", "reverse": True}).json()["card_ids"]
    assert set(fwd) == set(rev)
    assert len(fwd) == 2
