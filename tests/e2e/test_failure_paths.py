"""Failure-path coverage across routers: 400 / 404 / 409 / 422."""

import pytest


@pytest.mark.parametrize("path", ["/notes/abc", "/cards/abc", "/decks/not-a-number"])
def test_non_numeric_id_is_400(api, path):
    assert api.get(path).status_code == 400


@pytest.mark.parametrize("path", ["/notes/123456", "/cards/123456", "/decks/123456"])
def test_missing_resource_is_404(api, path):
    assert api.get(path).status_code == 404


def test_create_note_unknown_notetype_is_404(api):
    r = api.post("/notes", json={"deck": "D", "notetype": "Nope", "fields": {"Front": "x"}})
    assert r.status_code == 404


def test_create_note_unknown_field_is_422(api):
    r = api.post("/notes", json={"deck": "D", "notetype": "Basic", "fields": {"Bogus": "x"}})
    assert r.status_code == 422


def test_invalid_search_is_400(api):
    r = api.post("/search/cards", json={"query": "("})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_search"


def test_bad_rating_is_422(api):
    card_id = api.make_note(deck="S")["card_ids"][0]
    nxt = api.get("/review/next", params={"deck": "S"}).json()
    r = api.post("/review/answer", json={
        "card_id": card_id, "rating": "perfect", "review_token": nxt["review_token"],
    })
    assert r.status_code == 422


def test_bad_review_token_is_400(api):
    card_id = api.make_note(deck="S")["card_ids"][0]
    r = api.post("/review/answer", json={
        "card_id": card_id, "rating": "good", "review_token": "not-valid-base64-proto!!",
    })
    assert r.status_code == 400


def test_undo_empty_is_409(api):
    assert api.post("/undo").status_code == 409


def test_missing_body_field_is_422(api):
    # pydantic validation: /decks requires "name"
    assert api.post("/decks", json={}).status_code == 422
