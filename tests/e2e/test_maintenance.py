"""Collection maintenance [parity]: check database, optimize, empty cards."""


def test_check_database(api):
    api.make_note(deck="D", front="a")
    out = api.post("/collection/check-database").json()
    assert out["ok"] is True
    assert isinstance(out["report"], str) and out["report"]


def test_optimize(api):
    assert api.post("/collection/optimize").json()["ok"] is True


def test_empty_cards_report_and_remove(api):
    api.make_note(deck="D", front="a")
    report = api.get("/collection/empty-cards").json()
    assert isinstance(report, dict)  # {} when there are no empty cards
    out = api.post("/collection/empty-cards/remove").json()
    assert out["count"] == 0  # nothing to remove


def test_empty_cards_remove_deletes_exactly_the_empty_card(api):
    """The only test of this endpoint used to be the nothing-to-remove case, which a remover
    that deleted the wrong cards would also pass."""
    note = api.post("/notes", json={
        "deck": "D", "notetype": "Basic (optional reversed card)",
        "fields": {"Front": "f", "Back": "b", "Add Reverse": "y"},
    }).json()
    bystander = api.make_note(deck="D", front="bystander")
    forward, reverse = note["card_ids"]
    api.put(f"/notes/{note['id']}", json={"fields": {"Add Reverse": ""}})  # the reverse card is now empty

    report = api.get("/collection/empty-cards").json()
    assert report["notes"] == [{"note_id": note["id"], "card_ids": [reverse]}]

    assert api.post("/collection/empty-cards/remove").json()["count"] == 1
    assert api.get(f"/cards/{reverse}").status_code == 404
    assert api.get(f"/notes/{note['id']}").json()["card_ids"] == [forward]
    assert api.get(f"/notes/{bystander['id']}").json()["card_ids"] == bystander["card_ids"]
    assert "notes" not in api.get("/collection/empty-cards").json()
