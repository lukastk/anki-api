# anki-api

[![CI](https://github.com/lukastk/anki-api/actions/workflows/ci.yml/badge.svg)](https://github.com/lukastk/anki-api/actions/workflows/ci.yml)

A headless REST API server that wraps an Anki collection — create, edit, search,
review, sync, import/export, and manage cards over HTTP **without launching the
Anki desktop app**. Built directly on the [`anki`](https://pypi.org/project/anki/)
package's `Collection` (the Rust backend via pylib/rsbridge); no Qt/GUI. Intended
as a backend for building a custom Anki UI.

## Status

**Full feature parity** with the Anki feature set: 128 endpoints across 21
domains, backed by a rigorous test suite (207 pytest tests — unit + e2e in-process
over the ASGI app, plus a real-`uvicorn` smoke test and a live sync test against a
self-hosted sync server).

- **API reference:** [`docs/ENDPOINTS.md`](docs/ENDPOINTS.md) (auto-generated), plus
  interactive **`/docs`** (Swagger UI) and **`/redoc`** served by the running app.
- **Design surface:** [`docs/api-surface-v1.md`](docs/api-surface-v1.md).
- **Feasibility spikes the design is grounded in:** [`_dev/experiments/`](_dev/experiments/).

Implemented domains: decks, deck options/presets, notes & fields, notetypes &
templates (incl. change-notetype), cards (flags / suspend / bury / forget /
reposition / set-deck / restore), review (v3 scheduler, answer, set-due-date),
search & browse (configurable columns, find/replace, find-duplicates), tags,
statistics, config & preferences, media, import/export (apkg + CSV), FSRS
controls, filtered decks & custom study, undo/redo, collection maintenance (check
db / optimize / empty cards), **sync** (AnkiWeb or self-hosted), image occlusion
authoring, type-in-the-answer, TTS, and UI-chrome helpers (timespan formatting,
markdown, help links).

## Install & run

Requires [`uv`](https://docs.astral.sh/uv/). Python is pinned to `<3.13` (the
`anki` wheel has no 3.13 build yet; `uv` selects 3.12 automatically).

```sh
uv sync
ANKI_API_COLLECTION=/path/to/collection.anki2 uv run anki-api
# -> http://127.0.0.1:8765   (interactive docs at /docs)
```

The `.anki2` file is created if it doesn't exist. **Do not point this at a
collection the Anki desktop app has open** — the backend takes an exclusive lock
(see Architecture).

### Environment variables

| Var | Default | Meaning |
|---|---|---|
| `ANKI_API_COLLECTION` | *(required)* | Path to the `.anki2` file to serve (created if absent). |
| `ANKI_API_HOST` | `127.0.0.1` | Bind host. |
| `ANKI_API_PORT` | `8765` | Bind port. |
| `ANKI_API_V3_SCHEDULER` | `true` | Enable the v3 scheduler on open. |
| `ANKI_API_LANG` | `en` | Backend locale (used by i18n-dependent helpers). |
| `ANKI_API_SYNC_USERNAME` | *(unset)* | AnkiWeb email — if set (with the password), the server auto-logs-in on startup. |
| `ANKI_API_SYNC_PASSWORD` | *(unset)* | AnkiWeb password (used once to obtain a token, which is then persisted). |
| `ANKI_API_SYNC_ENDPOINT` | *(unset)* | Sync server URL; unset = AnkiWeb. |
| `ANKI_API_AUTOSYNC_INTERVAL` | `0` | Seconds between background incremental syncs; `0` disables. |
| `ANKI_API_SYNC_AUTH_PATH` | *(next to collection)* | Where the persisted sync token (`0600`) is stored. |

### Example

```sh
BASE=http://127.0.0.1:8765/v1

# create a deck and a note
curl -s -XPOST $BASE/decks -d '{"name":"Spanish"}' -H 'content-type: application/json'
curl -s -XPOST $BASE/notes -H 'content-type: application/json' -d '{
  "deck":"Spanish","notetype":"Basic",
  "fields":{"Front":"the house","Back":"la casa"},"tags":["nouns"]}'

# get the next due card, then answer it
curl -s "$BASE/review/next?deck=Spanish"
curl -s -XPOST $BASE/review/answer -H 'content-type: application/json' -d '{
  "card_id":"<id>","rating":"good","review_token":"<token from /review/next>"}'
```

## Architecture

Grounded in the feasibility experiments under [`_dev/experiments/`](_dev/experiments/):

- **Single owner.** The Anki backend takes an exclusive lock on a collection
  file, so one server process owns exactly one collection, held open for the
  process lifetime. The desktop app and this server cannot share a file (a second
  opener gets a clean `409`).
- **Single writer.** All access is serialized through one lock; FastAPI sync
  endpoints run in a threadpool, so the lock is the whole concurrency story.
- **OpChanges envelope.** Every mutating endpoint returns Anki's `OpChanges`
  flags (`card`, `note`, `deck`, `study_queues`, …) so a reactive UI knows which
  views to refresh.
- **IDs as strings.** Anki's 64-bit ids exceed JS `Number.MAX_SAFE_INTEGER`, so
  they are serialized as strings everywhere.
- **Errors are loud.** Backend errors map to specific HTTP statuses
  (404/409/422/400/502); anything unrecognised surfaces as a `500` rather than
  being silently swallowed.

### Sync

The server is a sync **client**, like the desktop app or AnkiDroid. `POST
/sync/login` (omit `endpoint` for AnkiWeb, or pass a self-hosted server URL), then
`POST /sync` for an incremental sync. A first sync or a schema change reports
`required: full_upload | full_download | full_sync`; the client then calls `POST
/sync/full-upload` or `/sync/full-download` explicitly (these overwrite one side,
so the direction is a deliberate choice). Full sync briefly closes and reopens the
collection under the writer lock. The collection this server owns and the
AnkiWeb/self-hosted account converge through normal sync — so your phone and
desktop stay in step with changes made via the API.

**Staying logged in & auto-sync.** The auth token from `/sync/login` is persisted
to a `0600` sidecar file, so a login survives restarts. If `ANKI_API_SYNC_USERNAME`
/ `ANKI_API_SYNC_PASSWORD` are set, the server logs in automatically on startup
when no token is present (the password is only used to mint a token; it isn't
stored). Set `ANKI_API_AUTOSYNC_INTERVAL` to have the server run an incremental
sync on that cadence in the background. Auto-sync never performs a full sync on its
own — if one is required it's logged and left for you to resolve via the explicit
full-upload/download endpoints, so there's no silent data loss.

## Limitations

- **TTS is OS-dependent.** Audio synthesis (`/media/tts/*`, for `{{tts:}}` cards)
  delegates to the operating system's native speech engine — available on macOS
  and Windows, but **not on Linux**, where the backend reports "not implemented
  for this OS". On a Linux host these endpoints return a clean `400`; run the
  server on macOS/Windows for working TTS. No per-card AV-tag extraction endpoint
  exists yet, so a UI currently derives what to play from the rendered card HTML.
- **Single collection per process.** By design (the exclusive lock). Serve
  multiple collections with multiple processes on different ports.
- **Image Occlusion** authoring is supported, but occlusion *geometry* is the
  caller's responsibility (the API takes structured shapes; it doesn't run the
  drawing editor).
- **Python `<3.13`** until an `anki` 3.13 wheel ships.

## Development

```sh
uv run pytest                 # full suite (unit + e2e, in-process)
uv run pytest tests/unit      # fast unit tests only
# real over-the-wire smoke test:
ANKI_API_COLLECTION=$(mktemp -d)/c.anki2 ANKI_API_PORT=8799 uv run anki-api &
BASE=http://127.0.0.1:8799 uv run python tests/smoke.py
```

Layout: `src/anki_api/` — `app.py` (factory + lifespan), `collection_handle.py`
(the single-owner lock), `config.py`, `errors.py`, `ids.py`, `schemas/`, and one
module per domain under `routers/`. Tests mirror this under `tests/unit` and
`tests/e2e`.

The project was built experiments-first; the durable findings from those spikes
live in [`_dev/experiments/EXPERIMENTS_PLAN.md`](_dev/experiments/EXPERIMENTS_PLAN.md).

## License

[AGPL-3.0-or-later](LICENSE). This project builds on the `anki` package, which is
AGPL-3.0-licensed, and the AGPL's network clause applies to software served over a
network — so if you run a modified version as a network service, you must offer
its source to users. Fine for personal/self-hosted use; a real consideration if
you offer it as a hosted product.
