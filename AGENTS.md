# anki-api — agent guide

Guidance for working in this repo. See `README.md` for user-facing docs and
`docs/ENDPOINTS.md` for the full endpoint list.

## What this is

A headless REST API (FastAPI) wrapping the `anki` PyPI package's `Collection` —
the Anki Rust backend via pylib/rsbridge, **no Qt/GUI**. It exposes Anki's full
feature set over HTTP so a custom UI can use it as a backend. ~130 endpoints
across 21 domains; full feature parity with Anki.

## Commands

```sh
uv sync                       # install (Python pinned <3.13; uv picks 3.12)
uv run anki-api               # run server (needs ANKI_API_COLLECTION env)
uv run pytest                 # full suite (unit + e2e, in-process via TestClient)
uv run pytest tests/unit      # fast unit tests
uv run pytest tests/e2e/test_<domain>.py   # one domain
# real over-the-wire smoke:
ANKI_API_COLLECTION=$(mktemp -d)/c.anki2 ANKI_API_PORT=8799 uv run anki-api &
BASE=http://127.0.0.1:8799 uv run python tests/smoke.py
```

`ANKI_API_COLLECTION` is required (path to a `.anki2`, created if absent).
Others: `ANKI_API_HOST`, `ANKI_API_PORT`, `ANKI_API_V3_SCHEDULER`, `ANKI_API_LANG`.
Sync (all optional, see `config.py`): `ANKI_API_SYNC_AUTH_PATH` (persisted auth
token; defaults next to the collection), `ANKI_API_SYNC_USERNAME`,
`ANKI_API_SYNC_PASSWORD`, `ANKI_API_SYNC_ENDPOINT` (self-hosted sync server; unset
→ AnkiWeb), `ANKI_API_AUTOSYNC_INTERVAL` (seconds between background syncs; `0`
disables).

## Architecture & invariants (do not break these)

- **Single owner / single writer.** The backend takes an exclusive file lock, so
  one process owns one collection. `CollectionHandle` (`collection_handle.py`)
  holds the one open `Collection` + a `threading.RLock`. Access it ONLY via
  `with handle.locked() as col:` — this serializes everything. Get the handle in
  a router with `handle: CollectionHandle = Depends(get_handle)`.
- **Endpoints are sync `def`, not `async`.** FastAPI runs them in a threadpool;
  the lock is the whole concurrency story. Don't make routes `async`.
- **IDs are strings in JSON** (Anki's 64-bit ids exceed JS safe int). Parse with
  `ids.parse_id` / `parse_ids`; serialize with `str(...)`. Never return raw ints.
- **Mutating endpoints return the OpChanges envelope** via
  `schemas.common.mutation(op_changes_result, id=?, count=?)`. The `changes`
  flags tell a reactive UI what to refresh. For `OpChangesWithCount` pass
  `count=out.count` and use `out.changes`; for `OpChangesWithId` use `out.id`.
- **Errors are loud.** `errors.py` maps `anki.errors.*` to specific HTTP codes;
  unrecognised backend errors become a 500. NEVER add silent fallbacks that mask
  bugs (e.g. returning a default for a missing id) — raise `HTTPException(404)`.
  Watch for anki methods that silently return a default (e.g. `decks.get_config`
  returns the Default preset for an unknown id — detect by id mismatch and 404).

## Layout

`src/anki_api/`: `app.py` (factory + lifespan, router registration),
`__main__.py` (CLI entry point — `uvicorn.run` on `ANKI_API_HOST`/`ANKI_API_PORT`),
`collection_handle.py`, `config.py`, `deps.py` (`get_handle` dependency),
`errors.py`, `ids.py`, `schemas/common.py` (OpChanges + Mutation), and one file
per domain in `routers/`. Tests mirror under `tests/unit` and `tests/e2e` — mostly
one `test_<domain>.py` per domain, plus cross-cutting suites (`test_failure_paths.py`,
`test_card_actions_extra.py`); `tests/conftest.py` has the `api`/`handle`/`settings`
fixtures and a `V1Client` wrapper.

## Adding a domain/endpoint (tests-first)

1. **Introspect the real `anki` API first** — read the installed package under
   `.venv/lib/python*/site-packages/anki/` (esp. `_backend_generated.py` for the
   full backend surface) or run `uv run python -c "..."`. Never invent method
   names; ground every call in what's actually there.
2. Write the test in `tests/e2e/test_<domain>.py` (success + failure paths).
3. Implement `routers/<domain>.py` (the `with handle.locked()` + `mutation()`
   patterns above), register it in `app.py`'s import + `include_router` loop.
   Put literal routes (e.g. `/stock`, `/change-info`) BEFORE `/{id}` routes.
4. Run `uv run pytest tests/e2e/test_<domain>.py`, then the full suite.
5. After changing routes, regenerate `docs/ENDPOINTS.md` (the generator is the
   inline script in the "Add docs" commit; or just describe new routes there).
6. Commit messages are written as a **prompt** to recreate the work.

## Gotchas learned during the build

- Review answers need `card.start_timer()` before `build_answer`; `/review/next`
  hands out an opaque base64 `review_token` (serialized `SchedulingStates`) that
  `/review/answer` decodes (avoids a queue-shift race).
- Some "flag" proto fields are `Empty` presence markers, not bools — e.g.
  `ExportLimit.whole_collection` needs `.SetInParent()`.
- `find_dupes`/`strip_html_media` need the process-global i18n initialised;
  `CollectionHandle.__init__` calls `anki.lang.set_lang(...)`.
- Field/template/notetype edits are in-memory mutators (`add_field`, etc.) — then
  persist with `col.models.update_dict(notetype)`.
- Image Occlusion `occlusions` is a cloze string:
  `{{c1::image-occlusion:rect:left=..:top=..:width=..:height=..}}`.

## Limitations

TTS synthesis is OS-dependent (works on macOS/Windows; returns 400 on Linux —
no native engine). Sync is a client of AnkiWeb/self-hosted servers; full sync
closes+reopens the collection under the lock. One collection per process.
