"""Statistics [parity]."""


def test_graphs_returns_all_sections(api):
    api.make_note(deck="D", front="a", back="b")
    g = api.get("/stats/graphs", params={"days": 365}).json()
    # the backend computes every graph section in one call
    for key in ("card_counts", "reviews", "intervals", "future_due", "today", "true_retention"):
        assert key in g, key


def test_graphs_accepts_search(api):
    api.make_note(deck="Filtered", front="a")
    assert api.get("/stats/graphs", params={"search": "deck:Filtered", "days": 30}).status_code == 200


def test_today_summary(api):
    out = api.get("/stats/today").json()
    assert isinstance(out["summary"], str)


def test_card_stats_data(api):
    card_id = api.make_note(deck="D")["card_ids"][0]
    cs = api.get(f"/stats/card/{card_id}").json()
    assert cs["card_id"] == card_id
    assert {"note_id", "deck", "notetype", "preset"} <= set(cs)


def test_graph_preferences_roundtrip(api):
    prefs = api.get("/stats/graph-preferences").json()
    assert "future_due_show_backlog" in prefs
    updated = api.put("/stats/graph-preferences", json={"future_due_show_backlog": False}).json()
    # MessageToDict omits false-valued bools; absence means it was set to false
    assert updated.get("future_due_show_backlog", False) is False
