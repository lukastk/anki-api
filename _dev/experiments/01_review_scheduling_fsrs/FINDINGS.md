# 01 — Review / scheduling / FSRS headless

**Status:** done (2026-06-09). Verdict: ✅ full review loop works headless, incl. FSRS toggle.

## What we learned

- **v3 scheduler** enables via `col.set_v3_scheduler(True)` → `col.sched` becomes an `anki.scheduler.v3.Scheduler`. (`col.sched_ver()` still legacy-reports 2; ignore it — `col.v3_scheduler()` is the real check.)
- The complete review loop runs with no GUI:
  1. `queued = col.sched.get_queued_cards(fetch_limit=N)` → `queued.cards`, each entry has `.card` and `.states` (the candidate next states per rating).
  2. `col.sched.describe_next_states(entry.states)` returns the 4 human interval labels (Again/Hard/Good/Easy) — exactly what a custom UI shows on the answer buttons.
  3. Answer: **start the timer first**, then build + submit:
     ```python
     card = col.get_card(card_id)
     card.start_timer()                      # REQUIRED headless — GUI normally does this
     ans = col.sched.build_answer(card=card, states=entry.states, rating=CardAnswer.GOOD)
     col.sched.answer_card(ans)
     ```
  4. Ratings live in `anki.scheduler_pb2.CardAnswer` (`AGAIN=1, HARD=2, GOOD=3, EASY=4`).
- After answering GOOD: card moved new→learning (`queue=1 type=1 reps=1`), a `revlog` row was written, and the new state **persisted across close/reopen**.
- **FSRS**: `col.set_config("fsrs", True)` sticks. (Per-preset FSRS params/optimization is a deeper area for a later experiment, but the on/off switch and the scheduler path are confirmed reachable headlessly.)

## Surprises / gotchas (these will shape the server design)

- **`card.start_timer()` is mandatory** before `build_answer`, else `time_taken()` throws `TypeError` (None timer). The REST layer must manage this — likely: record a server-side "shown at" timestamp when a card is dealt out, and compute elapsed ms on answer (or just call `start_timer()` and accept backend timing).
- `describe_next_states(states)` is indexed by `rating - 1` (it returns a 4-list in Again/Hard/Good/Easy order).
- The interval labels come back wrapped in `⁨…⁩` (Unicode isolate marks, U+2068/U+2069) for bidi — strip if exposing raw to a UI.
- The queue draws from the **selected deck** (`col.decks.select(did)`) / deck limits, just like the app — the server needs an explicit notion of "which deck(s) am I reviewing".

## Artifacts

- [`spike.py`](spike.py) — end-to-end review (queue → describe → answer → persist → reopen) + FSRS toggle. Prints `OK`.
