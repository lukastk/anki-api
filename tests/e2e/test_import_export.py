"""Import / Export [parity].

Every export test here reads the export BACK and asserts on what is in it. A status code
and the zip magic prove nothing about an exporter: a scoped export that silently widened to
the whole collection is still a 200 and still a valid .apkg, which is how the limit went
unenforced until 2026-10-01 with a green suite.
"""

import io
import json
import sqlite3
import tempfile
import zipfile

import pytest


def _read_apkg(blob: bytes) -> dict:
    """What a LEGACY .apkg actually holds: zip member names, every note's first field, the
    cards' (id, reps), the revlog row count and the media map.

    The data is in `collection.anki21`, plain sqlite (a modern package keeps it in the
    zstd-compressed `collection.anki21b`, and zstandard is not in the venv).
    `collection.anki2` is present in every package and is a stub holding one note that reads
    "Please update to the latest Anki version" — read that one and a correct export looks
    empty."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = z.namelist()
        raw = z.read("collection.anki21")
        media = json.loads(z.read("media"))
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        f.write(raw)
        f.flush()
        con = sqlite3.connect(f.name)
        try:
            return {
                "names": names,
                "fronts": [flds.split("\x1f")[0] for (flds,) in con.execute("select flds from notes")],
                "cards": con.execute("select id, reps from cards").fetchall(),
                "revlog": con.execute("select count(*) from revlog").fetchone()[0],
                "media": media,
            }
        finally:
            con.close()


def _csv_rows(text: str) -> list[list[str]]:
    """The data rows of an Anki CSV export (tab-separated; `#key:value` lines are headers)."""
    return [line.split("\t") for line in text.splitlines() if line and not line.startswith("#")]


def _review(api, deck: str, card_id: str) -> None:
    nxt = api.get("/review/next", params={"deck": deck}).json()
    assert nxt["card_id"] == card_id
    r = api.post("/review/answer", json={"card_id": card_id, "rating": "good", "review_token": nxt["review_token"]})
    assert r.status_code == 200, r.text


# --- the limit: every scope x every exporter, asserted on content ---

@pytest.fixture
def two_decks(api) -> dict:
    """Three notes in Wanted, two in Other; the limit for each scope and the fronts it must
    yield — exactly those, no more (widened) and no fewer (dropped)."""
    did = api.make_deck("Wanted")
    wanted = [api.make_note(deck="Wanted", front=f"wanted{i}") for i in range(3)]
    for i in range(2):
        api.make_note(deck="Other", front=f"other{i}")
    return {
        "collection": ({"scope": "collection"}, {"wanted0", "wanted1", "wanted2", "other0", "other1"}),
        "deck": ({"scope": "deck", "deck_id": did}, {"wanted0", "wanted1", "wanted2"}),
        "notes": ({"scope": "notes", "ids": [wanted[0]["id"], wanted[2]["id"]]}, {"wanted0", "wanted2"}),
        "cards": ({"scope": "cards", "ids": wanted[1]["card_ids"]}, {"wanted1"}),
    }


@pytest.mark.parametrize("scope", ["collection", "deck", "notes", "cards"])
def test_export_apkg_holds_exactly_the_limit(api, two_decks, scope):
    limit, expected = two_decks[scope]
    resp = api.post("/export/apkg", json={"limit": limit, "with_media": False, "legacy": True})
    assert resp.status_code == 200
    pkg = _read_apkg(resp.content)
    assert sorted(pkg["fronts"]) == sorted(expected)
    assert len(pkg["cards"]) == len(expected)


@pytest.mark.parametrize("scope", ["collection", "deck", "notes", "cards"])
def test_export_notes_csv_holds_exactly_the_limit(api, two_decks, scope):
    limit, expected = two_decks[scope]
    resp = api.post("/export/notes-csv", json={
        "limit": limit, "with_html": False, "with_tags": False, "with_deck": False, "with_notetype": False,
    })
    assert resp.status_code == 200
    assert sorted(row[0] for row in _csv_rows(resp.text)) == sorted(expected)  # Front, Back


@pytest.mark.parametrize("scope", ["collection", "deck", "notes", "cards"])
def test_export_cards_csv_holds_exactly_the_limit(api, two_decks, scope):
    limit, expected = two_decks[scope]
    resp = api.post("/export/cards-csv", json={"limit": limit, "with_html": False})
    assert resp.status_code == 200
    assert sorted(row[0] for row in _csv_rows(resp.text)) == sorted(expected)  # question, answer


# --- the limit: a request that cannot mean what it says is refused, never widened ---

@pytest.mark.parametrize("limit", [
    {"scope": "deck"},                                   # no deck_id
    {"scope": "notes"},                                  # no ids
    {"scope": "cards"},                                  # no ids
    {"scope": "bogus"},                                  # unknown scope
    {"deck_id": "1"},                                    # deck_id, but scope defaults to collection
    {"ids": ["1"]},                                      # ids, but scope defaults to collection
    {"scope": "deck", "deck_id": "1", "ids": ["1"]},     # ids do not belong to scope=deck
    {"scope": "notes", "ids": ["1"], "deck_id": "1"},    # deck_id does not belong to scope=notes
    {"scope": "deck", "deckId": "1"},                    # misspelled key
    {"scope": "collection", "deck": "1"},                # unknown key
])
@pytest.mark.parametrize("exporter", ["apkg", "notes-csv", "cards-csv"])
def test_export_limit_that_contradicts_itself_is_422(api, exporter, limit):
    """Each of these used to export something other than what the caller described —
    `{"deck_id": ...}` with the scope left out exported the whole collection."""
    api.make_note(deck="D", front="x")
    assert api.post(f"/export/{exporter}", json={"limit": limit}).status_code == 422


@pytest.mark.parametrize("limit", [
    {"scope": "deck", "deck_id": "999"},
    {"scope": "notes", "ids": ["999"]},
    {"scope": "cards", "ids": ["999"]},
])
@pytest.mark.parametrize("exporter", ["apkg", "notes-csv", "cards-csv"])
def test_export_of_an_unknown_id_is_404(api, exporter, limit):
    """An id that is not in the collection used to yield a 200 and an empty export."""
    api.make_note(deck="D", front="x")
    resp = api.post(f"/export/{exporter}", json={"limit": limit})
    assert resp.status_code == 404
    assert "999" in resp.json()["detail"]


def test_export_names_every_missing_id_among_known_ones(api):
    known = api.make_note(deck="D", front="x")["id"]
    resp = api.post("/export/notes-csv", json={"limit": {"scope": "notes", "ids": [known, "998", "999"]}})
    assert resp.status_code == 404
    assert "998" in resp.json()["detail"] and "999" in resp.json()["detail"]
    assert known not in resp.json()["detail"]


# --- export options ---

def test_export_apkg_with_scheduling_carries_the_review_history(api):
    card_id = api.make_note(deck="D", front="studied")["card_ids"][0]
    _review(api, "D", card_id)
    body = {"limit": {"scope": "collection"}, "with_media": False, "legacy": True}

    with_sched = _read_apkg(api.post("/export/apkg", json={**body, "with_scheduling": True}).content)
    assert with_sched["cards"] == [(int(card_id), 1)]
    assert with_sched["revlog"] == 1

    without = _read_apkg(api.post("/export/apkg", json={**body, "with_scheduling": False}).content)
    assert without["cards"] == [(int(card_id), 0)]  # same card, history stripped
    assert without["revlog"] == 0


def test_export_apkg_with_media_carries_the_referenced_file(api):
    api.post("/media/files", json={"filename": "pic.png", "data_base64": "UE5HREFUQQ=="})
    api.make_note(deck="D", front='<img src="pic.png">')
    body = {"limit": {"scope": "collection"}, "legacy": True}

    with_media = api.post("/export/apkg", json={**body, "with_media": True}).content
    assert _read_apkg(with_media)["media"] == {"0": "pic.png"}
    with zipfile.ZipFile(io.BytesIO(with_media)) as z:
        assert z.read("0") == b"PNGDATA"

    assert _read_apkg(api.post("/export/apkg", json={**body, "with_media": False}).content)["media"] == {}


def test_export_apkg_modern_format_unless_legacy(api):
    api.make_note(deck="D", front="x")
    resp = api.post("/export/apkg", json={"limit": {"scope": "collection"}, "with_media": False})
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        assert "collection.anki21b" in z.namelist()      # zstd-compressed, the modern format
        assert "collection.anki21" not in z.namelist()   # the legacy sqlite only when asked for


# --- imports ---

def _export_then_delete(api) -> tuple[bytes, str, str]:
    """A studied note, exported with its scheduling and then DELETED — so an import has to
    actually bring it back. (Importing into the collection that still holds the note, as this
    test used to, passes whether or not anything was imported.)"""
    note = api.make_note(deck="D", front="exported-note", back="its-back")
    card_id = note["card_ids"][0]
    _review(api, "D", card_id)
    apkg = api.post("/export/apkg", json={"limit": {"scope": "collection"}, "with_scheduling": True}).content
    assert api.delete(f"/notes/{note['id']}").json()["count"] == 1
    assert api.get("/collection").json()["note_count"] == 0
    return apkg, note["id"], card_id


def test_import_apkg_brings_the_note_back(api):
    apkg, note_id, card_id = _export_then_delete(api)
    resp = api.post("/import/apkg", params={"with_scheduling": True},
                    files={"file": ("e.apkg", apkg, "application/octet-stream")})
    assert resp.status_code == 200
    body = resp.json()
    assert [n["id"]["nid"] for n in body["log"]["new"]] == [note_id]
    assert body["log"]["found_notes"] == 1
    assert body["changes"]["note"] is True
    assert api.get(f"/notes/{note_id}").json()["fields"] == {"Front": "exported-note", "Back": "its-back"}
    assert api.get(f"/cards/{card_id}").json()["reps"] == 1  # with_scheduling: history restored


def test_import_apkg_without_scheduling_imports_the_card_as_new(api):
    apkg, note_id, card_id = _export_then_delete(api)
    resp = api.post("/import/apkg", params={"with_scheduling": False},
                    files={"file": ("e.apkg", apkg, "application/octet-stream")})
    assert resp.status_code == 200
    assert api.get(f"/notes/{note_id}").json()["fields"]["Front"] == "exported-note"
    card = api.get(f"/cards/{card_id}").json()
    assert (card["reps"], card["type"], card["queue"]) == (0, 0, 0)


def test_csv_metadata(api):
    csv = b"front1,back1\nfront2,back2\n"
    resp = api.post("/import/csv/metadata", files={"file": ("notes.csv", csv, "text/csv")})
    assert resp.status_code == 200
    meta = resp.json()
    assert meta["delimiter"] == "COMMA"
    assert len(meta["column_labels"]) == 2
    assert meta["preview"] == [{"vals": ["front1", "back1"]}, {"vals": ["front2", "back2"]}]


def _basic_id(api) -> str:
    return next(n["id"] for n in api.get("/notetypes").json() if n["name"] == "Basic")


def test_import_csv_creates_notes(api):
    did = api.make_deck("CsvDeck")
    csv = b"hello,world\nfoo,bar\n"
    resp = api.post(
        "/import/csv",
        params={"deck_id": did, "notetype_id": _basic_id(api)},
        files={"file": ("notes.csv", csv, "text/csv")},
    )
    assert resp.status_code == 200
    assert [n["fields"] for n in resp.json()["log"]["new"]] == [["hello", "world"], ["foo", "bar"]]
    found = api.post("/search/notes", json={"query": "deck:CsvDeck"}).json()
    assert found["count"] == 2
    fields = [api.get(f"/notes/{nid}").json()["fields"] for nid in found["note_ids"]]
    assert sorted(f["Front"] for f in fields) == ["foo", "hello"]
    assert sorted(f["Back"] for f in fields) == ["bar", "world"]


def test_import_csv_into_an_unknown_deck_is_404(api):
    """Used to answer 200, create a deck NAMED after the id and import into it."""
    decks_before = api.get("/decks").json()
    resp = api.post(
        "/import/csv",
        params={"deck_id": "999", "notetype_id": _basic_id(api)},
        files={"file": ("notes.csv", b"hello,world\n", "text/csv")},
    )
    assert resp.status_code == 404
    assert api.get("/decks").json() == decks_before
    assert api.get("/collection").json()["note_count"] == 0


def test_import_csv_with_an_unknown_notetype_is_404(api):
    """Used to answer 200 having imported nothing (the rows land in `missing_notetype`)."""
    did = api.make_deck("CsvDeck")
    resp = api.post(
        "/import/csv",
        params={"deck_id": did, "notetype_id": "999"},
        files={"file": ("notes.csv", b"hello,world\n", "text/csv")},
    )
    assert resp.status_code == 404
    assert api.get("/collection").json()["note_count"] == 0
