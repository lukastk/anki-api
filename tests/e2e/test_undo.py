def test_undo_status_empty_on_fresh_collection(api):
    status = api.get("/undo/status").json()
    assert status["undo"] == ""
    assert status["redo"] == ""


def test_undo_redo_roundtrip(api):
    did = api.make_deck("Temp")
    status = api.get("/undo/status").json()
    assert status["undo"]  # a non-empty label like "Add Deck"

    undo = api.post("/undo").json()
    assert undo["changes"]  # OpChanges present
    # deck should be gone after undo
    assert api.get(f"/decks/{did}").status_code == 404

    redo = api.post("/undo/redo").json()
    assert redo["changes"]
    assert api.get(f"/decks/{did}").status_code == 200


def test_undo_when_empty_is_409(api):
    assert api.post("/undo").status_code == 409
