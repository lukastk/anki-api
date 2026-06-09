def test_create_lists_and_gets(api):
    created = api.post("/decks", json={"name": "Geo"}).json()
    assert created["id"]
    assert created["changes"]["deck"] is True

    names = {d["name"]: d["id"] for d in api.get("/decks").json()}
    assert "Geo" in names and names["Geo"] == created["id"]

    got = api.get(f"/decks/{created['id']}").json()
    assert got["name"] == "Geo"
    assert got["filtered"] is False


def test_tree_includes_hierarchy_with_counts(api):
    api.make_deck("Parent::Child")
    tree = api.get("/decks/tree").json()
    parent = next(c for c in tree["children"] if c["name"] == "Parent")
    assert any(ch["name"] == "Child" for ch in parent["children"])
    # count fields present
    assert {"new_count", "learn_count", "review_count"} <= set(parent.keys())


def test_rename(api):
    did = api.make_deck("Old")
    out = api.post(f"/decks/{did}/rename", json={"name": "New"}).json()
    assert out["changes"]["deck"] is True
    assert api.get(f"/decks/{did}").json()["name"] == "New"


def test_reparent(api):
    parent = api.make_deck("P")
    child = api.make_deck("C")
    out = api.post("/decks/reparent", json={"deck_ids": [child], "new_parent": parent}).json()
    assert out["count"] == 1
    assert api.get(f"/decks/{child}").json()["name"] == "P::C"


def test_delete(api):
    did = api.make_deck("Doomed")
    out = api.delete(f"/decks/{did}")
    assert out.status_code == 200
    # OpChangesWithCount.count reflects cards removed (0 for an empty deck), not decks.
    assert "count" in out.json()
    assert api.get(f"/decks/{did}").status_code == 404
