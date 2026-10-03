import pytest

from anki_api.routers import cards as cards_router


@pytest.fixture
def card_id(api):
    return api.make_note(front="q", back="a")["card_ids"][0]


def test_get_card_view(api, card_id):
    card = api.get(f"/cards/{card_id}").json()
    assert card["id"] == card_id
    assert card["reps"] == 0
    assert card["flag"] == 0
    assert "q" in card["question"]


def test_set_flag(api, card_id):
    out = api.post("/cards/actions/set-flag", json={"card_ids": [card_id], "flag": 2}).json()
    assert out["count"] == 1
    assert api.get(f"/cards/{card_id}").json()["flag"] == 2
    # clear
    api.post("/cards/actions/set-flag", json={"card_ids": [card_id], "flag": 0})
    assert api.get(f"/cards/{card_id}").json()["flag"] == 0


def test_flag_out_of_range_is_422(api, card_id):
    assert api.post("/cards/actions/set-flag", json={"card_ids": [card_id], "flag": 99}).status_code == 422


def test_suspend_unsuspend(api, card_id):
    out = api.post("/cards/actions/suspend", json={"card_ids": [card_id]}).json()
    assert out["count"] == 1
    # queue -1 == suspended
    assert api.get(f"/cards/{card_id}").json()["queue"] == -1
    api.post("/cards/actions/unsuspend", json={"card_ids": [card_id]})
    assert api.get(f"/cards/{card_id}").json()["queue"] != -1


def test_bury_unbury(api, card_id):
    out = api.post("/cards/actions/bury", json={"card_ids": [card_id]}).json()
    assert out["count"] == 1
    assert api.get(f"/cards/{card_id}").json()["queue"] == -3  # user-buried
    resp = api.post("/cards/actions/unbury", json={"card_ids": [card_id]})
    assert resp.status_code == 200
    assert resp.json()["changes"]["card"] is True
    assert api.get(f"/cards/{card_id}").json()["queue"] == 0  # back in the new queue


def test_set_deck(api, card_id):
    other = api.make_deck("Other")
    out = api.post("/cards/actions/set-deck", json={"card_ids": [card_id], "deck_id": other}).json()
    assert out["count"] == 1
    assert api.get(f"/cards/{card_id}").json()["deck_id"] == other


def test_card_stats_html_route_is_gone(api, card_id):
    """Removed 2026-10-03 (Lukas: "probably remove it"). It returned Anki's DEPRECATED
    `card_stats` webview bootstrap page — `<div id="cardinfo-…"><script src="pages/card-info.js">`,
    useless outside Anki's own webview — and answered 200 for a card that does not exist.
    The structured card info is `GET /stats/card/{id}`."""
    assert api.get(f"/cards/{card_id}/stats").status_code == 404
    assert api.get(f"/stats/card/{card_id}").json()["card_id"] == card_id


# --- bulk views + scheduling writes (the scheduling snapshot/restore surface) ---

def test_bulk_card_views(api):
    id1 = api.make_note(front="q1", back="a1")["card_ids"][0]
    id2 = api.make_note(front="q2", back="a2")["card_ids"][0]
    views = api.post("/cards/views", json={"card_ids": [id1, id2]}).json()
    assert [v["id"] for v in views] == [id1, id2]
    for v in views:
        assert "factor" in v and "ord" in v and "interval" in v


def test_patch_card_scheduling(api, card_id):
    out = api.patch(f"/cards/{card_id}", json={"interval": 42, "factor": 2100, "reps": 7, "lapses": 1}).json()
    assert out["changes"]["card"] is True
    card = api.get(f"/cards/{card_id}").json()
    assert card["interval"] == 42
    assert card["factor"] == 2100
    assert card["reps"] == 7
    assert card["lapses"] == 1


def test_scheduling_restore_recipe(api, card_id):
    """The blessed restore recipe for recreated cards: set-due-date "N!" (review-ify,
    sets due+interval) then PATCH the remaining scheduling columns."""
    api.post("/review/set-due-date", json={"card_ids": [card_id], "days": "5!"})
    api.patch(f"/cards/{card_id}", json={"interval": 17, "factor": 2350})
    card = api.get(f"/cards/{card_id}").json()
    assert card["type"] == 2  # review card now
    assert card["interval"] == 17
    assert card["factor"] == 2350


# --- first_review / latest_review on the views (the bulk replacement for /stats/card/{id}) ---

def _answer(api, deck: str, card_id: str, rating: str = "good") -> None:
    nxt = api.get("/review/next", params={"deck": deck}).json()
    assert nxt["card_id"] == card_id
    r = api.post("/review/answer", json={"card_id": card_id, "rating": rating, "review_token": nxt["review_token"]})
    assert r.status_code == 200, r.text


def test_views_carry_first_and_latest_review_matching_card_stats(api):
    """`first_review` / `latest_review` on every card view: the epoch seconds of the card's
    first and last revlog row, null when it has none — the same numbers /stats/card/{id}
    reports (which serialises them as strings, protobuf int64), so a caller replaying the
    order a learner met hundreds of cards needs one request instead of one per card."""
    studied = api.make_note(deck="Studied", front="q1")["card_ids"][0]
    fresh = api.make_note(deck="Fresh", front="q2")["card_ids"][0]
    _answer(api, "Studied", studied)

    views = {v["id"]: v for v in api.post("/cards/views", json={"card_ids": [studied, fresh]}).json()}
    stats = api.get(f"/stats/card/{studied}").json()
    assert isinstance(views[studied]["first_review"], int)
    assert views[studied]["first_review"] == int(stats["first_review"])
    assert views[studied]["latest_review"] == int(stats["latest_review"])
    assert views[studied]["first_review"] <= views[studied]["latest_review"]

    assert views[fresh]["first_review"] is None and views[fresh]["latest_review"] is None
    assert "first_review" not in api.get(f"/stats/card/{fresh}").json()  # card info: absent, not zero

    # the single-card view is the same shape
    single = api.get(f"/cards/{studied}").json()
    assert single["first_review"] == views[studied]["first_review"]
    assert single["latest_review"] == views[studied]["latest_review"]
    assert api.get(f"/cards/{fresh}").json()["first_review"] is None


def test_a_manual_revlog_row_counts_as_the_first_review_as_card_stats_counts_it(api):
    """set-due-date on a never-answered card writes a MANUAL revlog row (type 4), and Anki's
    card info dates `first_review` from it while `reviews` stays 0. The view follows card info
    rather than second-guessing it; `reps` is what says whether the learner has answered."""
    card_id = api.make_note(deck="Restored")["card_ids"][0]
    api.post("/review/set-due-date", json={"card_ids": [card_id], "days": "5!"})
    view = api.get(f"/cards/{card_id}").json()
    stats = api.get(f"/stats/card/{card_id}").json()
    assert view["reps"] == 0 and stats.get("reviews", 0) == 0
    assert view["first_review"] is not None
    assert view["first_review"] == int(stats["first_review"])
    assert view["latest_review"] == int(stats["latest_review"])


def test_bulk_views_join_the_revlog_across_chunks(api, monkeypatch):
    """The revlog is read in chunks of ids; every card must land in its own view whatever
    chunk it falls in, and cards without rows stay null. Chunk size forced to 2 for 3 cards."""
    monkeypatch.setattr(cards_router, "REVLOG_BOUNDS_CHUNK", 2)
    ids = [api.make_note(deck=f"C{i}", front=f"q{i}")["card_ids"][0] for i in range(3)]
    _answer(api, "C0", ids[0])
    _answer(api, "C2", ids[2])
    views = api.post("/cards/views", json={"card_ids": ids}).json()
    assert [v["id"] for v in views] == ids
    assert views[0]["first_review"] == int(api.get(f"/stats/card/{ids[0]}").json()["first_review"])
    assert views[1]["first_review"] is None
    assert views[2]["first_review"] == int(api.get(f"/stats/card/{ids[2]}").json()["first_review"])
