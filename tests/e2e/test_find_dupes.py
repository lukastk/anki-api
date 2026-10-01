def test_find_duplicates(api):
    api.make_note(deck="D", front="same", back="1")
    api.make_note(deck="D", front="same", back="2")
    api.make_note(deck="D", front="unique", back="3")
    dupes = api.get("/notes/find-duplicates", params={"field": "Front"}).json()
    vals = {d["value"]: d["note_ids"] for d in dupes}
    assert "same" in vals and len(vals["same"]) == 2
    assert "unique" not in vals


def test_find_duplicates_in_an_unknown_field_is_404(api):
    """A field no notetype has used to answer 200 with [] — "no duplicates" for a typo."""
    api.make_note(deck="D", front="same", back="1")
    api.make_note(deck="D", front="same", back="2")
    assert api.get("/notes/find-duplicates", params={"field": "Frnot"}).status_code == 404
    # anki matches the field name case-insensitively
    assert len(api.get("/notes/find-duplicates", params={"field": "front"}).json()) == 1
