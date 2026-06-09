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
