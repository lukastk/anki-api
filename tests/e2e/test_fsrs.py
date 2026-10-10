"""FSRS controls [parity]."""

import time


def test_enable_disable(api):
    assert api.get("/fsrs").json()["enabled"] is False
    out = api.put("/fsrs", json={"enabled": True}).json()
    assert out["changes"]["config"] is True
    assert api.get("/fsrs").json()["enabled"] is True
    api.put("/fsrs", json={"enabled": False})
    assert api.get("/fsrs").json()["enabled"] is False


def test_compute_params_returns_list(api):
    # insufficient review history -> empty params list, still a 200
    api.make_note(deck="D", front="a")
    out = api.post("/fsrs/compute-params", json={"search": "deck:D"})
    assert out.status_code == 200
    assert isinstance(out.json()["params"], list)


def test_evaluate_insufficient_history_is_400(api):
    api.make_note(deck="D", front="a")
    resp = api.post("/fsrs/evaluate", json={"search": "deck:D"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_input"


# --- POST /fsrs/memory-state -----------------------------------------------------------

DAY_MS = 86_400_000


def _replay(api, card_id):
    """Replay a short history into `card_id`: learn 10 days ago, then two reviews."""
    now = int(time.time() * 1000)
    entries = [
        {"card_id": card_id, "id_ms": str(now - 10 * DAY_MS), "ease": 3, "interval": -600,
         "last_interval": 0, "factor": 0, "time_ms": 5000, "type": 0},
        {"card_id": card_id, "id_ms": str(now - 9 * DAY_MS), "ease": 3, "interval": 3,
         "last_interval": -600, "factor": 2500, "time_ms": 4000, "type": 1},
        {"card_id": card_id, "id_ms": str(now - 6 * DAY_MS), "ease": 3, "interval": 8,
         "last_interval": 3, "factor": 2500, "time_ms": 3000, "type": 1},
    ]
    assert api.post("/revlog", json={"entries": entries}).status_code == 200


def test_memory_state_from_replayed_history_is_stored_on_the_card(api):
    api.put("/fsrs", json={"enabled": True})
    replayed = api.make_note(deck="D", front="r")["card_ids"][0]
    untouched = api.make_note(deck="D", front="u")["card_ids"][0]
    _replay(api, replayed)
    assert api.get(f"/cards/{replayed}").json()["memory_state"] is None

    out = api.post("/fsrs/memory-state", json={"card_ids": [replayed]})
    assert out.status_code == 200, out.text
    [row] = out.json()
    assert row["card_id"] == replayed
    assert row["stability"] > 0 and row["difficulty"] > 0 and 0 < row["desired_retention"] < 1

    view = api.get(f"/cards/{replayed}").json()
    assert view["memory_state"] == {"stability": row["stability"], "difficulty": row["difficulty"]}
    assert view["desired_retention"] == row["desired_retention"]
    assert api.get(f"/cards/{untouched}").json()["memory_state"] is None


def test_memory_state_of_a_card_without_history_is_null(api):
    api.put("/fsrs", json={"enabled": True})
    card = api.make_note(deck="D")["card_ids"][0]
    [row] = api.post("/fsrs/memory-state", json={"card_ids": [card]}).json()
    assert row["stability"] is None and row["difficulty"] is None
    assert api.get(f"/cards/{card}").json()["memory_state"] is None


def test_memory_state_is_409_without_fsrs_and_writes_nothing(api):
    card = api.make_note(deck="D")["card_ids"][0]
    _replay(api, card)
    assert api.post("/fsrs/memory-state", json={"card_ids": [card]}).status_code == 409
    assert api.get(f"/cards/{card}").json()["memory_state"] is None


def test_memory_state_unknown_card_is_404_and_writes_nothing(api):
    api.put("/fsrs", json={"enabled": True})
    card = api.make_note(deck="D")["card_ids"][0]
    _replay(api, card)
    out = api.post("/fsrs/memory-state", json={"card_ids": [card, "555555"]})
    assert out.status_code == 404 and "555555" in out.text
    assert api.get(f"/cards/{card}").json()["memory_state"] is None
