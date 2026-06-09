# anki-api

A headless REST API server that wraps an Anki collection — create, edit, search,
and review cards over HTTP **without launching the Anki desktop app**. Built
directly on the [`anki`](https://pypi.org/project/anki/) package's `Collection`
(the Rust backend via pylib/rsbridge); no Qt/GUI. Intended as a backend for a
custom Anki UI.

## Status

Feature-parity build: ~110 endpoints over the full Anki feature set, backed by a
rigorous test suite (186 pytest tests, unit + e2e in-process over the ASGI app).
See [`docs/api-surface-v1.md`](docs/api-surface-v1.md) for the designed surface
and [`_dev/experiments/`](_dev/experiments/) for the feasibility spikes the
design is grounded in.

Implemented domains: decks, deck options/presets, notes & fields, notetypes &
templates (incl. change-notetype), cards (flags/suspend/bury/forget/reposition/
set-deck/restore), review (v3 scheduler, answer, set-due-date), search & browse
(configurable columns, find/replace, find-duplicates), tags, statistics, config
& preferences, media, import/export (apkg + CSV), FSRS controls, filtered decks
& custom study, undo/redo, collection maintenance (check db / optimize / empty
cards), type-in-the-answer, TTS, and UI-chrome helpers (timespan formatting,
markdown, help links).

Not implemented (niche): Image Occlusion note authoring, and sync (proven
reachable in experiment 04; an opt-in module — the server is a single-collection
backend by design).

## Architecture (from the experiments)

- **Single owner.** The Anki backend takes an exclusive lock on a collection
  file, so one server process owns exactly one collection, held open for the
  process lifetime. The desktop app and this server cannot share a file.
- **Single writer.** All access is serialized through one lock; FastAPI sync
  endpoints run in a threadpool, so the lock is the whole concurrency story.
- **OpChanges envelope.** Every mutating endpoint returns Anki's `OpChanges`
  flags so a reactive UI knows which views to refresh.
- **IDs as strings.** Anki's 64-bit ids exceed JS `Number.MAX_SAFE_INTEGER`, so
  they are serialized as strings everywhere.
- **Sync is out of scope for v1** (proven reachable; an opt-in module later).

## Running

```sh
# Python is pinned <3.13 (the anki wheel has no 3.13 build yet).
uv sync
ANKI_API_COLLECTION=/path/to/collection.anki2 uv run anki-api
# -> http://127.0.0.1:8765  (OpenAPI docs at /docs)
```

Environment variables:

| Var | Default | Meaning |
|---|---|---|
| `ANKI_API_COLLECTION` | *(required)* | Path to the `.anki2` file to serve (created if absent). |
| `ANKI_API_HOST` | `127.0.0.1` | Bind host. |
| `ANKI_API_PORT` | `8765` | Bind port. |
| `ANKI_API_V3_SCHEDULER` | `true` | Enable the v3 scheduler on open. |
