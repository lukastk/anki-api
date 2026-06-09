def test_search_cards_and_notes(api):
    a = api.make_note(deck="S", front="alpha", back="1")
    api.make_note(deck="S", front="beta", back="2")

    cards = api.post("/search/cards", json={"query": "deck:S"}).json()
    assert cards["count"] == 2
    assert a["card_ids"][0] in cards["card_ids"]

    notes = api.post("/search/notes", json={"query": "front:alpha"}).json()
    assert notes["count"] == 1
    assert notes["note_ids"] == [a["id"]]


def test_browser_rows_summary_strips_styling(api):
    api.make_note(deck="S", front="What is 2+2?", back="4")
    ids = api.post("/search/cards", json={"query": "deck:S"}).json()["card_ids"]
    rows = api.post("/browser/rows", json={"card_ids": ids}).json()
    assert rows[0]["deck"] == "S"
    # the rendered question must not leak the template <style> CSS
    assert "font-family" not in rows[0]["question"]
    assert rows[0]["question"] == "What is 2+2?"


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
