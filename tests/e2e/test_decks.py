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


def test_tree_counts_the_cards(api):
    for i in range(3):
        api.make_note(deck="Counted::Sub", front=f"q{i}")
    api.make_note(deck="Counted", front="top")
    tree = api.get("/decks/tree").json()
    parent = next(c for c in tree["children"] if c["name"] == "Counted")
    child = next(c for c in parent["children"] if c["name"] == "Sub")
    assert (child["new_count"], child["total_in_deck"]) == (3, 3)
    assert (parent["new_count"], parent["total_in_deck"], parent["total_including_children"]) == (4, 1, 4)


def test_list_flags_filter_the_list(api):
    api.make_note(deck="Src", front="q")
    api.post("/filtered-decks", json={"name": "Filt", "search": "deck:Src"})
    names = lambda **params: {d["name"] for d in api.get("/decks", params=params).json()}  # noqa: E731
    assert names() == {"Default", "Src", "Filt"}
    assert names(include_filtered=False) == {"Default", "Src"}
    assert names(skip_empty_default=True) == {"Src", "Filt"}


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


def test_delete_unknown_deck_is_404(api):
    """Used to answer 200 with count 0 — which is also what deleting an empty deck answers."""
    assert api.delete("/decks/123456").status_code == 404
