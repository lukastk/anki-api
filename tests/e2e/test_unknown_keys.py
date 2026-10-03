"""A JSON key the request does not declare is a 422 that changes nothing.

Before 2026-10-03 every model dropped unknown keys: a misspelled key was a 200 that did
something else (nothing, usually; the whole collection, for an export limit)."""

import pytest


def _unknown_keys(resp) -> list[str]:
    return [e["loc"][-1] for e in resp.json()["detail"] if e["type"] == "extra_forbidden"]


def test_misspelled_key_on_note_update_is_422_and_changes_nothing(api):
    nid = api.make_note(front="q", back="a", tags=["keep"])["id"]
    resp = api.put(f"/notes/{nid}", json={"tgas": ["x"]})
    assert resp.status_code == 422
    assert _unknown_keys(resp) == ["tgas"]
    assert api.get(f"/notes/{nid}").json()["tags"] == ["keep"]


def test_extra_key_on_create_is_422_and_creates_nothing(api):
    resp = api.post("/notes", json={"deck": "D", "notetype": "Basic", "fields": {"Front": "x"}, "tag": ["x"]})
    assert resp.status_code == 422
    assert _unknown_keys(resp) == ["tag"]
    assert api.get("/collection").json()["note_count"] == 0


def test_extra_key_beside_valid_ones_is_422(api):
    cid = api.make_note(front="q")["card_ids"][0]
    resp = api.post("/cards/actions/set-flag", json={"card_ids": [cid], "flag": 1, "flags": 2})
    assert resp.status_code == 422
    assert _unknown_keys(resp) == ["flags"]
    assert api.get(f"/cards/{cid}").json()["flag"] == 0


def test_unknown_key_in_a_nested_model_is_422(api):
    """Nested request models (an export limit, an occlusion) are checked too."""
    api.make_note(front="q")
    resp = api.post("/export/apkg", json={"limit": {"scope": "collection"}, "with_medai": False})
    assert resp.status_code == 422 and _unknown_keys(resp) == ["with_medai"]
    resp = api.post("/notes/image-occlusion", json={
        "occlusions": [{"shape": "rect", "properties": {"left": 1}, "ordinal": 1, "shap": "rect"}],
        "image_data_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC",
    })
    assert resp.status_code == 422 and _unknown_keys(resp) == ["shap"]
    assert api.get("/collection").json()["note_count"] == 1


@pytest.mark.parametrize("patch, key", [
    ({"newx": 1}, "newx"),
    ({"new": {"perday": 5}}, "new.perday"),
    ({"new": {"perDay": 5}, "lapse": {"delays": [10], "leechFail": 3}}, "lapse.leechFail"),
])
def test_preset_patch_with_a_key_the_preset_lacks_is_422_and_stores_nothing(api, patch, key):
    """The preset PUT is a dict merged into stored config; Anki keeps keys it does not know,
    so a misspelled one used to be stored and have no effect."""
    pid = api.post("/deck-presets", json={"name": "Strict"}).json()["id"]
    before = api.get(f"/deck-presets/{pid}").json()
    resp = api.put(f"/deck-presets/{pid}", json=patch)
    assert resp.status_code == 422
    assert key in resp.json()["detail"]
    assert api.get(f"/deck-presets/{pid}").json() == before


def test_an_empty_body_is_not_an_unknown_key(api):
    """mysrs posts `{}` to endpoints whose body is all-optional or absent."""
    assert api.post("/collection/backup", json={}).status_code == 200
    assert api.post("/sync", json={}).status_code == 401  # body accepted; not logged in
