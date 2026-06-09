"""Deck options / presets [parity] — the deck-options screen's config groups."""


def _preset_id(api, name: str) -> str:
    return next(p["id"] for p in api.get("/deck-presets").json() if p["name"] == name)


def test_list_includes_default(api):
    presets = {p["name"]: p["id"] for p in api.get("/deck-presets").json()}
    assert "Default" in presets
    assert presets["Default"] == "1"


def test_get_full_config(api):
    cfg = api.get("/deck-presets/1").json()
    assert cfg["id"] == "1"
    assert cfg["name"] == "Default"
    assert {"new", "rev", "lapse", "desiredRetention"} <= set(cfg)
    assert "perDay" in cfg["new"]


def test_get_missing_is_404(api):
    assert api.get("/deck-presets/999999").status_code == 404


def test_create_preset(api):
    out = api.post("/deck-presets", json={"name": "Aggressive"}).json()
    assert out["id"] and out["id"] != "1"
    assert api.get(f"/deck-presets/{out['id']}").json()["name"] == "Aggressive"


def test_create_clone_copies_settings(api):
    # tweak Default, then clone from it
    api.put("/deck-presets/1", json={"new": {"perDay": 42}})
    out = api.post("/deck-presets", json={"name": "Cloned", "clone_from": "1"}).json()
    assert api.get(f"/deck-presets/{out['id']}").json()["new"]["perDay"] == 42


def test_update_partial_merges(api):
    pid = api.post("/deck-presets", json={"name": "Tunable"}).json()["id"]
    updated = api.put(f"/deck-presets/{pid}", json={
        "new": {"perDay": 99}, "rev": {"perDay": 50}, "desiredRetention": 0.95,
    }).json()
    assert updated["new"]["perDay"] == 99
    assert updated["rev"]["perDay"] == 50
    assert updated["desiredRetention"] == 0.95
    # other nested keys preserved (merge, not replace)
    assert "delays" in updated["new"]


def test_delete_preset(api):
    pid = api.post("/deck-presets", json={"name": "Doomed"}).json()["id"]
    assert api.delete(f"/deck-presets/{pid}").status_code == 200
    assert api.get(f"/deck-presets/{pid}").status_code == 404


def test_delete_default_is_422(api):
    assert api.delete("/deck-presets/1").status_code == 422


def test_restore_defaults(api):
    pid = api.post("/deck-presets", json={"name": "Reset"}).json()["id"]
    api.put(f"/deck-presets/{pid}", json={"new": {"perDay": 7}})
    api.post(f"/deck-presets/{pid}/restore-defaults")
    # default new.perDay is not 7
    assert api.get(f"/deck-presets/{pid}").json()["new"]["perDay"] != 7


def test_deck_preset_get_and_assign(api):
    did = api.make_deck("Studyish")
    # default deck uses the Default preset
    assert api.get(f"/decks/{did}/preset").json()["name"] == "Default"

    pid = api.post("/deck-presets", json={"name": "ForDeck"}).json()["id"]
    resp = api.post(f"/decks/{did}/preset", json={"preset_id": pid})
    assert resp.status_code == 200
    # the assignment persists (anki reports no view-refresh flags for a conf-only change)
    assert api.get(f"/decks/{did}/preset").json()["name"] == "ForDeck"
