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


# --- per-deck study limits ("This deck" / "Today only") ---------------------------------

LIMIT_FIELDS = ("new_limit", "review_limit", "new_limit_today", "review_limit_today")


def _deck_with_new_cards(api, name="Course::Cards", n=6) -> str:
    for i in range(n):
        api.make_note(deck=name, front=f"{name}{i}")
    return next(d["id"] for d in api.get("/decks").json() if d["name"] == name)


def _new_count(api, name="Course::Cards") -> int:
    return api.get("/review/counts", params={"deck": name}).json()["new"]


def _stored(api, deck_id: str) -> dict:
    """The raw deck dict, for mod/usn and the untouched fields."""
    with api._c.app.state.handle.locked() as col:
        return dict(col.decks.get_legacy(int(deck_id)))


def test_a_new_deck_has_no_limits(api):
    did = _deck_with_new_cards(api)
    deck = api.get(f"/decks/{did}").json()
    assert {k: deck[k] for k in LIMIT_FIELDS} == dict.fromkeys(LIMIT_FIELDS)


def test_set_limits_are_read_back_honoured_by_the_scheduler_and_sync_marked(api):
    did = _deck_with_new_cards(api)
    with api._c.app.state.handle.locked() as col:  # pretend the deck was synced
        col.db.execute("update decks set usn = 7, mtime_secs = 1000 where id = ?", int(did))
    before = _stored(api, did)
    assert _new_count(api) == 6

    out = api.patch(f"/decks/{did}/limits", json={"new_limit": 4, "review_limit": 50})
    assert out.status_code == 200, out.text
    assert out.json() == api.get(f"/decks/{did}").json()  # the deck as GET shows it
    assert {k: out.json()[k] for k in LIMIT_FIELDS} == {
        "new_limit": 4, "review_limit": 50, "new_limit_today": None, "review_limit_today": None}
    assert _new_count(api) == 4

    # today-only overrides "this deck" for today
    api.patch(f"/decks/{did}/limits", json={"new_limit_today": 2, "review_limit_today": 9})
    deck = api.get(f"/decks/{did}").json()
    assert (deck["new_limit"], deck["new_limit_today"], deck["review_limit_today"]) == (4, 2, 9)
    assert _new_count(api) == 2

    after = _stored(api, did)
    assert after["usn"] == -1 and after["mod"] > before["mod"]  # sync will carry it
    untouched = {k for k in before if k not in ("newLimit", "reviewLimit", "newLimitToday", "reviewLimitToday", "mod", "usn")}
    assert {k: after[k] for k in untouched} == {k: before[k] for k in untouched}


def test_omitted_fields_are_kept_and_null_clears(api):
    did = _deck_with_new_cards(api)
    api.patch(f"/decks/{did}/limits", json={"new_limit": 3, "review_limit": 40, "new_limit_today": 1})
    out = api.patch(f"/decks/{did}/limits", json={"new_limit_today": None}).json()
    assert {k: out[k] for k in LIMIT_FIELDS} == {
        "new_limit": 3, "review_limit": 40, "new_limit_today": None, "review_limit_today": None}
    assert _new_count(api) == 3
    out = api.patch(f"/decks/{did}/limits", json={"new_limit": None, "review_limit": None}).json()
    assert {k: out[k] for k in LIMIT_FIELDS} == dict.fromkeys(LIMIT_FIELDS)
    assert _new_count(api) == 6


def test_today_only_limit_expires_at_the_day_boundary(api):
    """A today-only limit is stamped with Anki's current day. Crossing the day boundary
    (moving the collection's creation stamp back one day, then reopening so the backend
    recomputes its cached day) makes it stale: GET reports null and the scheduler falls
    back to the deck's "this deck" limit. The stale value stays in the deck dict, as
    Anki's own deck options leave it."""
    did = _deck_with_new_cards(api)
    api.patch(f"/decks/{did}/limits", json={"new_limit": 4, "new_limit_today": 2})
    day = api.get("/collection/timing").json()["days_elapsed"]
    assert _stored(api, did)["newLimitToday"] == {"limit": 2, "today": day}
    assert _new_count(api) == 2

    with api._c.app.state.handle.locked() as col:
        col.crt = col.crt - 86_400
        col.close()
        col.reopen()
    assert api.get("/collection/timing").json()["days_elapsed"] == day + 1
    deck = api.get(f"/decks/{did}").json()
    assert deck["new_limit_today"] is None and deck["new_limit"] == 4
    assert _new_count(api) == 4
    assert _stored(api, did)["newLimitToday"] == {"limit": 2, "today": day}


def test_other_decks_are_unchanged(api):
    did = _deck_with_new_cards(api)
    other = _deck_with_new_cards(api, name="Plain", n=3)
    before = _stored(api, other)
    api.patch(f"/decks/{did}/limits", json={"new_limit": 1, "new_limit_today": 1})
    assert _stored(api, other) == before
    assert {k: api.get(f"/decks/{other}").json()[k] for k in LIMIT_FIELDS} == dict.fromkeys(LIMIT_FIELDS)
    assert _new_count(api, "Plain") == 3


def test_limits_refusals_write_nothing(api):
    did = _deck_with_new_cards(api)
    api.patch(f"/decks/{did}/limits", json={"new_limit": 5})
    before = _stored(api, did)
    for bad in ({"new_limit": -1}, {"review_limit_today": -3}, {"newLimit": 3}):
        assert api.patch(f"/decks/{did}/limits", json=bad).status_code == 422, bad
    fid = api.post("/filtered-decks", json={"name": "F", "search": "deck:Course::Cards"}).json()["id"]
    out = api.patch(f"/decks/{fid}/limits", json={"new_limit": 1})
    assert out.status_code == 409 and "filtered" in out.text
    assert api.patch("/decks/999999/limits", json={"new_limit": 1}).status_code == 404
    assert _stored(api, did) == before


def test_filtered_deck_reads_null_limits(api):
    _deck_with_new_cards(api)
    fid = api.post("/filtered-decks", json={"name": "F", "search": "deck:Course::Cards"}).json()["id"]
    deck = api.get(f"/decks/{fid}").json()
    assert deck["filtered"] is True
    assert {k: deck[k] for k in LIMIT_FIELDS} == dict.fromkeys(LIMIT_FIELDS)
