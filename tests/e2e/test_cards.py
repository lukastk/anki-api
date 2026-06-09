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
