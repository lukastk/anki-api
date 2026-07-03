# API reference

Auto-generated from the live routes. The server also serves interactive
OpenAPI docs at **`/docs`** (Swagger UI) and **`/redoc`**, and the raw schema
at `/openapi.json`. All paths are under `/v1`.
**128 endpoints across 21 domains.**


## cards

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/cards/actions/bury` |  |
| `POST` | `/v1/cards/actions/forget` | Reset cards to the 'new' state (clears scheduling history). |
| `POST` | `/v1/cards/actions/reposition` | Reposition new cards' due order (only affects cards in the new queue). |
| `POST` | `/v1/cards/actions/restore-buried-and-suspended` | Clear both buried and suspended states for a selection in one undoable op. |
| `POST` | `/v1/cards/actions/set-deck` |  |
| `POST` | `/v1/cards/actions/set-flag` |  |
| `POST` | `/v1/cards/actions/suspend` |  |
| `POST` | `/v1/cards/actions/unbury` |  |
| `POST` | `/v1/cards/actions/unsuspend` |  |
| `POST` | `/v1/cards/views` | Bulk card views for a card-id selection (avoids N round-trips — e.g. when |
| `GET` | `/v1/cards/{card_id}` |  |
| `PATCH` | `/v1/cards/{card_id}` | Write scheduling columns directly (mutate-then-update_card). Meant for |
| `GET` | `/v1/cards/{card_id}/stats` | The fully-rendered Card Info HTML that desktop/AnkiDroid show. |

## deck-presets

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/deck-presets` |  |
| `POST` | `/v1/deck-presets` |  |
| `DELETE` | `/v1/deck-presets/{preset_id}` |  |
| `GET` | `/v1/deck-presets/{preset_id}` |  |
| `PUT` | `/v1/deck-presets/{preset_id}` | Merge a partial config into the preset (deep-merges nested new/rev/lapse). |
| `POST` | `/v1/deck-presets/{preset_id}/restore-defaults` |  |

## decks

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/decks` |  |
| `POST` | `/v1/decks` |  |
| `POST` | `/v1/decks/reparent` |  |
| `GET` | `/v1/decks/tree` | Deck-browser tree with per-deck due/new/learn counts. |
| `DELETE` | `/v1/decks/{deck_id}` |  |
| `GET` | `/v1/decks/{deck_id}` |  |
| `GET` | `/v1/decks/{deck_id}/preset` | The effective deck-options preset (config group) for this deck. |
| `POST` | `/v1/decks/{deck_id}/preset` |  |
| `POST` | `/v1/decks/{deck_id}/rename` |  |

## filtered-decks

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/filtered-decks` |  |
| `POST` | `/v1/filtered-decks/custom-study` |  |
| `POST` | `/v1/filtered-decks/{deck_id}/empty` |  |
| `POST` | `/v1/filtered-decks/{deck_id}/rebuild` |  |

## fsrs

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/fsrs` |  |
| `PUT` | `/v1/fsrs` |  |
| `POST` | `/v1/fsrs/compute-params` | Optimize FSRS parameters from review history. Returns an empty params list |
| `POST` | `/v1/fsrs/evaluate` | Evaluate current params against review history (400 if history is too thin). |

## image-occlusion

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/notes/image-occlusion` |  |
| `GET` | `/v1/notes/{note_id}/image-occlusion` |  |
| `PUT` | `/v1/notes/{note_id}/image-occlusion` |  |
| `POST` | `/v1/notetypes/image-occlusion` | Ensure the Image Occlusion notetype exists; returns its id. |

## import-export

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/export/apkg` |  |
| `POST` | `/v1/export/cards-csv` |  |
| `POST` | `/v1/export/notes-csv` |  |
| `POST` | `/v1/import/apkg` |  |
| `POST` | `/v1/import/csv` | Import notes from a CSV using detected metadata, into the given deck + |
| `POST` | `/v1/import/csv/metadata` | Detected metadata (delimiter, column count, html-ness) for an uploaded CSV, |

## media

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/media/check` |  |
| `POST` | `/v1/media/files` |  |
| `DELETE` | `/v1/media/files/{filename}` |  |
| `GET` | `/v1/media/files/{filename}` |  |

## notes

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/notes` |  |
| `GET` | `/v1/notes/find-duplicates` | Notes sharing the same value in `field` (Notes > Find Duplicates). |
| `DELETE` | `/v1/notes/{note_id}` |  |
| `GET` | `/v1/notes/{note_id}` |  |
| `PUT` | `/v1/notes/{note_id}` |  |
| `GET` | `/v1/notes/{note_id}/cards` |  |

## notetypes

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/notetypes` |  |
| `POST` | `/v1/notetypes` |  |
| `POST` | `/v1/notetypes/change` |  |
| `POST` | `/v1/notetypes/change-info` |  |
| `GET` | `/v1/notetypes/stock` |  |
| `DELETE` | `/v1/notetypes/{notetype_id}` |  |
| `GET` | `/v1/notetypes/{notetype_id}` |  |
| `PATCH` | `/v1/notetypes/{notetype_id}` |  |
| `POST` | `/v1/notetypes/{notetype_id}/clone` |  |
| `GET` | `/v1/notetypes/{notetype_id}/default-deck` | The deck last used with this notetype (Add screen picks it on notetype switch). |
| `POST` | `/v1/notetypes/{notetype_id}/fields` |  |
| `DELETE` | `/v1/notetypes/{notetype_id}/fields/{field_name}` |  |
| `POST` | `/v1/notetypes/{notetype_id}/fields/{field_name}/rename` |  |
| `POST` | `/v1/notetypes/{notetype_id}/fields/{field_name}/reposition` |  |
| `POST` | `/v1/notetypes/{notetype_id}/templates` |  |
| `DELETE` | `/v1/notetypes/{notetype_id}/templates/{template_name}` |  |
| `PUT` | `/v1/notetypes/{notetype_id}/templates/{template_name}` |  |
| `POST` | `/v1/notetypes/{notetype_id}/templates/{template_name}/reposition` |  |

## preferences

| Method | Path | Description |
|---|---|---|
| `DELETE` | `/v1/config/{key}` |  |
| `GET` | `/v1/config/{key}` |  |
| `PUT` | `/v1/config/{key}` |  |
| `GET` | `/v1/preferences` |  |
| `PUT` | `/v1/preferences` | Partial update: merges the given fields into the current preferences. |

## review

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/review/answer` |  |
| `GET` | `/v1/review/counts` |  |
| `GET` | `/v1/review/next` | The next card due for review, or null if the queue is empty. |
| `POST` | `/v1/review/set-due-date` |  |

## search

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/browser/active-columns` |  |
| `PUT` | `/v1/browser/active-columns` | Persist the active columns for the given mode (stored in collection config). |
| `GET` | `/v1/browser/columns` | All available browser columns, with their card/note-mode labels. |
| `POST` | `/v1/browser/rows` | Rendered rows for a window of card ids, with cells aligned to the active |
| `POST` | `/v1/search/cards` |  |
| `POST` | `/v1/search/find-replace` |  |
| `POST` | `/v1/search/notes` |  |

## stats

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/stats/card/{card_id}` | Structured card info (complements the rendered HTML at /cards/{id}/stats). |
| `GET` | `/v1/stats/graph-preferences` |  |
| `PUT` | `/v1/stats/graph-preferences` |  |
| `GET` | `/v1/stats/graphs` | All stats-graph data for cards matching `search` over the last `days`. |
| `GET` | `/v1/stats/today` |  |

## sync

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/sync` | Perform an incremental sync. Reports if a full sync is additionally required. |
| `POST` | `/v1/sync/full-download` | Overwrite this collection with the server's (full download). |
| `POST` | `/v1/sync/full-upload` | Overwrite the server's collection with this one (full upload). |
| `GET` | `/v1/sync/health` | Local sync-health facts — no server contact, no auth required. |
| `POST` | `/v1/sync/login` |  |
| `POST` | `/v1/sync/logout` |  |
| `POST` | `/v1/sync/media` |  |
| `GET` | `/v1/sync/status` |  |

## system

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/collection` |  |
| `POST` | `/v1/collection/check-database` | Tools > Check Database (fsck). Returns the report and whether it was ok. |
| `GET` | `/v1/collection/empty-cards` | Report of notes that produce empty cards (Tools > Empty Cards). |
| `POST` | `/v1/collection/empty-cards/remove` |  |
| `POST` | `/v1/collection/optimize` | Vacuum/optimize the underlying database. |
| `GET` | `/v1/health` |  |

## tags

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/tags` |  |
| `POST` | `/v1/tags/actions/add` |  |
| `POST` | `/v1/tags/actions/delete` | Remove the given tags entirely (from all notes). |
| `POST` | `/v1/tags/actions/remove` |  |
| `POST` | `/v1/tags/clear-unused` |  |
| `POST` | `/v1/tags/rename` |  |
| `POST` | `/v1/tags/reparent` |  |
| `POST` | `/v1/tags/set-collapsed` |  |
| `GET` | `/v1/tags/tree` |  |

## tts

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/media/tts/synthesize` |  |
| `GET` | `/v1/media/tts/voices` |  |

## typing

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/notes/extract-cloze-for-typing` |  |
| `POST` | `/v1/scheduler/compare-answer` |  |

## undo

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/undo` | Undo the last operation (409 undo_empty if nothing to undo). |
| `POST` | `/v1/undo/redo` |  |
| `GET` | `/v1/undo/status` | What undo/redo would do next (empty strings mean nothing to undo/redo). |

## util

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/format/timespan` |  |
| `GET` | `/v1/help/link` | Resolve a HelpPage enum index to its versioned Anki-manual URL (for the |
| `POST` | `/v1/render/markdown` |  |
