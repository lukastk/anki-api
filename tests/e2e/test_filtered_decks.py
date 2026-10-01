"""Filtered decks & custom study [parity]."""


def test_create_filtered_gathers_cards(api):
    for i in range(3):
        api.make_note(deck="Src", front=f"q{i}")
    out = api.post("/filtered-decks", json={"name": "Filt", "search": "deck:Src"}).json()
    assert out["count"] == 3
    fid = out["id"]
    # the gathered cards now live in the filtered deck
    assert api.post("/search/cards", json={"query": f'deck:Filt'}).json()["count"] == 3


def test_rebuild_and_empty(api):
    api.make_note(deck="Src", front="x")
    fid = api.post("/filtered-decks", json={"name": "F", "search": "deck:Src"}).json()["id"]
    rebuilt = api.post(f"/filtered-decks/{fid}/rebuild").json()
    assert rebuilt["count"] == 1
    assert api.post("/search/cards", json={"query": "deck:F"}).json()["count"] == 1
    emptied = api.post(f"/filtered-decks/{fid}/empty").json()
    assert "changes" in emptied
    # after emptying, the filtered deck holds no cards
    assert api.post("/search/cards", json={"query": "deck:F"}).json()["count"] == 0


def test_create_filtered_invalid_search_is_400(api):
    assert api.post("/filtered-decks", json={"name": "Bad", "search": "("}).status_code == 400


def test_custom_study_bad_mode_is_422(api):
    did = api.make_deck("CS")
    assert api.post("/filtered-decks/custom-study", json={
        "deck_id": did, "mode": "bogus", "value": 10,
    }).status_code == 422


def test_custom_study_increase_new(api):
    api.make_note(deck="CS", front="a")
    did = next(d["id"] for d in api.get("/decks").json() if d["name"] == "CS")
    resp = api.post("/filtered-decks/custom-study", json={
        "deck_id": did, "mode": "new_limit", "value": 10,
    })
    # succeeds, or cleanly reports no cards available (409) — never 500
    assert resp.status_code in (200, 409)


def test_custom_study_new_limit_raises_todays_new_count(api):
    did = api.make_deck("CS")
    for i in range(3):
        api.make_note(deck="CS", front=f"q{i}")
    api.put("/deck-presets/1", json={"new": {"perDay": 1}})
    assert api.get("/review/counts", params={"deck": "CS"}).json()["new"] == 1
    resp = api.post("/filtered-decks/custom-study", json={"deck_id": did, "mode": "new_limit", "value": 1})
    assert resp.status_code == 200
    assert api.get("/review/counts", params={"deck": "CS"}).json()["new"] == 2


def test_create_filtered_honours_the_limit(api):
    for i in range(3):
        api.make_note(deck="Src", front=f"q{i}")
    out = api.post("/filtered-decks", json={"name": "Two", "search": "deck:Src", "limit": 2}).json()
    assert out["count"] == 2
    assert api.post("/search/cards", json={"query": "deck:Two"}).json()["count"] == 2


def test_create_filtered_unknown_order_is_422(api):
    """`order` is an index into anki's filtered-deck orders (0-9); 99 used to be stored as given."""
    api.make_note(deck="Src", front="q")
    decks_before = api.get("/decks").json()
    assert api.post("/filtered-decks", json={"name": "Bad", "search": "deck:Src", "order": 99}).status_code == 422
    assert api.get("/decks").json() == decks_before
