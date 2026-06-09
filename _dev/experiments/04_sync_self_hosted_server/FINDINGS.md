# 04 — Interop with a self-hosted Anki sync server

**Status:** done (2026-06-09). Verdict: ✅ works via the **hub model** — the API server is a sync *client* of the self-hosted server, alongside all other devices.

## The architecture question, answered

The user wants the API to "mutate the self-hosted server directly, as well as any local copies." The supported way to do that:

- The **self-hosted `anki.syncserver` is the canonical store / source of truth.** It is *not* a mutation API — it speaks only the sync protocol.
- **Every participant is a sync client of that hub:** our API server, the phone, the desktop app.
- Our **API server keeps its own local working `Collection`**, mutates it (create/review/etc.), and calls `col.sync_collection(auth)` to push to the hub. Changes then propagate to every other client on their next sync.
- **You do NOT open the server's stored collection files directly** — the manual is explicit: *"You must sync your data to the server, not manually copy files."* Direct file access bypasses USN/sync bookkeeping and corrupts sync state. The hub model is the only safe path.

So "mutate the server + local copies" = **everyone syncs to the hub; the hub reconciles.** Demonstrated end to end.

## What the spike proved

A real `python -m anki.syncserver` subprocess (`SYNC_USER1`, `SYNC_BASE`, `SYNC_HOST`, `SYNC_PORT`) as the hub, with two independent local collections (A = "API server", B = "a local copy"):

1. **A → hub:** fresh hub demands `FULL_UPLOAD`; A uploads its collection.
2. **hub → B:** fresh empty B demands `FULL_DOWNLOAD`; B receives A's data (gets the "Paris" note).
3. **B mutates + pushes**, **A pulls** → A incrementally receives B's "Tokyo" note. **Bidirectional propagation confirmed.**

## Sync API contract (carry into `src/`)

```python
auth = col.sync_login(user, pass, "http://host:port/")   # -> SyncAuth(hkey, endpoint, io_timeout_secs)
status = col.sync_status(auth)        # pre-check: NO_CHANGES | NORMAL_SYNC | FULL_SYNC
out = col.sync_collection(auth, sync_media=False)  # PERFORMS the incremental sync inline
# out.required: NO_CHANGES | NORMAL_SYNC | FULL_SYNC | FULL_DOWNLOAD | FULL_UPLOAD
```

- **`sync_collection()` does the incremental exchange itself.** `required == NO_CHANGES` after it means "normal sync complete, no *full* sync needed" — NOT "nothing transferred" (we saw notes propagate while it reported `NO_CHANGES`). Don't gate transfer on the return value.
- **Full sync is a separate, heavier dance** and requires closing the collection:
  ```python
  col.close_for_full_sync()
  col.full_upload_or_download(auth=auth, server_usn=out.server_media_usn, upload=<bool>)
  col.reopen(after_full_sync=True)
  ```
  `FULL_UPLOAD`/`FULL_DOWNLOAD` tell you the direction; bare `FULL_SYNC` = server can't pick a side (genuine conflict) → the caller/app must choose which side wins (data loss on the other).
- Media syncs separately: `col.sync_media(auth)` / `col.media_sync_status()`.
- AnkiWeb is the *same* client path with `endpoint=None` (defaults to AnkiWeb) — self-hosted just points the endpoint elsewhere. So self-hosted and AnkiWeb interop are one mechanism.

## Implications for the API server design

- **Full sync vs. the single-writer lock (important):** incremental `sync_collection()` runs against the open collection — fine. But **full sync requires `close_for_full_sync()` → `reopen()`**, a window where the collection is unavailable. The server must serialize this under the same lock as everything else and reject/queue requests during the window (HTTP 503 "syncing"). Full syncs are triggered by schema changes (e.g. adding a notetype) and first upload/download.
- **Source-of-truth strategy:** to keep divergence (and forced full-sync conflicts) minimal, have the API **sync right after each mutation/batch**, and document that other clients should sync before+after editing. The more frequent the sync, the more likely changes merge incrementally instead of conflicting.
- **Two viable topologies:**
  1. **API server = a client of an external self-hosted hub** (what we tested). Cleanest separation; phone/desktop already sync to the same hub.
  2. **API server is the primary, runs its own hub for others** — would mean running `anki.syncserver` as a *separate* process on a *separate* `SYNC_BASE`, and the API still syncs to it as a client (they can't share one file). Equivalent to (1) with co-located processes.
- `SYNC_BASE` "must not be the same location as your normal Anki data folder" — keep the hub's store and the API's working collection on separate paths (the single-owner lock from exp 02 makes this mandatory anyway).

## Artifacts

- [`spike.py`](spike.py) — launches the sync server subprocess and drives A↔hub↔B propagation. Prints `OK`.
