"""End-to-end smoke test against a running anki-api server.

Exercises every core router + both blockers over real HTTP. Run via run_smoke.sh
(which boots a server against a throwaway collection and sets BASE).
"""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:8799") + "/v1"


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=15)

    assert c.get("/health").json()["status"] == "ok"
    info = c.get("/collection").json()
    assert info["v3_scheduler"] is True
    print("collection info:", {k: info[k] for k in ("v3_scheduler", "note_count")})

    # --- deck create + tree ---
    deck = c.post("/decks", json={"name": "Smoke::Geo"}).json()
    deck_id = deck["id"]
    assert deck["changes"]["deck"] is True
    print("created deck", deck_id, "changes.deck=", deck["changes"]["deck"])
    tree = c.get("/decks/tree").json()
    assert any(ch["name"] == "Smoke" for ch in tree["children"])

    # --- note create ---
    note = c.post("/notes", json={
        "deck": "Smoke::Geo", "notetype": "Basic",
        "fields": {"Front": "capital of France?", "Back": "Paris"}, "tags": ["geo"],
    }).json()
    note_id = note["id"]
    print("created note", note_id)
    fetched = c.get(f"/notes/{note_id}").json()
    assert fetched["fields"]["Back"] == "Paris"
    assert fetched["tags"] == ["geo"]
    card_id = fetched["card_ids"][0]

    # --- note update ---
    upd = c.put(f"/notes/{note_id}", json={"fields": {"Front": "Capital of France?", "Back": "Paris"}}).json()
    assert upd["changes"]["note"] is True

    # --- search + browser rows ---
    found = c.post("/search/cards", json={"query": "deck:Smoke::Geo"}).json()
    assert found["count"] == 1 and found["card_ids"] == [card_id]
    rows = c.post("/browser/rows", json={"card_ids": found["card_ids"]}).json()
    assert rows[0]["deck"] == "Smoke::Geo"
    print("browser row:", {"q": rows[0]["question"], "deck": rows[0]["deck"]})

    # --- card actions ---
    flag = c.post("/cards/actions/set-flag", json={"card_ids": [card_id], "flag": 1}).json()
    assert flag["count"] == 1
    assert c.get(f"/cards/{card_id}").json()["flag"] == 1
    susp = c.post("/cards/actions/suspend", json={"card_ids": [card_id]}).json()
    assert susp["count"] == 1
    c.post("/cards/actions/unsuspend", json={"card_ids": [card_id]})

    # --- review loop ---
    counts = c.get("/review/counts", params={"deck": "Smoke::Geo"}).json()
    print("counts:", counts)
    nxt = c.get("/review/next", params={"deck": "Smoke::Geo"}).json()
    assert nxt is not None and nxt["card_id"] == card_id
    print("buttons:", nxt["buttons"])
    ans = c.post("/review/answer", json={
        "card_id": card_id, "rating": "good", "review_token": nxt["review_token"], "time_taken_ms": 2500,
    }).json()
    assert ans["changes"]["card"] is True
    assert c.get(f"/cards/{card_id}").json()["reps"] == 1
    print("answered good; reps=1")

    # --- set due date ---
    sdd = c.post("/review/set-due-date", json={"card_ids": [card_id], "days": "3"}).json()
    assert sdd["changes"]["card"] is True

    # --- undo (undoes the set-due-date) ---
    status = c.get("/undo/status").json()
    assert status["undo"]  # non-empty label
    print("undo available:", status["undo"])
    c.post("/undo")

    # --- blocker 1: type-in-the-answer ---
    cmp = c.post("/scheduler/compare-answer", json={"expected": "Paris", "provided": "Pari"}).json()
    assert "comparison_html" in cmp and "<" in cmp["comparison_html"]
    print("compare-answer html len:", len(cmp["comparison_html"]))
    cloze = c.post("/notes/extract-cloze-for-typing", json={"text": "The {{c1::quick}} fox", "ordinal": 1}).json()
    assert cloze["text"] == "quick", cloze
    print("extract-cloze-for-typing ->", cloze["text"])

    # --- blocker 2: tts voices (OS/engine-dependent; 200 list or 400 not-implemented) ---
    vr = c.get("/media/tts/voices")
    if vr.status_code == 200:
        print(f"tts voices available: {len(vr.json())}")
    else:
        print(f"tts not available on this OS ({vr.status_code}: {vr.json().get('error')})")

    # --- delete note ---
    dele = c.delete(f"/notes/{note_id}").json()
    assert dele["count"] == 1

    print("\nSMOKE OK")


if __name__ == "__main__":
    main()
