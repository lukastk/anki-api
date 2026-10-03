# API reference

Auto-generated from the live routes. The server also serves interactive
OpenAPI docs at **`/docs`** (Swagger UI) and **`/redoc`**, and the raw schema
at `/openapi.json`. All paths are under `/v1`. Every JSON request body refuses a
key it does not declare (422, `extra_forbidden`, naming the key), at every nesting
level; the three plain-dict bodies (`PUT /v1/preferences`,
`PUT /v1/stats/graph-preferences`, `PUT /v1/deck-presets/{id}`) are checked against
the stored shape and answer 422 the same way.
**129 endpoints across 21 domains.**


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
| `POST` | `/v1/cards/views` | Bulk card views for a card-id selection, with each card's first_review/latest_review (epoch seconds as JSON integers, null when never reviewed; `/v1/stats/card/{id}` reports the same values as strings — protobuf int64 — so compare as numbers). |
| `GET` | `/v1/cards/{card_id}` | One card's view — the same shape as an element of POST /cards/views, first_review/latest_review included. |
| `PATCH` | `/v1/cards/{card_id}` | Write scheduling columns directly (mutate-then-update_card). Meant for |

## deck-presets

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/deck-presets` |  |
| `POST` | `/v1/deck-presets` |  |
| `DELETE` | `/v1/deck-presets/{preset_id}` |  |
| `GET` | `/v1/deck-presets/{preset_id}` |  |
| `PUT` | `/v1/deck-presets/{preset_id}` | Merge a partial config into the preset (deep-merges nested new/rev/lapse). 422 for a key the preset does not have, at any level. |
| `POST` | `/v1/deck-presets/{preset_id}/restore-defaults` |  |

## decks

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/decks` |  |
| `POST` | `/v1/decks` |  |
| `POST` | `/v1/decks/reparent` |  |
| `GET` | `/v1/decks/tree` | Deck-browser tree with per-deck due/new/learn counts. |
| `DELETE` | `/v1/decks/{deck_id}` | Delete the deck and its cards; `count` is the number of cards removed. 404 if there is no such deck. |
| `GET` | `/v1/decks/{deck_id}` |  |
| `GET` | `/v1/decks/{deck_id}/preset` | The effective deck-options preset (config group) for this deck. |
| `POST` | `/v1/decks/{deck_id}/preset` | Assign an existing deck-options preset to this deck. 404 if the deck or the preset does not exist. |
| `POST` | `/v1/decks/{deck_id}/rename` |  |

## filtered-decks

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/filtered-decks` | Create a filtered deck gathering up to `limit` cards matching `search`, in `order` — an index into Anki's filtered-deck orders (0 oldest reviewed first, 1 random, 2 intervals ascending, 3 intervals descending, 4 lapses, 5 added, 6 due, 7 reverse added, 8 retrievability ascending, 9 retrievability descending); 422 outside 0-9. |
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
| `POST` | `/v1/export/apkg` | An .apkg of exactly what `limit` names: `{"scope": "collection"}` (the default), `{"scope": "deck", "deck_id": …}`, `{"scope": "notes", "ids": […]}` or `{"scope": "cards", "ids": […]}`. A limit that contradicts itself — a `deck_id` or `ids` that does not belong to the scope (including a `deck_id` with the scope left out), a missing one, an unknown key — is a 422, never a wider export; a deck, note or card id that does not exist is a 404 naming it. |
| `POST` | `/v1/export/cards-csv` | A tab-separated question/answer export of exactly the cards `limit` names (same `limit`, 422 and 404 rules as `/v1/export/apkg`). |
| `POST` | `/v1/export/notes-csv` | A tab-separated export of exactly the notes `limit` names (same `limit`, 422 and 404 rules as `/v1/export/apkg`). |
| `POST` | `/v1/import/apkg` | Import an .apkg upload; the response is Anki's import log plus the change set. 400 if the upload is not a package (not a zip, no collection inside, truncated). |
| `POST` | `/v1/import/csv` | Import notes from a CSV using detected metadata, into the given deck + notetype (column order maps to the notetype's fields). 404 for a `deck_id` or `notetype_id` that does not exist. |
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
| `GET` | `/v1/notes/find-duplicates` | Notes sharing the same value in `field` (Notes > Find Duplicates). 404 if no notetype has a field of that name (matched case-insensitively). |
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
| `DELETE` | `/v1/notetypes/{notetype_id}` | Delete the notetype. 404 if there is no such notetype. |
| `GET` | `/v1/notetypes/{notetype_id}` |  |
| `PATCH` | `/v1/notetypes/{notetype_id}` | Change `name`, `css` and/or `sort_field_index` (422 if the index is not one of the notetype's fields; nothing is applied). |
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
| `GET` | `/v1/review/counts` | Today's new/learn/review counts for the current deck, or for the deck named `deck`. 404 if there is no deck of that name (it is not created). |
| `GET` | `/v1/review/next` | The next card due for review, or null if the queue is empty. 404 if `deck` names no deck (it is not created). |
| `POST` | `/v1/review/set-due-date` |  |

## search

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/browser/active-columns` | The active browser columns for `mode` (`cards`, the default, or `notes`; anything else is a 422). |
| `PUT` | `/v1/browser/active-columns` | Persist the active columns for the given mode (stored in collection config). 422 for a `mode` other than `cards` / `notes`, or a key that is not a column of `GET /v1/browser/columns`. |
| `GET` | `/v1/browser/columns` | All available browser columns, with their card/note-mode labels. |
| `POST` | `/v1/browser/rows` | Rendered rows for a window of card ids, with cells aligned to the active |
| `POST` | `/v1/search/cards` | Card ids matching the Anki search `query`. Unsorted unless `order` names a browser column that is `sortable_cards` in `GET /v1/browser/columns`; `reverse` flips that order. 422 for an unknown or unsortable column, or for `reverse` without an `order`. |
| `POST` | `/v1/search/find-replace` |  |
| `POST` | `/v1/search/notes` | Note ids matching the Anki search `query`. Unsorted unless `order` names a browser column that is `sortable_notes`; `reverse` flips that order. Same 422 rules as `/v1/search/cards`. |

## stats

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/stats/card/{card_id}` | Structured card info: the data behind Anki's Card Info screen (404 for an unknown card). (`GET /v1/cards/{id}/stats`, which returned Anki's deprecated webview page, was removed 2026-10-03.) |
| `GET` | `/v1/stats/graph-preferences` |  |
| `PUT` | `/v1/stats/graph-preferences` |  |
| `GET` | `/v1/stats/graphs` | All stats-graph data for cards matching `search` over the last `days`. |
| `GET` | `/v1/stats/today` |  |

## sync

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/sync` | Perform an incremental sync. Reports if a full sync is additionally required. |
| `POST` | `/v1/sync/backup-remote` | Shadow-download the server's collection into a timestamped backup file. |
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
| `POST` | `/v1/collection/backup` | Back up the LIVE collection to backups/ (Anki's own .colpkg backups, with its |
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
| `GET` | `/v1/help/link` | Resolve a HelpPage enum index to its versioned Anki-manual URL (for the contextual Help buttons a full client shows on dialogs). 422 for an index outside the enum. |
| `POST` | `/v1/render/markdown` |  |
