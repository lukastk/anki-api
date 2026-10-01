"""UI-chrome helpers [parity]: timespan formatting, markdown, i18n, + small gaps."""


def test_format_timespan(api):
    out = api.post("/format/timespan", json={"seconds": 90}).json()
    assert isinstance(out["text"], str) and out["text"]


def test_format_timespan_contexts(api):
    # different contexts render differently (the number is wrapped in bidi isolates)
    text = lambda ctx: api.post("/format/timespan", json={"seconds": 86400, "context": ctx}).json()[  # noqa: E731
        "text"].replace("\u2068", "").replace("\u2069", "")
    assert text("answer_buttons") == "1d"
    assert text("intervals") == "1 day"
    assert text("precise") == "1 day"


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
    # with anki's default "new notes go to the current deck", there is no per-notetype deck
    assert out == {"deck_id": None}
    # switch that off and it is the deck last used with the notetype
    api.put("/config/addToCur", json={"value": False})
    assoc = next(d["id"] for d in api.get("/decks").json() if d["name"] == "AssocDeck")
    assert api.get(f"/notetypes/{nt_id}/default-deck").json() == {"deck_id": assoc}


def test_restore_buried_and_suspended(api):
    card_id = api.make_note(deck="D")["card_ids"][0]
    api.post("/cards/actions/suspend", json={"card_ids": [card_id]})
    assert api.get(f"/cards/{card_id}").json()["queue"] == -1
    out = api.post("/cards/actions/restore-buried-and-suspended", json={"card_ids": [card_id]}).json()
    assert "changes" in out
    assert api.get(f"/cards/{card_id}").json()["queue"] != -1
