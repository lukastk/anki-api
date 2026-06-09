"""UI-chrome helpers [parity]: timespan formatting, markdown, i18n, + small gaps."""


def test_format_timespan(api):
    out = api.post("/format/timespan", json={"seconds": 90}).json()
    assert isinstance(out["text"], str) and out["text"]


def test_format_timespan_contexts(api):
    # different contexts render differently; all must succeed
    for ctx in ("precise", "answer_buttons", "intervals"):
        r = api.post("/format/timespan", json={"seconds": 86400, "context": ctx})
        assert r.status_code == 200


def test_format_timespan_bad_context_is_422(api):
    assert api.post("/format/timespan", json={"seconds": 1, "context": "nope"}).status_code == 422


def test_render_markdown(api):
    out = api.post("/render/markdown", json={"markdown": "# Title\n\n**bold**"}).json()
    assert "<h1" in out["html"]
    assert "<strong>" in out["html"]


def test_default_deck_for_notetype(api):
    # create a note so a deck becomes associated with the Basic notetype
    api.make_note(deck="AssocDeck", front="a", back="b")
    nt_id = next(n["id"] for n in api.get("/notetypes").json() if n["name"] == "Basic")
    out = api.get(f"/notetypes/{nt_id}/default-deck").json()
    # deck_id is null or a string id, never an int
    assert out["deck_id"] is None or isinstance(out["deck_id"], str)


def test_restore_buried_and_suspended(api):
    card_id = api.make_note(deck="D")["card_ids"][0]
    api.post("/cards/actions/suspend", json={"card_ids": [card_id]})
    assert api.get(f"/cards/{card_id}").json()["queue"] == -1
    out = api.post("/cards/actions/restore-buried-and-suspended", json={"card_ids": [card_id]}).json()
    assert "changes" in out
    assert api.get(f"/cards/{card_id}").json()["queue"] != -1
