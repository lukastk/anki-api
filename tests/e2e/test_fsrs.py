"""FSRS controls [parity]."""


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
