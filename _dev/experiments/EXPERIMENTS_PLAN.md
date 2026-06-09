# Experiments plan

Throwaway prototyping for **anki-api** — a headless REST API server wrapping an Anki collection, so a collection can be mutated/reviewed without launching the Anki desktop app (and a custom UI could use it as a backend).

Architecture decision already made (option B): build directly on the `anki` PyPI package's `Collection` (the Rust backend via pylib/rsbridge), **no Qt/GUI**. See conversation feasibility writeup.

Each experiment is a numbered subdirectory. The only deliverable is **learnings** — write them in the experiment's `FINDINGS.md` and summarize under its "Findings" section here. Experiment code is throwaway; we rewrite for `src/` once confident.

Status legend: `todo` · `in progress` · `done` · `skipped`.

---

## Group A — Backend feasibility (core derisking)

### `00_open_collection_headless`

**Status:** done (2026-06-09)

**Questions**
- Does `pip install anki` provide a working wheel on this machine's Python (3.13.5)? If not, which Python version do we need?
- Can we open a `Collection` from a fresh `.anki2` file with **no Qt installed** and no GUI?
- Can we create a note + card, add a deck, search, and read it back?
- What's the minimal import surface and object lifecycle (open / close / save)?

**Deliverable**
- A script that creates a fresh collection, adds a deck + note, searches for it, prints the card, closes cleanly. Plus the exact dependency/Python pin that works.

**Findings** *(full writeup in [`00_open_collection_headless/FINDINGS.md`](00_open_collection_headless/FINDINGS.md))*
- ✅ Works end-to-end headless, **no Qt** (`aqt` not pulled in; 13 light deps).
- `anki==25.9.4`; wheel needs **CPython ≤3.12** (uv auto-picked 3.12.12; no 3.13 wheel). Pin `>=3.9,<3.13`.
- Full CRUD loop validated: deck/note/card create, search via Anki query DSL, `card.question()` renders HTML, persists across reopen.
- `col.sched_ver()` == 2 on fresh collections; v3 scheduler is a separate toggle — verify in `01`.

---

### `01_review_scheduling_fsrs`

**Status:** done (2026-06-09)

**Questions**
- Can we drive the v3 scheduler headlessly: get the due queue, fetch a card's answer-button intervals, answer a review, and persist the new scheduling state?
- Can FSRS be enabled/used via the backend without the GUI?
- Does scheduling state survive close/reopen?

**Deliverable**
- A script that reviews a card end-to-end (queue → answer Good → verify due date moved) against a collection built in `00`.

**Findings** *(full writeup in [`01_review_scheduling_fsrs/FINDINGS.md`](01_review_scheduling_fsrs/FINDINGS.md))*
- ✅ Full review loop headless: `set_v3_scheduler(True)` → `sched.get_queued_cards` → `describe_next_states` → `build_answer` → `answer_card`. Persists; revlog written.
- **Gotcha:** must `card.start_timer()` before `build_answer` or it throws (GUI normally does this). Server must manage shown-at timing.
- Ratings: `anki.scheduler_pb2.CardAnswer.{AGAIN=1,HARD=2,GOOD=3,EASY=4}`. Interval labels wrapped in bidi isolate marks — strip for UI.
- FSRS on/off via `col.set_config("fsrs", True)` sticks; per-preset param optimization deferred.
- Queue is driven by the **selected deck** — server needs an explicit "reviewing which deck" notion.

---

### `02_locking_and_concurrency`

**Status:** done (2026-06-09)

**Questions**
- Confirm the exclusive-lock model: what happens if two processes open the same collection? Error type?
- How do we safely serialize writes inside one long-lived server process?
- Cost of open/close per request vs. holding one Collection open for the server's lifetime.

**Deliverable**
- A note on the ownership model + the failure mode of concurrent access, validated experimentally.

**Findings** *(full writeup in [`02_locking_and_concurrency/FINDINGS.md`](02_locking_and_concurrency/FINDINGS.md))*
- ✅ Single-owner enforced by backend: second open raises `DBError: Anki already open` (catchable, not corruption).
- Backend serializes threaded writes internally (unserialized 4×25 writes → 0 errors), but design still mandates one writer-lock + one long-lived Collection per process.
- Map `anki.errors.DBError` → HTTP 409/503. Desktop app + server can't share a file (loud constraint).

---

## Group B — Server shape

### `03_fastapi_collection_server`

**Status:** done (2026-06-09)

**Questions**
- Can we wrap a single long-lived `Collection` behind FastAPI with serialized access (one writer) and expose clean REST endpoints?
- Validate the architecture end-to-end: `POST /notes`, `GET /cards?search=`, `POST /cards/{id}/answer`.
- Threading model: is the backend safe across threads, or do we funnel all calls through one worker/lock?

**Deliverable**
- A minimal FastAPI app proving the REST → Collection mapping with serialized access.

**Findings** *(full writeup in [`03_fastapi_collection_server/FINDINGS.md`](03_fastapi_collection_server/FINDINGS.md))*
- ✅ Whole architecture holds over real HTTP. `CollectionHandle` = `Collection` + one `threading.Lock`; **sync `def`** endpoints run in FastAPI's threadpool, lock serializes them.
- 20 concurrent `POST /notes` → all 200, all persisted. `/decks`, `/cards?search=`, `/review/next`, `/cards/{id}/answer` all work.
- One Collection per process opened in `lifespan`; `DBError` on open → fail fast.
- Design note: `/review/next` should hand the client an opaque review token (the `states`) to pass back to `answer`, instead of re-deriving from the queue (avoids a queue-shift race).

---

### `04_sync_self_hosted_server`

**Status:** done (2026-06-09)

**Questions**
- Can the API interop with a self-hosted Anki sync server — mutate it *and* keep local copies in sync?
- Can the backend drive sync (incremental + full) at controlled checkpoints? What does a conflict look like?

**Deliverable**
- A note on the interop topology (hub model) and whether server-as-source-of-truth + checkpoint sync is viable.

**Findings** *(full writeup in [`04_sync_self_hosted_server/FINDINGS.md`](04_sync_self_hosted_server/FINDINGS.md))*
- ✅ **Hub model works.** The self-hosted `anki.syncserver` is the canonical store; the API server is a sync *client* of it, alongside the phone/desktop. Verified bidirectional propagation A↔hub↔B end to end.
- The sync server is **not a mutation API** — you sync to it, you never edit its files directly (manual: "must sync, not manually copy files"). API mutates its *own* local collection + `sync_collection(auth)` to the hub.
- API contract: `sync_login(u,p,endpoint)` → `SyncAuth`; `sync_collection(auth)` performs the incremental exchange inline (`NO_CHANGES` ≠ "nothing transferred"); full sync needs `close_for_full_sync()` → `full_upload_or_download(...)` → `reopen(after_full_sync=True)`.
- AnkiWeb is the **same** path with `endpoint=None` — self-hosted just repoints it.
- **Design impact:** full sync requires closing the collection → must serialize under the same lock and return 503 during that window. Sync after each mutation/batch to minimize forced full-sync conflicts.

---

## Conclusion (2026-06-09): GO

All experiments (00–04) passed. Option B is validated end to end: a headless `anki`-package `Collection` behind a FastAPI server, single-owner + single-writer-lock, does everything we need (create, search, review with FSRS, persist) over real HTTP — **no Anki desktop app required** — and **interoperates with a self-hosted sync server as a sync client** (exp 04), so other devices stay in sync via the hub. A custom UI can sit on top of this API. Recommended production shape:

- **Stack:** FastAPI + `anki==25.9.x`, Python pinned `>=3.9,<3.13`.
- **Core:** a `CollectionHandle` (one `Collection` + one `threading.Lock`), opened in `lifespan`, sync `def` endpoints.
- **Single owner:** one collection per process; surface "collection busy / open elsewhere" as HTTP 409. Desktop app and server cannot share a file.
- **Review tokens:** `/review/next` returns an opaque token (the card's next-`states`) the client passes back to `/answer`, instead of re-deriving from the queue.
- **Sync (validated, exp 04):** API server is a **sync client** of a self-hosted `anki.syncserver` hub; mutate locally, `sync_collection()` after each mutation/batch. Full sync requires closing the collection → serialize under the lock, return 503 during the window. Never edit the hub's files directly.
- **Open scope for v1 → v2:** auth, media serving, note edit/delete, notetype/template mgmt, undo. All on the same `Collection`.
- **License watch:** `anki` is AGPL-3.0 — serving it over a network triggers source-disclosure obligations if ever distributed/exposed publicly. Fine for self-host.

## Resolved decisions (2026-06-09)

- **Approach:** Option B — build on the `anki` PyPI package's `Collection` directly. No Qt/GUI dependency. Server is the sole owner of a collection.
- **Goal:** a RESTful API usable as a backend for a custom Anki UI, with the full feature set (create cards, review, search, decks) over time.
- **Experiment VCS:** experiment code is gitignored; `EXPERIMENTS_PLAN.md` and `*/FINDINGS.md` are tracked.
- **Scope — no sync in v1:** the API server controls **one specific Anki client** (its own collection); v1 ships **without** a sync server (Case 0). Sync (exp 04) is proven reachable on the same `Collection` and stays a future opt-in module — the API would simply be "just another sync client," like AnkiDroid/desktop. Deferring it requires no architectural change beyond handling the full-sync close/reopen window when added.

## Still to decide

- ~~Sync topology / whether v1 ships sync~~ → **decided: no sync in v1** (see Resolved decisions). Topology choice (join external hub vs. operate own) deferred to whenever sync lands.
- Web framework (FastAPI assumed for the spike; recommend keeping).
- Single-collection-per-process vs. multi-collection server (multi would need one lock + handle per collection).
