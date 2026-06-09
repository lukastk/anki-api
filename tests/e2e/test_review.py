def test_full_review_loop(api):
    created = api.make_note(deck="Study", front="2+2?", back="4")
    card_id = created["card_ids"][0]

    counts = api.get("/review/counts", params={"deck": "Study"}).json()
    assert counts == {"new": 1, "learn": 0, "review": 0}

    nxt = api.get("/review/next", params={"deck": "Study"}).json()
    assert nxt["card_id"] == card_id
    assert set(nxt["buttons"]) == {"again", "hard", "good", "easy"}
    assert nxt["review_token"]

    out = api.post("/review/answer", json={
        "card_id": card_id, "rating": "good", "review_token": nxt["review_token"], "time_taken_ms": 1500,
    }).json()
    assert out["changes"]["card"] is True
    assert api.get(f"/cards/{card_id}").json()["reps"] == 1


def test_next_is_null_when_queue_empty(api):
    # fresh collection, default deck, no cards
    assert api.get("/review/next").json() is None


def test_set_due_date(api):
    card_id = api.make_note(deck="Study")["card_ids"][0]
    # answer it first so it leaves the 'new' queue, then reschedule
    nxt = api.get("/review/next", params={"deck": "Study"}).json()
    api.post("/review/answer", json={"card_id": card_id, "rating": "good", "review_token": nxt["review_token"]})
    out = api.post("/review/set-due-date", json={"card_ids": [card_id], "days": "3"}).json()
    assert out["changes"]["card"] is True


def test_answer_without_timer_field_still_works(api):
    # time_taken_ms omitted -> server starts the timer; must not error.
    card_id = api.make_note(deck="Study")["card_ids"][0]
    nxt = api.get("/review/next", params={"deck": "Study"}).json()
    out = api.post("/review/answer", json={
        "card_id": card_id, "rating": "again", "review_token": nxt["review_token"],
    })
    assert out.status_code == 200
