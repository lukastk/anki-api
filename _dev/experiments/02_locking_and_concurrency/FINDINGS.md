# 02 — Locking & concurrency

**Status:** done (2026-06-09). Verdict: ✅ single-owner model confirmed and enforced by the backend.

## What we learned

- **Opening a collection twice is hard-blocked by the backend.** A second `Collection(path)` while the first is open raises `DBError: Anki already open, or media currently syncing.` — a clean, catchable exception (not corruption). This *enforces* the single-owner model for us. → The desktop app and our server can never hold the same file simultaneously; that's a hard constraint to surface to users, not a bug to work around.
- **Within one process, the Rust backend tolerates threaded access surprisingly well.** 4 threads × 25 `add_note` calls:
  - With an explicit `threading.Lock`: 0 errors, exact count (105).
  - **Without** the lock: *also* 0 errors, exact count (105). The backend (rsbridge → a `Backend` holding an internal mutex) appears to serialize DB operations internally.

## Design implications

- **One process per collection file**, enforced by the backend's lock. The server owns the file for its lifetime; opening Anki desktop on the same file will fail (and vice-versa). Document loudly.
- Despite the backend's internal serialization, the server should **still funnel writes through one lock / single worker** for correctness guarantees at the Python object level (note objects are mutable, multi-step ops aren't logically atomic) and for predictable error handling. Don't rely on the backend's implicit serialization as the design.
- **Hold one long-lived `Collection` open** for the server's lifetime rather than open/close per request (open/close is heavy and the lock is exclusive anyway). Confirmed cheap and stable in `03`.
- Error mapping: catch `anki.errors.DBError` (and friends) → translate to a clean HTTP 409/503 ("collection busy/locked").

## Artifacts

- [`spike.py`](spike.py) — double-open test + serialized/unserialized threaded write tests.
