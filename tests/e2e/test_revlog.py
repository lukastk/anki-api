"""Review log [mosaic-v4]: bulk read (GET /revlog) and history replay (POST /revlog)."""

import time

DAY_MS = 86_400_000


def _entry(card_id, id_ms, *, ease=3, interval=1, last_interval=0, factor=2500, time_ms=4000, type=1):
    return {"card_id": card_id, "id_ms": str(id_ms), "ease": ease, "interval": interval,
            "last_interval": last_interval, "factor": factor, "time_ms": time_ms, "type": type}


def _ids(resp):
    return [e["id"] for e in resp.json()["entries"]]


def _past(days_ago: int) -> int:
    return int(time.time() * 1000) - days_ago * DAY_MS


# --- GET /revlog -------------------------------------------------------------------------

def _two_cards_with_history(api):
    """Two cards, three inserted rows each at known times (30, 20, 10 days ago), types 0/1/2."""
    a = api.make_note(deck="D", front="a")["card_ids"][0]
    b = api.make_note(deck="D", front="b")["card_ids"][0]
    entries = []
    for i, days in enumerate((30, 20, 10)):
        entries.append(_entry(a, _past(days), type=i))
        entries.append(_entry(b, _past(days) + 1, type=i))
    assert api.post("/revlog", json={"entries": entries}).status_code == 200
    return a, b, entries


def test_get_returns_every_row_ordered_by_id_with_string_ids(api):
    a, b, entries = _two_cards_with_history(api)
    out = api.get("/revlog").json()
    assert out["truncated"] is False
    assert [e["id"] for e in out["entries"]] == sorted((e["id_ms"] for e in entries), key=int)
    first = out["entries"][0]
    assert first == {"id": entries[0]["id_ms"], "card_id": a, "usn": -1, "ease": 3, "interval": 1,
                     "last_interval": 0, "factor": 2500, "time_ms": 4000, "type": 0}


def test_get_filters_by_card_ids_repeatable_or_comma_separated(api):
    a, b, _ = _two_cards_with_history(api)
    only_a = api.get("/revlog", params={"card_ids": a}).json()["entries"]
    assert len(only_a) == 3 and {e["card_id"] for e in only_a} == {a}
    repeated = api.get("/revlog", params=[("card_ids", a), ("card_ids", b)]).json()["entries"]
    comma = api.get("/revlog", params={"card_ids": f"{a},{b}"}).json()["entries"]
    assert len(repeated) == 6 and repeated == comma


def test_get_filters_by_time_window_since_inclusive_until_exclusive(api):
    a, b, entries = _two_cards_with_history(api)
    middle_a = int(entries[2]["id_ms"])  # card a, 20 days ago
    middle_b = int(entries[3]["id_ms"])  # card b, 20 days ago (+1 ms)
    out = api.get("/revlog", params={"since_ms": middle_a, "until_ms": middle_b})
    assert _ids(out) == [str(middle_a)]
    out = api.get("/revlog", params={"since_ms": middle_a, "until_ms": middle_b + 1})
    assert _ids(out) == [str(middle_a), str(middle_b)]
    assert len(api.get("/revlog", params={"since_ms": middle_a}).json()["entries"]) == 4


def test_get_filters_by_type(api):
    _two_cards_with_history(api)
    out = api.get("/revlog", params=[("types", 0), ("types", 2)]).json()["entries"]
    assert len(out) == 4 and {e["type"] for e in out} == {0, 2}


def test_get_limit_sets_truncated(api):
    _two_cards_with_history(api)
    out = api.get("/revlog", params={"limit": 4}).json()
    assert len(out["entries"]) == 4 and out["truncated"] is True
    out = api.get("/revlog", params={"limit": 6}).json()
    assert len(out["entries"]) == 6 and out["truncated"] is False
    assert api.get("/revlog", params={"limit": 0}).status_code == 422
    assert api.get("/revlog", params={"limit": 100_001}).status_code == 422


def test_get_returns_manual_rows_with_type_4(api):
    card = api.make_note(deck="D")["card_ids"][0]
    api.post("/review/set-due-date", json={"card_ids": [card], "days": "3"})
    rows = api.get("/revlog", params={"card_ids": card}).json()["entries"]
    assert [r["type"] for r in rows] == [4]
    assert api.get("/revlog", params={"types": 4}).json()["entries"] == rows


def test_get_bad_card_id_is_400(api):
    assert api.get("/revlog", params={"card_ids": "abc"}).status_code == 400


# --- POST /revlog ------------------------------------------------------------------------

def test_inserted_rows_show_in_card_stats(api):
    card = api.make_note(deck="D")["card_ids"][0]
    entries = [_entry(card, _past(5), type=0, interval=-600), _entry(card, _past(3), type=1, interval=3)]
    out = api.post("/revlog", json={"entries": entries})
    assert out.json() == {"inserted": 2}
    stats = api.get(f"/stats/card/{card}").json()
    assert len(stats["revlog"]) == 2
    # newest first; MessageToDict leaves out the proto default, so LEARNING (0) has no key
    assert [r.get("review_kind", "LEARNING") for r in stats["revlog"]] == ["REVIEW", "LEARNING"]
    assert api.get("/revlog", params={"card_ids": card}).json()["entries"][1]["interval"] == 3


def test_insert_marks_the_collection_modified(api):
    """A raw revlog write must bump col.mod, or an incremental sync can see "no changes"."""
    card = api.make_note(deck="D")["card_ids"][0]
    before = int(api.get("/collection").json()["modified"])
    time.sleep(0.01)
    api.post("/revlog", json={"entries": [_entry(card, _past(1))]})
    assert int(api.get("/collection").json()["modified"]) > before


def _assert_refused(api, card, entries, status=422):
    before = api.get("/revlog").json()["entries"]
    out = api.post("/revlog", json={"entries": entries})
    assert out.status_code == status, out.text
    assert api.get("/revlog").json()["entries"] == before  # nothing written
    return out


def test_duplicate_id_against_the_table_is_refused_and_nothing_written(api):
    card = api.make_note(deck="D")["card_ids"][0]
    t = _past(2)
    api.post("/revlog", json={"entries": [_entry(card, t)]})
    out = _assert_refused(api, card, [_entry(card, _past(1)), _entry(card, t)])
    assert str(t) in out.text


def test_duplicate_id_within_the_request_is_refused(api):
    card = api.make_note(deck="D")["card_ids"][0]
    t = _past(2)
    _assert_refused(api, card, [_entry(card, t), _entry(card, t, ease=1)])


def test_unknown_card_is_404_naming_it(api):
    card = api.make_note(deck="D")["card_ids"][0]
    out = _assert_refused(api, card, [_entry(card, _past(2)), _entry("987654321", _past(1))], status=404)
    assert "987654321" in out.text


def test_future_id_is_refused(api):
    card = api.make_note(deck="D")["card_ids"][0]
    _assert_refused(api, card, [_entry(card, _past(1)), _entry(card, _past(-1))])


def test_ease_and_type_bounds(api):
    card = api.make_note(deck="D")["card_ids"][0]
    for bad in ({"ease": 0}, {"ease": 5}, {"type": 4}, {"type": 5}, {"type": -1}):
        _assert_refused(api, card, [_entry(card, _past(1), **bad)])


def test_empty_entries_inserts_nothing(api):
    assert api.post("/revlog", json={"entries": []}).json() == {"inserted": 0}
