"""Tags [parity]."""


def test_list_and_tree(api):
    api.make_note(deck="D", front="a", tags=["geo::europe", "geo::asia"])
    tags = api.get("/tags").json()
    assert "geo::europe" in tags and "geo::asia" in tags

    tree = api.get("/tags/tree").json()
    geo = next(c for c in tree["children"] if c["name"] == "geo")
    assert {c["name"] for c in geo["children"]} == {"europe", "asia"}


def test_add_and_remove_tags(api):
    note = api.make_note(deck="D")
    nid = note["id"]
    out = api.post("/tags/actions/add", json={"note_ids": [nid], "tags": ["x", "y"]}).json()
    assert out["count"] == 1
    assert set(api.get(f"/notes/{nid}").json()["tags"]) == {"x", "y"}

    api.post("/tags/actions/remove", json={"note_ids": [nid], "tags": ["x"]})
    assert api.get(f"/notes/{nid}").json()["tags"] == ["y"]


def test_rename_tag(api):
    nid = api.make_note(deck="D", tags=["old"])["id"]
    out = api.post("/tags/rename", json={"old": "old", "new": "new"}).json()
    assert out["count"] == 1
    assert api.get(f"/notes/{nid}").json()["tags"] == ["new"]


def test_reparent_tag(api):
    nid = api.make_note(deck="D", tags=["child"])["id"]
    api.post("/tags/reparent", json={"tags": ["child"], "new_parent": "parent"})
    assert api.get(f"/notes/{nid}").json()["tags"] == ["parent::child"]


def test_delete_tag(api):
    nid = api.make_note(deck="D", tags=["gone", "stay"])["id"]
    out = api.post("/tags/actions/delete", json={"tags": ["gone"]}).json()
    assert out["count"] >= 1
    assert api.get(f"/notes/{nid}").json()["tags"] == ["stay"]


def test_set_collapsed(api):
    api.make_note(deck="D", tags=["parent::child"])
    out = api.post("/tags/set-collapsed", json={"tag": "parent", "collapsed": True}).json()
    assert "changes" in out
    tree = api.get("/tags/tree").json()
    assert next(c for c in tree["children"] if c["name"] == "parent")["collapsed"] is True


def test_clear_unused(api):
    nid = api.make_note(deck="D", tags=["temp"])["id"]
    # remove the tag from the note; it lingers in the tag list until cleared
    api.post("/tags/actions/remove", json={"note_ids": [nid], "tags": ["temp"]})
    assert "temp" in api.get("/tags").json()
    out = api.post("/tags/clear-unused").json()
    assert out["count"] >= 1
    assert "temp" not in api.get("/tags").json()
