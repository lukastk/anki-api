import pytest


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
    api.post("/cards/actions/unbury", json={"card_ids": [card_id]})  # must not error


def test_set_deck(api, card_id):
    other = api.make_deck("Other")
    out = api.post("/cards/actions/set-deck", json={"card_ids": [card_id], "deck_id": other}).json()
    assert out["count"] == 1
    assert api.get(f"/cards/{card_id}").json()["deck_id"] == other


def test_card_stats_html(api, card_id):
    stats = api.get(f"/cards/{card_id}/stats").json()
    assert "<" in stats["html"]


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
