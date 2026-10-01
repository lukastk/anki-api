"""Import / Export [parity]."""


def test_export_apkg_collection(api):
    api.make_note(deck="D", front="alpha", back="beta")
    resp = api.post("/export/apkg", json={"limit": {"scope": "collection"}, "with_scheduling": True})
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"  # zip/apkg magic


def test_export_apkg_deck(api):
    did = api.make_deck("Exportable")
    api.make_note(deck="Exportable", front="x")
    resp = api.post("/export/apkg", json={"limit": {"scope": "deck", "deck_id": did}})
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"


def test_export_deck_requires_deck_id(api):
    assert api.post("/export/apkg", json={"limit": {"scope": "deck"}}).status_code == 422


def test_export_unknown_scope(api):
    assert api.post("/export/apkg", json={"limit": {"scope": "bogus"}}).status_code == 422


def test_export_notes_csv_contains_content(api):
    api.make_note(deck="D", front="alphaword", back="betaword")
    resp = api.post("/export/notes-csv", json={"limit": {"scope": "collection"}, "with_html": False})
    assert resp.status_code == 200
    assert "alphaword" in resp.text


def test_export_cards_csv(api):
    api.make_note(deck="D", front="q1")
    resp = api.post("/export/cards-csv", json={"limit": {"scope": "collection"}})
    assert resp.status_code == 200
    assert resp.text  # non-empty


def test_import_apkg_roundtrip(api):
    api.make_note(deck="D", front="exported-note")
    apkg = api.post("/export/apkg", json={"limit": {"scope": "collection"}, "with_scheduling": True}).content

    resp = api.post(
        "/import/apkg",
        params={"merge_notetypes": True, "with_scheduling": True},
        files={"file": ("e.apkg", apkg, "application/octet-stream")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "log" in body and "changes" in body
    assert api.get("/collection").json()["note_count"] >= 1


def test_csv_metadata(api):
    csv = b"front1,back1\nfront2,back2\n"
    resp = api.post("/import/csv/metadata", files={"file": ("notes.csv", csv, "text/csv")})
    assert resp.status_code == 200
    meta = resp.json()
    assert "delimiter" in meta


def test_import_csv_creates_notes(api):
    nt_id = next(n["id"] for n in api.get("/notetypes").json() if n["name"] == "Basic")
    did = api.make_deck("CsvDeck")
    csv = b"hello,world\nfoo,bar\n"
    resp = api.post(
        "/import/csv",
        params={"deck_id": did, "notetype_id": nt_id},
        files={"file": ("notes.csv", csv, "text/csv")},
    )
    assert resp.status_code == 200
    assert api.post("/search/notes", json={"query": "deck:CsvDeck"}).json()["count"] == 2


def test_export_deck_exports_only_that_deck(api):
    """The limit must actually limit. Until 2026-10-01 it did not: `_build_limit` returned
    an `ie.ExportLimit` protobuf, Anki's `pb_export_limit` dispatches on its own wrapper
    types and falls through to `whole_collection` for anything else, so every scoped export
    quietly returned the entire collection and still answered 200 with a valid .apkg. The
    tests that existed asserted the status and the zip magic, which both stayed true.

    `legacy` so the package carries a plain sqlite the test can read without zstandard."""
    did = api.make_deck("Wanted")
    api.make_note(deck="Wanted", front="keepmeplease")
    api.make_note(deck="Other", front="leavemeout")
    resp = api.post("/export/apkg", json={"limit": {"scope": "deck", "deck_id": did},
                                          "with_media": False, "legacy": True})
    assert resp.status_code == 200
    fronts = _apkg_fields(resp.content)
    assert any("keepmeplease" in f for f in fronts), "the wanted note is missing"
    assert not any("leavemeout" in f for f in fronts), "a note outside the deck was exported"


def test_export_notes_csv_honours_the_deck_limit(api):
    did = api.make_deck("CsvWanted")
    api.make_note(deck="CsvWanted", front="csvkeep")
    api.make_note(deck="CsvOther", front="csvdrop")
    resp = api.post("/export/notes-csv", json={"limit": {"scope": "deck", "deck_id": did},
                                               "with_html": False})
    assert resp.status_code == 200
    assert "csvkeep" in resp.text
    assert "csvdrop" not in resp.text


def _apkg_fields(blob: bytes) -> list[str]:
    """Every note's fields in a LEGACY .apkg.

    The data is in `collection.anki21`, plain sqlite. `collection.anki2` is present in
    every package and is a stub holding one note that reads "Please update to the latest
    Anki version" — read that one and a correct export looks empty."""
    import io
    import sqlite3
    import tempfile
    import zipfile

    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read("collection.anki21")
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        f.write(raw)
        f.flush()
        con = sqlite3.connect(f.name)
        con.create_collation("unicase", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
        try:
            return [r[0] for r in con.execute("select flds from notes")]
        finally:
            con.close()
