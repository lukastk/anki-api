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
    assert "count" in rebuilt
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
