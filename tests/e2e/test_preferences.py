"""Config & preferences [parity]."""


def test_config_set_get_delete(api):
    out = api.put("/config/myKey", json={"value": {"a": 1, "b": [2, 3]}}).json()
    assert out["changes"]["config"] is True
    got = api.get("/config/myKey").json()
    assert got["value"] == {"a": 1, "b": [2, 3]}

    api.delete("/config/myKey")
    assert api.get("/config/myKey").status_code == 404


def test_get_missing_config_is_404(api):
    assert api.get("/config/neverSet").status_code == 404


def test_delete_missing_config_is_404(api):
    assert api.delete("/config/neverSet").status_code == 404


def test_config_scalar_values(api):
    api.put("/config/num", json={"value": 42})
    assert api.get("/config/num").json()["value"] == 42
    api.put("/config/flag", json={"value": True})
    assert api.get("/config/flag").json()["value"] is True


def test_preferences_shape(api):
    prefs = api.get("/preferences").json()
    assert {"scheduling", "reviewing", "editing", "backups"} <= set(prefs)


def test_preferences_partial_update_merges(api):
    before = api.get("/preferences").json()["scheduling"]
    updated = api.put("/preferences", json={"scheduling": {"learn_ahead_secs": 1234}}).json()
    assert updated["scheduling"]["learn_ahead_secs"] == 1234
    # an unrelated scheduling field is preserved (merge, not replace)
    if "new_timezone" in before:
        assert updated["scheduling"].get("new_timezone") == before.get("new_timezone")
