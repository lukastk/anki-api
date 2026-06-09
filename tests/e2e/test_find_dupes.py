def test_find_duplicates(api):
    api.make_note(deck="D", front="same", back="1")
    api.make_note(deck="D", front="same", back="2")
    api.make_note(deck="D", front="unique", back="3")
    dupes = api.get("/notes/find-duplicates", params={"field": "Front"}).json()
    vals = {d["value"]: d["note_ids"] for d in dupes}
    assert "same" in vals and len(vals["same"]) == 2
    assert "unique" not in vals
