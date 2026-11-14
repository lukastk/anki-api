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


def test_delete_preset_from_never_synced_collection(api):
    pid = api.post("/deck-presets", json={"name": "Doomed"}).json()["id"]
    assert api.get("/sync/health").json()["never_synced"] is True
    assert api.delete(f"/deck-presets/{pid}").status_code == 200
    assert api.get(f"/deck-presets/{pid}").status_code == 404


def test_delete_preset_refuses_on_a_synced_collection(api):
    """Deleting a preset calls mod_schema, so a collection with a sync history would
    require a one-way full sync. Refuse before removing anything."""
    pid = api.post("/deck-presets", json={"name": "Doomed"}).json()["id"]
    with api._c.app.state.handle.locked() as col:
        col.db.execute("update col set ls = ?", col.db.scalar("select scm from col"))
    assert api.get("/sync/health").json()["never_synced"] is False

    refused = api.delete(f"/deck-presets/{pid}")
    assert refused.status_code == 409
    assert "synced collection" in refused.json()["detail"]
    assert "full sync" in refused.json()["detail"]
    assert api.get(f"/deck-presets/{pid}").status_code == 200, "the refusal wrote nothing"


def test_schema_change_acknowledgement_cannot_bypass_synced_collection_refusal(api):
    """The old acknowledgement query must not turn the destructive operation back on."""
    pid = api.post("/deck-presets", json={"name": "Doomed"}).json()["id"]
    with api._c.app.state.handle.locked() as col:
        col.db.execute("update col set ls = ?", col.db.scalar("select scm from col"))

    refused = api.delete(f"/deck-presets/{pid}?accept_schema_change=true")
    assert refused.status_code == 409
    assert api.get(f"/deck-presets/{pid}").status_code == 200


def test_delete_default_is_422(api):
    assert api.delete("/deck-presets/1").status_code == 422


def test_delete_a_preset_that_is_not_there_is_404_before_the_sync_guard(api):
    """A missing preset is not a reason to reject the collection or touch its schema."""
    with api._c.app.state.handle.locked() as col:
        col.db.execute("update col set ls = ?", col.db.scalar("select scm from col"))
    assert api.delete("/deck-presets/987654321").status_code == 404


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


def test_assign_unknown_preset_is_404_and_leaves_the_deck_alone(api):
    """Used to answer 200 and store the dangling preset id on the deck, which then quietly
    studied with the Default preset."""
    did = api.make_deck("Studyish")
    pid = api.post("/deck-presets", json={"name": "ForDeck"}).json()["id"]
    api.post(f"/decks/{did}/preset", json={"preset_id": pid})

    assert api.post(f"/decks/{did}/preset", json={"preset_id": "999999"}).status_code == 404
    assert api.get(f"/decks/{did}").json()["config_id"] == pid
    assert api.get(f"/decks/{did}/preset").json()["name"] == "ForDeck"
