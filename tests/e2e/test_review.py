import time


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
    in_three = api.get(f"/cards/{card_id}").json()
    assert (in_three["type"], in_three["queue"]) == (2, 2)  # a review card
    # `due` of a review card is a day number; "0" is today, so "3" is three days later
    api.post("/review/set-due-date", json={"card_ids": [card_id], "days": "0"})
    assert in_three["due"] - api.get(f"/cards/{card_id}").json()["due"] == 3


def test_answer_without_timer_field_still_works(api):
    # time_taken_ms omitted -> server starts the timer; must not error.
    card_id = api.make_note(deck="Study")["card_ids"][0]
    nxt = api.get("/review/next", params={"deck": "Study"}).json()
    out = api.post("/review/answer", json={
        "card_id": card_id, "rating": "again", "review_token": nxt["review_token"],
    })
    assert out.status_code == 200
    assert api.get(f"/cards/{card_id}").json()["reps"] == 1  # the answer was recorded


def test_unknown_deck_is_404_and_is_not_created(api):
    """`deck=` names a deck to select. An unknown name used to CREATE that deck — on a GET —
    and report an empty queue for it, so a typo both littered the collection and read as
    "nothing due"."""
    api.make_note(deck="Study")
    decks_before = api.get("/decks").json()
    assert api.get("/review/counts", params={"deck": "Stduy"}).status_code == 404
    assert api.get("/review/next", params={"deck": "Stduy"}).status_code == 404
    assert api.get("/decks").json() == decks_before


# --- Grade Now (POST /review/grade-now) -------------------------------------------------


def _revlog_rows(api, card_id):
    return api.get("/revlog", params={"card_ids": card_id}).json()["entries"]


def test_grade_now_writes_one_revlog_row_and_schedules_like_an_answer(api):
    """A new card graded `good` leaves the new state with one revlog row stamped now
    carrying the rating; a second card in the same deck is untouched."""
    graded = api.make_note(deck="Atoms", front="a")["card_ids"][0]
    other = api.make_note(deck="Atoms", front="b")["card_ids"][0]
    before_ms = int(time.time() * 1000)
    out = api.post("/review/grade-now", json={"card_ids": [graded], "rating": "good"})
    after_ms = int(time.time() * 1000)
    assert out.status_code == 200, out.text
    assert out.json()["changes"]["card"] is True

    rows = _revlog_rows(api, graded)
    assert len(rows) == 1
    assert rows[0]["ease"] == 3  # good
    assert before_ms <= int(rows[0]["id"]) <= after_ms
    card = api.get(f"/cards/{graded}").json()
    assert card["reps"] == 1
    assert card["type"] != 0 and card["queue"] != 0  # out of the new state
    assert _revlog_rows(api, other) == []
    assert api.get(f"/cards/{other}").json()["reps"] == 0


def test_grade_now_again_vs_easy_schedule_differently(api):
    """Easy on a new card graduates it straight to review; Again keeps it in learning —
    the same outcome an ordinary answer gives."""
    easy = api.make_note(deck="Atoms", front="e")["card_ids"][0]
    again = api.make_note(deck="Atoms", front="a")["card_ids"][0]
    api.post("/review/grade-now", json={"card_ids": [easy], "rating": "easy"})
    api.post("/review/grade-now", json={"card_ids": [again], "rating": "again"})
    easy_view, again_view = api.get(f"/cards/{easy}").json(), api.get(f"/cards/{again}").json()
    assert (easy_view["type"], easy_view["queue"]) == (2, 2) and easy_view["interval"] >= 1
    assert again_view["type"] == 1 and again_view["interval"] == 0
    assert _revlog_rows(api, easy)[0]["ease"] == 4
    assert _revlog_rows(api, again)[0]["ease"] == 1


def test_grade_now_keeps_a_suspended_card_suspended(api):
    """Anki's grade_now UNSUSPENDS a suspended card (anki 25.09.4: queue -1 -> 1). The
    endpoint re-suspends every card that was suspended before, so the card is graded (revlog
    row, reps) AND still suspended; an unsuspended card in the same call stays unsuspended."""
    suspended = api.make_note(deck="Atoms", front="s")["card_ids"][0]
    free = api.make_note(deck="Atoms", front="f")["card_ids"][0]
    api.post("/cards/actions/suspend", json={"card_ids": [suspended]})
    assert api.get(f"/cards/{suspended}").json()["queue"] == -1

    out = api.post("/review/grade-now", json={"card_ids": [suspended, free], "rating": "good"})
    assert out.status_code == 200, out.text
    s = api.get(f"/cards/{suspended}").json()
    assert s["queue"] == -1  # still suspended
    assert s["reps"] == 1 and s["type"] == 1  # but graded
    assert len(_revlog_rows(api, suspended)) == 1
    assert api.get(f"/cards/{free}").json()["queue"] == 1  # not suspended by the call


def test_grade_now_works_under_a_zero_zero_preset(api):
    """A deck whose preset allows 0 new and 0 review cards a day: grading still happens."""
    preset = api.post("/deck-presets", json={"name": "Nobody studies"}).json()["id"]
    api.put(f"/deck-presets/{preset}", json={"new": {"perDay": 0}, "rev": {"perDay": 0}})
    card = api.make_note(deck="Atoms", front="z")["card_ids"][0]
    deck_id = api.get(f"/cards/{card}").json()["deck_id"]
    assert api.post(f"/decks/{deck_id}/preset", json={"preset_id": preset}).status_code == 200
    assert api.get("/review/counts", params={"deck": "Atoms"}).json() == {"new": 0, "learn": 0, "review": 0}

    api.post("/review/grade-now", json={"card_ids": [card], "rating": "easy"})
    view = api.get(f"/cards/{card}").json()
    assert (view["type"], view["queue"], view["reps"]) == (2, 2, 1)
    assert len(_revlog_rows(api, card)) == 1


def test_grade_now_with_fsrs_gives_the_card_a_memory_state(api):
    api.put("/fsrs", json={"enabled": True})
    card = api.make_note(deck="Atoms", front="m")["card_ids"][0]
    assert api.get(f"/cards/{card}").json()["memory_state"] is None
    api.post("/review/grade-now", json={"card_ids": [card], "rating": "good"})
    state = api.get(f"/cards/{card}").json()["memory_state"]
    assert state["stability"] > 0 and state["difficulty"] > 0


def test_grade_now_unknown_card_is_404_and_grades_nothing(api):
    card = api.make_note(deck="Atoms", front="k")["card_ids"][0]
    out = api.post("/review/grade-now", json={"card_ids": [card, "123456789"], "rating": "good"})
    assert out.status_code == 404
    assert "123456789" in out.text
    assert _revlog_rows(api, card) == []
    assert api.get(f"/cards/{card}").json()["reps"] == 0


def test_grade_now_unknown_rating_is_422(api):
    card = api.make_note(deck="Atoms", front="r")["card_ids"][0]
    assert api.post("/review/grade-now", json={"card_ids": [card], "rating": "great"}).status_code == 422
    assert api.get(f"/cards/{card}").json()["reps"] == 0
