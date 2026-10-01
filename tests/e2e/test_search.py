import pytest


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
    put = api.put("/browser/active-columns", json={"columns": ["noteFld", "deck", "noteTags"]})
    assert put.status_code == 200
    assert api.get("/browser/active-columns").json()["columns"] == ["noteFld", "deck", "noteTags"]


def test_find_replace(api):
    nid = api.make_note(deck="S", front="colour", back="x")["id"]
    out = api.post("/search/find-replace", json={
        "note_ids": [nid], "search": "colour", "replacement": "color",
    }).json()
    assert out["count"] == 1
    assert api.get(f"/notes/{nid}").json()["fields"]["Front"] == "color"


def _fronts(api, card_ids: list[str]) -> list[str]:
    return [api.get(f"/notes/{api.get(f'/cards/{cid}').json()['note_id']}").json()["fields"]["Front"]
            for cid in card_ids]


def test_search_order_sorts_by_a_browser_column_and_reverse_reverses_it(api):
    """`reverse` used to be accepted and do nothing: with no order the backend returns the
    ids unsorted, and the test here asserted only that both directions held the same set."""
    for front in ("bravo", "alpha", "charlie"):  # deliberately not created in sorted order
        api.make_note(deck="S", front=front)

    asc = api.post("/search/cards", json={"query": "deck:S", "order": "noteFld"}).json()["card_ids"]
    assert _fronts(api, asc) == ["alpha", "bravo", "charlie"]
    desc = api.post("/search/cards", json={"query": "deck:S", "order": "noteFld", "reverse": True}).json()["card_ids"]
    assert _fronts(api, desc) == ["charlie", "bravo", "alpha"]

    notes = api.post("/search/notes", json={"query": "deck:S", "order": "noteFld", "reverse": True}).json()["note_ids"]
    assert [api.get(f"/notes/{nid}").json()["fields"]["Front"] for nid in notes] == ["charlie", "bravo", "alpha"]


@pytest.mark.parametrize("endpoint", ["/search/cards", "/search/notes"])
@pytest.mark.parametrize("body", [
    {"query": "", "reverse": True},                 # nothing to reverse without an order
    {"query": "", "order": "nopeColumn"},           # not a browser column
    {"query": "", "order": "question"},             # a column, but not a sortable one
])
def test_search_order_that_cannot_be_honoured_is_422(api, endpoint, body):
    api.make_note(deck="S", front="a")
    assert api.post(endpoint, json=body).status_code == 422


def test_active_columns_are_kept_per_mode(api):
    api.put("/browser/active-columns", json={"columns": ["noteFld", "deck"], "mode": "cards"})
    out = api.put("/browser/active-columns", json={"columns": ["noteFld", "noteTags"], "mode": "notes"})
    assert out.status_code == 200
    assert out.json() == {"mode": "notes", "columns": ["noteFld", "noteTags"]}
    assert api.get("/browser/active-columns", params={"mode": "cards"}).json()["columns"] == ["noteFld", "deck"]
    assert api.get("/browser/active-columns", params={"mode": "notes"}).json()["columns"] == ["noteFld", "noteTags"]


def test_active_columns_unknown_mode_is_422(api):
    """Anything that was not "cards" used to be treated as "notes": a mistyped mode read, and
    on PUT overwrote, the notes-mode columns."""
    notes_before = api.get("/browser/active-columns", params={"mode": "notes"}).json()["columns"]
    assert api.get("/browser/active-columns", params={"mode": "card"}).status_code == 422
    assert api.put("/browser/active-columns", json={"columns": ["noteFld"], "mode": "card"}).status_code == 422
    assert api.get("/browser/active-columns", params={"mode": "notes"}).json()["columns"] == notes_before


def test_active_columns_unknown_column_is_422(api):
    """An unknown key used to be stored, and every row then rendered an empty cell for it."""
    before = api.get("/browser/active-columns").json()["columns"]
    assert api.put("/browser/active-columns", json={"columns": ["noteFld", "nopeColumn"]}).status_code == 422
    assert api.get("/browser/active-columns").json()["columns"] == before
