# 03 — FastAPI over a long-lived Collection

**Status:** done (2026-06-09). Verdict: ✅ the whole architecture holds over real HTTP.

## What we proved

A real uvicorn server holding **one** `Collection` for its lifetime, all access serialized through **one `threading.Lock`**, exercised over actual HTTP (`client.py`):

- `GET /decks` → `[{id, name}]`
- `POST /notes` {deck, model, fields, tags} → creates note + cards (auto-creates deck)
- **20 concurrent `POST /notes`** from an 8-thread client → **all 200**, all persisted (21 cards total). The single-writer lock + FastAPI's threadpool handle concurrent HTTP cleanly.
- `GET /cards?search=deck:API::Demo` → 21 cards with fields/queue/due/reps
- `GET /review/next?deck=…` → `{card_id, question (HTML), answer (HTML), buttons:{again,hard,good,easy}}` with interval labels (bidi marks stripped)
- `POST /cards/{id}/answer` {rating} → review recorded, `reps=1`

## The architecture that works (carry into `src/`)

- **`CollectionHandle`**: wraps `Collection` + a `threading.Lock`; every method takes the lock. This is the whole concurrency story — simple and correct.
- **Sync `def` endpoints**, not `async def`. FastAPI runs sync endpoints in a threadpool; the lock serializes them. (If we used `async def` we'd have to manually offload the blocking backend calls — unnecessary.)
- **One collection per process**, opened in FastAPI's `lifespan`, closed on shutdown. `DBError` on open → fail fast ("already open?").
- Pydantic models give request validation for free; map `anki.errors.*` → HTTP codes.

## Gotchas found while building

- **`answer` needs the card's `states`**, which come from `get_queued_cards`. We re-fetch the queue and match by `card.id` to get the right `states`, then `build_answer`. A production design should instead hand the client an opaque review token (the states) from `/review/next` and accept it back on answer, rather than re-deriving — avoids a race if the queue shifts between calls.
- `card.start_timer()` still required before `build_answer` (from exp 01).
- `note.items()` / `dict(note.items())` gives field name→value cleanly for responses.

## Deferred (not blockers)

- Auth, media upload/serving, note *editing*/deletion, notetype/template management, undo, and sync (exp 04). All reachable on the same `Collection` — this spike just didn't need them to prove the architecture.

## Artifacts

- [`app.py`](app.py) — the server. `COLLECTION_PATH=/tmp/x.anki2 uv run uvicorn app:app`.
- [`client.py`](client.py) — HTTP driver that prints `OK`.
