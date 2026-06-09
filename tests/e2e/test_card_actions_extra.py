"""Additional card actions [parity]: forget (reset to new) and reposition."""


def _review_once(api, deck="D"):
    card_id = api.make_note(deck=deck, front="q", back="a")["card_ids"][0]
    nxt = api.get("/review/next", params={"deck": deck}).json()
    api.post("/review/answer", json={"card_id": card_id, "rating": "good", "review_token": nxt["review_token"]})
    return card_id


def test_forget_resets_to_new(api):
    card_id = _review_once(api)
    assert api.get(f"/cards/{card_id}").json()["reps"] == 1
    out = api.post("/cards/actions/forget", json={"card_ids": [card_id], "reset_counts": True}).json()
    assert "changes" in out
    card = api.get(f"/cards/{card_id}").json()
    assert card["type"] == 0  # back to new
    assert card["reps"] == 0  # reset_counts cleared the history count


def test_reposition_new_cards(api):
    card_id = api.make_note(deck="D", front="x")["card_ids"][0]
    out = api.post("/cards/actions/reposition", json={
        "card_ids": [card_id], "starting_from": 5, "step_size": 1,
    }).json()
    assert out["count"] >= 1
    assert api.get(f"/cards/{card_id}").json()["due"] == 5


def test_help_link(api):
    out = api.get("/help/link", params={"page": 0}).json()
    assert out["url"].startswith("http")
