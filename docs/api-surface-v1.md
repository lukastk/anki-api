# Anki REST API — v1 Surface (for sign-off)

> **Status:** draft for review — not yet implemented. Maps the REST surface needed to build a custom Anki UI with **full feature parity**, grounded in the real `anki==25.9.4` package source. Every capability cites a real backend call; none invented.
>
> **Provenance:** produced by a multi-agent discovery pass — 15 parallel agents (one per Anki domain) read the installed package incl. `_backend_generated.py`; a synthesis pass merged them into the unified surface below (**374 endpoints across 15 domains**); a feature-parity critic then audited it against every Anki UI screen. The critic's findings are folded in as the **Parity audit** section at the end — integrate them into the relevant groups during the build.
>
> **Legend:** `[core]` = needed for a basic functional UI · `[parity]` = needed for full desktop/AnkiDroid parity.
> **Out of scope for v1:** sync (collection + media) — proven reachable in experiment `04`, lands later as an opt-in module.

---

# Anki REST API — Unified Surface (v1)

A headless REST API wrapping `anki.collection.Collection`, designed to give a custom UI full feature parity with the desktop Anki app. Endpoints are grouped by resource. Each group is tagged `[core]` (needed for a basic functional UI) or `[parity]` (needed for full desktop parity).

---

## Conventions

**Base & versioning.** All paths are under `/v1`. A single server process owns one open `Collection`; `{collection_id}` in collection-lifecycle paths is the session handle. Single-collection servers may treat it as a constant.

**IDs as strings.** All Anki ids (deck, note, card, notetype, config/preset, revlog) are 64-bit integers that exceed JS `Number.MAX_SAFE_INTEGER`. They are serialized as **strings** in JSON, both in paths and bodies, and parsed back to int server-side.

**Resource naming.** Plural nouns for collections (`/decks`, `/notes`, `/cards`). A specific resource is `/{resource}/{id}`. Sub-resources nest (`/notes/{id}/cards`, `/notetypes/{id}/fields`).

**Bulk / selection actions.** Operations on a *set* of ids, or verbs that don't map to CRUD, use a dedicated action sub-resource:
`POST /{resource}/actions/{action}` with an id-list body, e.g. `POST /cards/actions/suspend {"card_ids":[...]}`.
- Card-driven bulk ops take `card_ids`; note-driven ops take `note_ids`. A few ops accept either via a `by=card|note` discriminator (documented per endpoint).
- Single-resource convenience verbs that are *not* bulk (e.g. rename a deck) use `POST /{resource}/{id}/{verb}`.

**Search DSL.** The Anki search string is parsed entirely in the Rust backend; there is no Python grammar. The API passes the query string through verbatim. Structured search building (sidebar clicks) goes through `/search/build`, `/search/join`, `/search/replace-node` using `SearchNode` (mirrors `search_pb2.SearchNode` oneof). The raw-SQL `custom` sort escape hatch is **not exposed** (injection risk); sorting is by builtin column key + `reverse` only.

**Sort order.** `order` is `{ "none" }`, `{ "column": "<key>", "reverse": bool }`, or `{ "use_stored_sort": true }` (uses the per-mode stored config). Backed by `col._build_sort_mode` → `search_pb2.SortOrder`.

**Pagination for large lists (browse).** There is **no** backend "page of rows" call; `browser_row_for_id` is strictly one id at a time. The canonical flow is:
1. `POST /search/cards` (or `/search/notes`) → full ordered **id list** (held client-side).
2. `POST /browser/rows {ids, mode}` → rendered rows for a visible window of ids (server batches `browser_row_for_id`).
This supports virtualized/lazy rendering without a server-side cursor. Clients page by slicing the id list themselves.

**Mutation envelope (OpChanges).** Every mutating backend call returns `OpChanges` (or `OpChangesWithCount` / `OpChangesWithId`). Mutating endpoints return a uniform envelope:
```json
{ "id": "…",            // present for *WithId ops (create)
  "count": 12,          // present for *WithCount ops
  "changes": {          // OpChanges flags — which views to refresh
    "card": false, "note": false, "deck": false, "tag": false,
    "notetype": false, "config": false, "deck_config": false, "mtime": false,
    "browser_table": false, "browser_sidebar": false, "note_text": false,
    "study_queues": false } }
```
Clients use `changes` to decide which UI to invalidate. `op_made_changes` semantics: if all flags are false, the op was a no-op.

**Undo policy.** Most mutations create an undo entry automatically. `update_card(s)` / `update_note(s)` accept `skip_undo_entry` for high-frequency editor autosaves. Config writes default to **no** undo entry but accept `undoable: true`. Composite client actions can be grouped via `/undo/entries` + merge.

**Errors.** `404` NotFoundError (missing deck/note/card/key). `400` invalid search / invalid enum name / validation. `409` `UndoEmpty`, or a schema-modification requiring full-sync confirmation (`AbortSchemaModification` / `mod_schema(check=True)` raised). `422` malformed body. Errors return `{ "error": "<code>", "message": "<detail>" }`.

**Schema-modifying ops.** Field/template add/remove/reposition, change-notetype, delete preset, etc. set the schema-modified flag (forces a one-way/full sync). Such endpoints surface a `schema_will_change`/confirmation requirement; the current schema value is read via `GET /collection/{id}/schema`.

**Long-running ops.** Optimize/evaluate/simulate FSRS, check-media, render-LaTeX, check-database, import/export are blocking backend calls. Progress is polled via a shared `GET /operations/progress` (`col.latest_progress()`), and cancelled via `POST /operations/abort` (`col.set_wants_abort()`). There is only one global progress channel and one abort flag, so the server **serializes** these jobs per collection.

**File transport.** All backend import/export calls are file-path based. The REST layer bridges this with `POST /files/uploads` (multipart → server path) and `GET /files/downloads/{token}` (export artifact → stream). These are transport helpers, not anki methods.

---

## Deferred to later (not v1 core)

- **Sync (collection + media)** — `sync_collection`, `sync_media`, `media_sync_status`, `abort_media_sync`, `full_sync` flows, login/auth handshakes. Explicitly **out of scope for v1**. (`force_resync` clears the local media DB and is the only sync-adjacent call kept, under Media/[parity].)
- **Scheduler v1→v2 upgrade / v3 toggle** — kept as [parity] read+write but not core.
- **App update check** (`check_for_update`) and **backend logging init** — operational, [parity].
- **Raw DB query/transaction** (`db/query`, `db/transaction`) — advanced/debug only, [parity], read-only query gated.
- **Research dataset export**, **FSRS benchmark** — advanced/dev tooling, [parity].
- **Add-on custom field filters** in template rendering — a headless server has no add-ons; built-in filters (hint/text/tts/type/cloze) render, add-on filters are skipped.

---

## Decks `[core]`

Deck CRUD, tree, current selection, breadcrumbs. Filtered-deck *editing* lives here; filtered-deck *rebuild/empty* lives under Review (cross-referenced). Moving cards between decks lives under Cards (`/cards/actions/set-deck`).

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/decks/tree` | Deck-browser tree with per-deck counts, totals, flags | `?now` (epoch, default server time) | `DeckTreeNode{deck_id,name,level,collapsed,new_count,learn_count,review_count,*_uncapped,total_in_deck,total_including_children,filtered,children[]}` | `col.decks.deck_tree()` |
| GET | `/decks/due-tree` | Tree with scheduler due counts (study scope) | `?top_deck_id` | `DeckTreeNode` tree | `col.sched.deck_due_tree(top_deck_id)` |
| GET | `/decks` | Flat list of names+ids | `?skip_empty_default&include_filtered` | `[{id,name}]` | `col.decks.all_names_and_ids` |
| GET | `/decks/count` | Total deck count | — | `{count}` | `col.decks.count` |
| GET | `/decks/by-name` | Resolve deck id/object by name | `?name` | `{id,name}` or Deck | `col.decks.id_for_name` / `by_name` |
| GET | `/decks/{id}` | Full deck object | — | `Deck{id,name,mtime_secs,usn,common,normal{config_id,description,markdown_description,review_limit,new_limit,desired_retention,…}|filtered{…}}` | `col.decks.get_legacy` / `get_deck` |
| GET | `/decks/{id}/children` | Deck + descendants as (name,id) | `?include_self` | `[{id,name}]` | `col.decks.deck_and_child_name_ids` |
| GET | `/decks/{id}/parents` | Ancestor decks (breadcrumb) | — | `[Deck…]` | `col.decks.parents` |
| GET | `/decks/{id}/card-count` | Cards in deck | `?include_subdecks` | `{count}` | `col.decks.card_count` |
| GET | `/decks/{id}/card-ids` | Card ids in deck | `?children` | `{card_ids[]}` | `col.decks.cids` |
| GET | `/decks/{id}/counts-today` | New+review studied today | — | `{new,review}` | `col._backend.counts_for_deck_today` |
| POST | `/decks` | Create normal deck (idempotent by name; auto-creates `::` parents) | `{name}` | `{id, changes}` | `col.decks.add_normal_deck_with_name` |
| PATCH | `/decks/{id}` | Update deck fields (description, limits, desired_retention) | partial Deck (no `mtime_secs`/`usn`) | `{changes}` | `col.decks.update_dict` / `update_deck` |
| POST | `/decks/{id}/rename` | Rename (cascades to children) | `{new_name}` | `{changes}` | `col.decks.rename` |
| DELETE | `/decks/{id}` | Delete one deck + cards/subdecks | — | `{count,changes}` | `col.decks.remove` |
| POST | `/decks/actions/delete` | Bulk delete decks | `{deck_ids[]}` | `{count,changes}` | `col.decks.remove` |
| POST | `/decks/actions/reparent` | Reparent decks (drag/drop; `new_parent=0`→top) | `{deck_ids[],new_parent}` | `{count,changes}` | `col.decks.reparent` |
| POST | `/decks/{id}/collapsed` | Set collapsed in reviewer/browser scope | `{collapsed, scope:REVIEWER\|BROWSER}` | `{changes}` | `col.decks.set_collapsed` |
| GET | `/decks/current` | Current selected deck | — | `{id, deck}` | `col.decks.get_current_id` / `current` |
| PUT | `/decks/current` | Set current deck | `{deck_id}` | `{changes}` | `col.decks.set_current` |
| GET | `/decks/active` | Active deck ids (selected+subdecks) | — | `{deck_ids[]}` | `col.decks.active` |
| GET | `/decks/{id}/config` | Effective/resolved config for a deck | — | DeckConfig (falls back to default) | `col.decks.config_dict_for_deck_id` |

**Filtered decks (editing)** `[parity]`

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/filtered-decks/{id}` | Get/create filtered-deck draft (`id=0` to create) | — | `FilteredDeckForUpdate{id,name,config{reschedule,search_terms[],delays,preview_*},allow_empty}` | `col.decks.get_or_create_filtered_deck` |
| PUT | `/filtered-decks/{id}` | Create/update filtered deck | `FilteredDeckForUpdate` | `{id,changes}` | `col.decks.add_or_update_filtered_deck` |
| GET | `/filtered-decks/order-labels` | Ordering labels for the Order dropdown | — | `[label…]` | `col.decks.filtered_deck_order_labels` |

> Filtered-deck **rebuild/empty** → see Review. **Move cards to a deck** → `POST /cards/actions/set-deck` (Cards).

---

## Deck Presets (Deck Options) `[parity]`

The desktop Deck Options screen. Canonical save path is the transactional bundle (`/decks/{id}/options`); granular preset CRUD is offered for simpler clients. FSRS optimize/simulate lives under FSRS (cross-referenced).

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/decks/{id}/options` | Full Deck Options bundle for a deck | — | `all_config[{config,use_count}], current_deck{name,config_id,parent_config_ids,limits}, defaults, schema_modified, fsrs, fsrs_health_check, fsrs_legacy_evaluate, apply_all_parent_limits, new_cards_ignore_review_limit, card_state_customizer, days_since_last_fsrs_optimize` | `col.decks.get_deck_configs_for_update` |
| POST | `/decks/{id}/options` | **Transactional save**: upsert/delete presets, assign preset, set limits/flags, FSRS enable/reschedule | `UpdateDeckConfigsRequest{configs[DeckConfig], removed_config_ids[], mode:NORMAL\|APPLY_TO_CHILDREN\|COMPUTE_ALL_PARAMS, limits, new_cards_ignore_review_limit, apply_all_parent_limits, card_state_customizer, fsrs, fsrs_reschedule, fsrs_health_check}` (`target_deck_id` = path id) | `{changes}` | `col.decks.update_deck_configs` |
| GET | `/deck-presets` | List all presets | — | `[{id,name}]` | `col.decks.all_config` |
| GET | `/deck-presets/defaults` | Built-in default values | — | DeckConfig defaults | `get_deck_configs_for_update().defaults` |
| GET | `/deck-presets/{id}` | One preset's full config | — | `DeckConfig{id,name,config{…}}` | `col.decks.get_config` |
| POST | `/deck-presets` | Create preset (optionally clone) | `{name, clone_from_id?}` | `{id,name,config}` | `col.decks.add_config` |
| PUT | `/deck-presets/{id}` | Update/rename a preset | full DeckConfig | `{id}` | `col.decks.update_config` |
| POST | `/deck-presets/{id}/actions/restore-defaults` | Reset preset to defaults (keep id+name) | — | `{id}` | `col.decks.restore_to_default` |
| DELETE | `/deck-presets/{id}` | Delete preset (decks revert to Default; schema mod) | — | `{changes}` | `col.decks.remove_config` |
| GET | `/deck-presets/{id}/decks` | Decks using preset (impact preview) | — | `{deck_ids[], use_count}` | `col.decks.decks_using_config` |
| PUT | `/decks/{id}/preset` | Assign a preset to a deck | `{preset_id}` | `{changes}` | `col.decks.set_config_id_for_deck_dict` (or via options save) |

> Per-preset `Config` fields (all tabs): daily limits, learn/relearn steps, graduating/easy intervals, ease/hard/lapse/interval multipliers, max/min intervals, leech action+threshold, new-card insert/gather/sort order, review order, new/interday mix, bury flags, timer/audio (`cap_answer_time_to_secs`, `show_timer`, `stop_timer_on_answer`, `question_action`, `answer_action`, `wait_for_audio`, `skip_question_when_replaying_answer`), and FSRS fields (see FSRS group).
> FSRS optimize/evaluate/simulate buttons on this screen → **FSRS** group.

---

## Notes & Fields `[core]`

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| POST | `/notes` | Create + persist a note in a deck | `{notetype_id, deck_id, fields(map\|ordered list), tags[]}` | `{id, count, changes}` | `col.new_note` + `col.add_note` |
| POST | `/notes/actions/bulk-create` | Bulk create (import/paste), per-item deck | `{requests:[{notetype_id,deck_id,fields,tags[]}]}` | `{nids[], changes}` | `col.add_notes(AddNoteRequest[])` |
| GET | `/notes/{id}` | Get note fields/tags/notetype/guid/mtime | — | `{id,guid,notetype_id,mtime_secs,usn,tags[],fields[],field_names[]}` | `col.get_note` |
| POST | `/notes/actions/batch-get` | Fetch many notes (table rows) | `{note_ids[]}` | `{notes[]}` | `col.get_note` × n |
| PATCH | `/notes/{id}` | Edit a note's fields/tags (server loads, merges, saves) | `{fields(partial), tags[], skip_undo_entry?}` | `{changes}` | load + setters + `col.update_note` |
| POST | `/notes/actions/bulk-update` | Bulk update (full note state per item) | `{notes:[{note_id,fields,tags[]}], skip_undo_entry?}` | `{changes}` | `col.update_notes` |
| DELETE | `/notes/{id}` | Delete a note + its cards | — | `{count,changes}` | `col.remove_notes` |
| POST | `/notes/actions/delete` | Bulk delete notes | `{note_ids[]}` | `{count,changes}` | `col.remove_notes` |
| POST | `/notes/actions/delete-by-card` | Delete notes owning given cards | `{card_ids[]}` | `{changes}` | `col.remove_notes_by_card` |
| GET | `/notes/{id}/cards` | Card ids of a note | — | `{card_ids[]}` | `col.card_ids_of_note` |
| GET | `/notes` | Search note ids | `?q&order&reverse` | `{note_ids[]}` | `col.find_notes` |
| GET | `/notes/count` | Total note count | — | `{count}` | `col.note_count` |
| POST | `/notes/fields-check` | Empty/duplicate/cloze check on a draft or stored note | `{notetype_id, fields[], tags[]}` *or* `{note_id}` | `{state:NORMAL\|EMPTY\|DUPLICATE\|MISSING_CLOZE\|NOTETYPE_NOT_CLOZE\|FIELD_NOT_CLOZE}` | `Note.fields_check` / `note_fields_check` |
| POST | `/notes/cloze-numbers` | Cloze numbers in draft fields | `{notetype_id, fields[]}` | `{numbers[]}` | `cloze_numbers_in_note` |
| GET | `/notes/add-defaults` | Default deck+notetype for Add screen | `?current_review_card_id` | `{deck_id, notetype_id}` | `col.defaults_for_adding` |
| POST | `/notes/field-names` | Union of field names across notes | `{note_ids[]}` | `{field_names[]}` | `field_names_for_notes` |
| POST | `/notes/actions/after-updates` | Recompute checksums/sort fields; regen cards | `{note_ids[], mark_modified, generate_cards}` | `{count,changes}` | `col.after_note_updates` |
| POST | `/notes/preview` | Render front/back from a draft note | `{notetype_id, fields[], tags[], card_ord, fill_empty}` | `{question_html, answer_html, css, …av_tags}` | `Note.ephemeral_card` / `render_uncommitted_card_legacy` |

**Notes tagging & bulk edit** `[parity]` — see Tags group for `add-tags`/`remove-tags`/`find-replace-tags`; Search/Browse for `find-and-replace`/`change-notetype`/`toggle-mark`/`duplicates`.

> Field wire format: accepts/returns either an **ordered list** (by notetype field ord) or a **name→value map**; mapping uses `col.models.field_map`. `guid` is server-assigned on create and not client-writable (except import).

**Image Occlusion** `[parity]`

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| POST | `/image-occlusion/notetype` | Ensure IO notetype exists (idempotent) | — | `{changes}` | `add_image_occlusion_notetype` |
| GET | `/image-occlusion/fields` | IO field index mapping | `?notetype_id` | `ImageOcclusionFieldIndexes{occlusions,image,header,back_extra}` | `get_image_occlusion_fields` |
| POST | `/image-occlusion/image` | Load image for occlusion editing | `{path}` | `{data(base64), name}` | `col.get_image_for_occlusion` |
| POST | `/image-occlusion/notes` | Create IO note | `{notetype_id,image_path,occlusions,header,back_extra,tags[]}` | `{changes}` | `col.add_image_occlusion_note` |
| GET | `/image-occlusion/notes/{id}` | Read IO note for editing | — | `GetImageOcclusionNoteResponse{note{image_data,occlusions[…],header,back_extra,tags,image_file_name,occlude_inactive}}` | `col.get_image_occlusion_note` |
| PATCH | `/image-occlusion/notes/{id}` | Update IO note | `{occlusions?,header?,back_extra?,tags[]?}` | `{changes}` | `col.update_image_occlusion_note` |

---

## Notetypes & Templates `[parity]`

Notetypes are edited via the legacy `NotetypeDict`. Granular field/template endpoints are conveniences that fetch the dict, mutate, and `update_dict`. After adding fields/templates the client **must re-fetch** (ordinals are backend-assigned) — those POSTs return the reloaded notetype. Many ops are schema-modifying.

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/notetypes` | List notetypes; `?with_counts` adds use_count | `?with_counts` | `[{id,name,use_count?}]` | `all_names_and_ids` / `all_use_counts` |
| GET | `/notetypes/{id}` | Full notetype (config, fields[], templates[], css) | `?format=legacy\|typed` | `{id,name,type,sortf,css,latexPre,latexPost,flds[],tmpls[],originalStockKind}` | `col.models.get` |
| GET | `/notetypes/by-name/{name}` | By name / resolve id | — | notetype \| `{id}` | `by_name` / `id_for_name` |
| GET | `/notetypes/{id}/fields` | Field names+ords | — | `[{ord,name}]` | `field_names` |
| GET | `/notetypes/{id}/fields/detailed` | Fields with full config | — | `[{ord,name,sticky,rtl,font,size,description,plainText,collapsed,excludeFromSearch,preventDeletion}]` | `col.models.get`→`flds` |
| GET | `/notetypes/{id}/cloze-field-ords` | Cloze field ordinals | — | `{ords[]}` | `cloze_fields` |
| GET | `/notetypes/{id}/use-count` | Notes using notetype | — | `{count}` | `use_count` |
| GET | `/notetypes/{id}/notes` | Note ids using notetype | — | `{note_ids[]}` | `nids` |
| GET | `/notetypes/stock` | Built-in stock notetypes | — | `[{kind,name}]` | `stdmodels.get_stock_notetypes` |
| GET | `/notetypes/stock/{kind}` | Stock notetype skeleton | — | notetype dict | `get_stock_notetype_legacy` |
| POST | `/notetypes` | Create (empty / from stock / clone) | `{name, from_kind?\|clone_of_id?, fields?, templates?, css?}` | `{id, notetype}` (final deduped name) | `new`+`add_dict` / stock+`add_dict` / `copy` |
| POST | `/notetypes/{id}/clone` | Clone notetype | `{name?}` | `{id, notetype}` | `col.models.copy(add=True)` |
| PUT | `/notetypes/{id}` | Full update (fields/templates/css/config/name) | full notetype; `?skip_checks` | `{changes}` | `update_dict` |
| PATCH | `/notetypes/{id}` | Partial (name/css/latex/sort field) | `{name?,css?,latexPre?,latexPost?,latexsvg?,sortf?}` | `{changes}` | mutate + `update_dict` |
| DELETE | `/notetypes/{id}` | Delete notetype + notes/cards | — | `{changes}` | `col.models.remove` |
| POST | `/notetypes/{id}/actions/restore-to-stock` | Restore to stock template | `{force_kind?}` | `{changes}` | `restore_notetype_to_stock` |
| POST | `/notetypes/{id}/fields` | Add field (schema mod) | `{name, config?}` | `{changes, notetype}` | `new_field`+`add_field`+`update_dict` |
| PATCH | `/notetypes/{id}/fields/{ord}` | Rename / edit field config | `{name?, sticky?, rtl?, font?, size?, description?, plainText?, collapsed?, excludeFromSearch?, preventDeletion?}` | `{changes}` | `rename_field` + mutate + `update_dict` |
| DELETE | `/notetypes/{id}/fields/{ord}` | Remove field (schema mod) | — | `{changes}` | `remove_field`+`update_dict` |
| POST | `/notetypes/{id}/fields/{ord}/actions/reposition` | Move field | `{new_index}` | `{changes}` | `reposition_field` |
| POST | `/notetypes/{id}/fields/actions/set-sort-field` | Set sort field | `{field_ord}` | `{changes}` | `set_sort_index` |
| GET | `/notetypes/{id}/templates` | List templates | — | `[{ord,name,qfmt,afmt,bqfmt,bafmt,did,bfont,bsize}]` | `col.models.get`→`tmpls` |
| POST | `/notetypes/{id}/templates` | Add template (schema mod) | `{name,qfmt?,afmt?}` | `{changes, notetype}` | `new_template`+`add_template` |
| PATCH | `/notetypes/{id}/templates/{ord}` | Edit template Q/A/styling/browser/deck-override | `{name?,qfmt?,afmt?,bqfmt?,bafmt?,did?,bfont?,bsize?}` | `{changes}` | mutate + `update_dict` |
| DELETE | `/notetypes/{id}/templates/{ord}` | Remove template (rejects last) | — | `{changes}` | `remove_template` |
| POST | `/notetypes/{id}/templates/{ord}/actions/reposition` | Reorder template | `{new_index}` | `{changes}` | `reposition_template` |
| GET | `/notetypes/{id}/templates/{ord}/use-count` | Cards from this template | — | `{count}` | `template_use_count` |
| PUT | `/notetypes/{id}/styling` | Update notetype CSS | `{css}` | `{changes}` | mutate css + `update_dict` |
| POST | `/notetypes/{id}/templates/{ord}/preview` | Live preview of uncommitted template | `{note:{fields[],tags?}, template:{qfmt,afmt}, fill_empty?}` | `{question_html,answer_html,css,question_av_tags,answer_av_tags,is_empty,latex_svg}` | `TemplateRenderContext.from_card_layout().render()` |
| GET | `/notetypes/change-info` | Field/template names + default remap | `?old_notetype_id&new_notetype_id` | `ChangeNotetypeInfo{old_field_names[],old_template_names[],new_field_names[],new_template_names[],input,old_notetype_name}` | `get_change_notetype_info` |
| POST | `/notes/actions/single-notetype` | Common notetype of a selection | `{note_ids[]}` | `{notetype_id}` | `get_single_notetype_of_notes` |
| GET | `/notetypes/tts-voices` | Available TTS voices | `?validate` | `[{id,name,available}]` | `all_tts_voices` |
| GET | `/notetypes/{id}/aux-config-key` | Aux config storage key (UI state) | `?key` | `{config_key}` | `get_aux_notetype_config_key` |
| GET | `/notetypes/{id}/templates/{ord}/aux-config-key` | Aux template config key | `?key` | `{config_key}` | `get_aux_template_config_key` |
| POST | `/notetypes/render/strip-html` | Strip HTML / to text line | `{text, mode}` | `{text}` | `strip_html` / `html_to_text_line` |

> Change-notetype mutation → `POST /notes/actions/change-notetype` (Search/Browse home). Empty-cards report → `GET /cards/empty` (Cards). `other` config blobs (notetype/field/template) round-trip untouched.

---

## Cards `[core]`

Card state, deletion, rendering, and **all card-driven bulk scheduling actions** (suspend/bury/flag/forget/set-due/reposition/grade-now) live here. These also appear in Review and Search/Browse inventories — this group is their single home; Review and Browse cross-reference.

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/cards/{id}` | Full card state | — | `{id,note_id,deck_id,template_idx,ctype,queue,due,interval,ease_factor,reps,lapses,remaining_steps,original_due,original_deck_id,flags,user_flag,original_position,custom_data,memory_state{stability,difficulty},desired_retention,decay,last_review_time_secs,mtime,usn}` | `col.get_card` |
| GET | `/cards` | Search/list card ids | `?search&order&reverse` | `{card_ids[]}` | `col.find_cards` |
| POST | `/cards/actions/batch-get` | Fetch many cards | `{card_ids[]}` | `{cards[]}` | `col.get_card` × n |
| PATCH | `/cards/{id}` | Update one card's mutable fields | partial card fields | `{changes}` | `col.update_card` |
| POST | `/cards/actions/update` | Bulk update cards | `{cards[], skip_undo_entry?}` | `{changes}` | `col.update_cards` |
| POST | `/cards/actions/delete` | Delete cards + orphaned notes | `{card_ids[]}` | `{count,changes}` | `col.remove_cards_and_orphaned_notes` |
| POST | `/cards/actions/set-deck` | Move cards to a deck | `{card_ids[], deck_id}` | `{count,changes}` | `col.set_deck` |
| POST | `/cards/actions/set-flag` | Set/clear flag (0–7; 0 clears) | `{card_ids[], flag}` | `{count,changes}` | `col.set_user_flag_for_cards` |
| POST | `/cards/actions/suspend` | Suspend cards (`by=card\|note`) | `{card_ids[]}` or `{note_ids[]}` | `{count,changes}` | `col.sched.suspend_cards` / `suspend_notes` |
| POST | `/cards/actions/unsuspend` | Unsuspend cards | `{card_ids[]}` | `{changes}` | `col.sched.unsuspend_cards` |
| POST | `/cards/actions/bury` | Bury cards (`by=card\|note`, `manual`) | `{card_ids[]\|note_ids[], manual}` | `{count,changes}` | `col.sched.bury_cards` / `bury_notes` |
| POST | `/cards/actions/unbury` | Unbury cards by id | `{card_ids[]}` | `{changes}` | `col.sched.unbury_cards` |
| POST | `/cards/actions/forget` | Reschedule as new (forget) | `{card_ids[], restore_position, reset_counts, context:BROWSER\|REVIEWER}` | `{changes}` | `col.sched.schedule_cards_as_new` |
| GET | `/cards/forget-defaults` | Forget dialog defaults | `?context` | `{restore_position, reset_counts}` | `schedule_cards_as_new_defaults` |
| POST | `/cards/actions/set-due-date` | Set due date | `{card_ids[], days:'5'\|'5-7'\|'5!', config_key?}` | `{changes}` | `col.sched.set_due_date` |
| POST | `/cards/actions/reposition` | Reposition new cards | `{card_ids[], starting_from, step_size, randomize, shift_existing}` | `{count,changes}` | `col.sched.reposition_new_cards` |
| GET | `/cards/reposition-defaults` | Reposition dialog defaults | — | `{random, shift}` | `col.sched.reposition_defaults` |
| POST | `/cards/actions/grade-now` | Grade cards immediately at a rating | `{card_ids[], rating:AGAIN\|HARD\|GOOD\|EASY}` | `{changes}` | `col._backend.grade_now` |
| POST | `/cards/actions/regenerate` | Regen cards after direct note edits | `{note_ids[], mark_modified, generate_cards}` | `{count,changes}` | `col.after_note_updates` |
| GET | `/cards/{id}/render` | Rendered Q/A + CSS + AV tags | `?browser&partial_render` | `{question_html,answer_html,css,question_av_tags,answer_av_tags}` | `Card.render_output` / `render_existing_card` |
| POST | `/cards/render-uncommitted` | Preview-render an unsaved card | `{note fields, card_ord, template, fill_empty, partial_render}` | `RenderCardResponse` | `render_uncommitted_card` |
| GET | `/cards/empty` | Empty-cards report | — | `EmptyCardsReport{report, notes:[{note_id,card_ids[],will_delete_note}]}` | `col.get_empty_cards` |
| GET | `/cards/{id}/scheduling-config` | Per-card reviewer behavior from deck preset | — | `{time_limit_ms, show_timer, autoplay, replay_question_on_answer}` | `Card.time_limit/should_show_timer/autoplay/replay_question_audio_on_answer_side` |

> `user_flag = flags & 0b111`. Flag colors: 1 red, 2 orange, 3 green, 4 blue, 5 pink, 6 turquoise, 7 purple. Per-card FSRS fields are writable via PATCH but normally set via FSRS recompute flows. `custom_data` is add-on-defined opaque JSON. Card stats/revlog → Stats group; memory-state → FSRS group.

---

## Review (Scheduler) `[core]`

The review loop, study counts, custom study, filtered-deck rebuild/empty. Bulk card scheduling actions are in Cards.

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/scheduler/queue/next` | Next due card(s) + states + counts + context (idempotent) | `?fetch_limit&intraday_learning_only` | `{cards:[{card, queue:NEW\|LEARNING\|REVIEW, states{current,again,hard,good,easy}, context{deck_name,seed}}], new_count, learning_count, review_count}` | `col.sched.get_queued_cards` |
| GET | `/scheduler/counts` | Remaining new/learning/review | — | `{new,learning,review}` | `col.sched.counts` |
| GET | `/cards/{id}/scheduling-states` | Four scheduling states for a card | — | `SchedulingStates{current,again,hard,good,easy}` | `get_scheduling_states` |
| POST | `/scheduler/describe-next-states` | Next-interval button labels | `{states}` or `{card_id}` | `[again,hard,good,easy]` labels | `col.sched.describe_next_states` |
| POST | `/scheduler/answer` | Answer current card | `{card_id, rating, milliseconds_taken?, current_state?, new_state?}` | `{changes}` | `col.sched.build_answer` + `answer_card` |
| POST | `/scheduler/scheduling-states` | Override states before answering (customizer) | `{key, states}` | `{key, states}` | `set_scheduling_states` / `get_scheduling_states_with_context` |
| POST | `/scheduler/state-is-leech` | Would new state mark a leech | `{new_state}` | `{is_leech}` | `col.sched.state_is_leech` |
| GET | `/scheduler/timing-today` | Days elapsed + next rollover | — | `{days_elapsed, next_day_at}` | `col.sched._timing_today` |
| GET | `/scheduler/congrats` | Finished-screen info | — | `{learn_remaining, secs_until_next_learn, review_remaining, new_remaining, have_sched_buried, have_user_buried, is_filtered_deck, deck_description}` | `col.sched.congratulations_info` |
| POST | `/decks/{id}/actions/extend-limits` | Extend today's limits | `{new_delta, review_delta}` | `{changes}` | `col.sched.extend_limits` |
| POST | `/decks/{id}/custom-study` | Start custom study | `CustomStudyRequest{new_limit_delta\|review_limit_delta\|forgot_days\|review_ahead_days\|preview_days\|cram{kind:DUE\|NEW\|REVIEW\|ALL,card_limit,tags_to_include[],tags_to_exclude[]}}` | `{changes}` | `col.sched.custom_study` |
| GET | `/decks/{id}/custom-study/defaults` | Custom Study dialog defaults | — | `{tags[{name,include,exclude}], extend_new, extend_review, available_new, available_review, available_new_in_children, available_review_in_children}` | `col.sched.custom_study_defaults` |
| POST | `/filtered-decks/{id}/actions/rebuild` | Rebuild filtered deck | — | `{count,changes}` | `col.sched.rebuild_filtered_deck` |
| POST | `/filtered-decks/{id}/actions/empty` | Empty filtered deck | — | `{changes}` | `col.sched.empty_filtered_deck` |
| POST | `/decks/{id}/actions/unbury` | Unbury a deck | `{mode:ALL\|SCHED_ONLY\|USER_ONLY}` | `{changes}` | `col.sched.unbury_deck` |
| POST | `/decks/{id}/actions/sort-new` | Randomize/order new-card order | `{randomize}` | `{count,changes}` | `col.sched.randomize_cards` / `order_cards` |

> Reviewer Undo/Redo → **Undo** group. `milliseconds_taken` is client-measured. Answer accepts both shapes: `{card_id, rating}` (server recomputes states) or echoed `current_state`/`new_state` (needed for the customizer key handshake). No queue-reset endpoint (backend auto-resets).

---

## FSRS `[parity]`

FSRS enable/disable and per-preset param save are folded into the Deck Options save (`POST /decks/{id}/options` with `fsrs`/`fsrs_reschedule`/`COMPUTE_ALL_PARAMS`). The endpoints below are the optimize/evaluate/simulate tools and per-card memory state. `compute_optimal_retention`, `simulate_fsrs_review`, `simulate_fsrs_workload` share one `SimulateFsrsReviewRequest` body schema.

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| POST | `/fsrs/actions/enable` | Convenience FSRS master toggle (round-trips an UpdateDeckConfigsRequest) | `{enabled, reschedule, target_deck_id}` | `{changes}` | `col.decks.update_deck_configs(fsrs=,fsrs_reschedule=)` |
| POST | `/fsrs/actions/compute-params` | Optimize params from history | `{search, current_params[], ignore_revlogs_before_ms, num_of_relearning_steps, health_check}` | `{params[], fsrs_items, health_check_passed}` | `compute_fsrs_params` |
| POST | `/fsrs/actions/compute-params-from-items` | Optimize from supplied items | `{items:[FsrsItem{reviews:[{rating,delta_t}]}]}` | `{params[], fsrs_items, health_check_passed}` | `compute_fsrs_params_from_items` |
| POST | `/fsrs/actions/evaluate-params` | Evaluate params (log loss + RMSE) | `{search, ignore_revlogs_before_ms, num_of_relearning_steps}` | `{log_loss, rmse_bins}` | `evaluate_params` |
| POST | `/fsrs/actions/evaluate-params-legacy` | Evaluate explicit param vector | `{params[], search, ignore_revlogs_before_ms}` | `{log_loss, rmse_bins}` | `evaluate_params_legacy` |
| POST | `/fsrs/actions/compute-optimal-retention` | Min recommended retention | `SimulateFsrsReviewRequest` | `{optimal_retention}` | `compute_optimal_retention` |
| GET | `/fsrs/optimal-retention-parameters` | Simulation seed params from history | `?search` | `GetOptimalRetentionParametersResponse{deck_size,learn_span,max_cost_perday,max_ivl,first_rating_prob[],review_rating_prob[],loss_aversion,learn_limit,review_limit,learning_step_transitions[],relearning_step_transitions[],state_rating_costs[],learning_step_count,relearning_step_count}` | `get_optimal_retention_parameters` |
| POST | `/fsrs/actions/simulate-review` | Per-day schedule projection | `SimulateFsrsReviewRequest{params[],desired_retention,deck_size,days_to_simulate,new_limit,review_limit,max_interval,search,review_order,…}` | `{accumulated_knowledge_acquisition[], daily_review_count[], daily_new_count[], daily_time_cost[]}` | `simulate_fsrs_review` |
| POST | `/fsrs/actions/simulate-workload` | Workload vs retention curve | `SimulateFsrsReviewRequest` | `{cost[], memorized[], review_count[]}` | `simulate_fsrs_workload` |
| POST | `/fsrs/actions/retention-workload` | Per-retention cost for candidate weights | `{w[], search}` | `{costs:{retention_pct:cost}}` | `get_retention_workload` |
| GET | `/fsrs/ignored-before-count` | Revlogs included vs ignored for a cutoff date | `?ignore_revlogs_before_date&search` | `{included, total}` | `get_ignored_before_count` |
| GET | `/cards/{id}/memory-state` | FSRS memory state for a card | — | `{desired_retention, stability, difficulty, decay}` | `col.compute_memory_state` |
| GET | `/cards/{id}/fuzz-delta` | Fuzz days on a card's interval | `?interval` | `{fuzz_delta}` | `col.fuzz_delta` |
| GET | `/fsrs/preferences` | Global FSRS behavior flags | — | `{short_term_with_steps_enabled, legacy_evaluate}` | config bools `FSRS_SHORT_TERM_WITH_STEPS_ENABLED`/`FSRS_LEGACY_EVALUATE` |
| PATCH | `/fsrs/preferences` | Set FSRS behavior flags | `{short_term_with_steps_enabled?, legacy_evaluate?}` | `{changes}` | `set_config_bool` |
| POST | `/fsrs/actions/benchmark` | Benchmark params (dev) `[deferred]` | `{train_set[FsrsItem]}` | `{params[]}` | `fsrs_benchmark` |

> Params are versioned: `fsrs_params_4` (17), `fsrs_params_5` (19), `fsrs_params_6` (21); read/write the latest non-empty per FSRS version. `ignore_revlogs_before` is a **date string** in config/`ignored-before-count` but **epoch-ms** in compute/evaluate — server converts. Progress/abort use the shared `/operations/*` endpoints.

---

## Search / Browse `[core]` (table) / `[parity]` (sidebar config, options)

Search and the Browse table. Card/note bulk actions that originate here are routed to their home groups (Cards, Notes, Tags) and cross-referenced. Note-driven bulk ops (find&replace, change-notetype, delete, duplicates, mark) are homed here.

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| POST | `/search/cards` | Search → card ids | `{query, order?, reverse?, use_stored_sort?}` | `{card_ids[]}` | `col.find_cards` |
| POST | `/search/notes` | Search → note ids | `{query, order?, reverse?, use_stored_sort?}` | `{note_ids[]}` | `col.find_notes` |
| POST | `/search/build` | Build/validate query from structured terms | `{nodes:[SearchNode], joiner:AND\|OR}` | `{query}` | `col.build_search_string` / `group_searches` |
| POST | `/search/join` | Append a term without over-bracketing | `{existing_node, additional_node, operator:AND\|OR}` | `{query}` | `col.join_searches` |
| POST | `/search/replace-node` | Replace nodes of a type | `{existing_node, replacement_node}` | `{query}` | `col.replace_in_search_node` |
| GET | `/browser/columns` | All available columns + metadata | — | `{columns:[{key,cards_mode_label,notes_mode_label,sorting_cards,sorting_notes,uses_cell_font,alignment,cards_mode_tooltip,notes_mode_tooltip}]}` | `col.all_browser_columns` |
| GET | `/browser/columns/active` | Active columns for a mode | `?mode=cards\|notes` | `{columns[]}` | `load_browser_card_columns`/`load_browser_note_columns` |
| PUT | `/browser/columns/active` | Set/reorder active columns | `{mode, columns[]}` | `{ok}` | `set_browser_card_columns`/`set_browser_note_columns` |
| POST | `/browser/rows` | Render rows for a window of ids (pagination primitive) | `{ids[], mode}` | `{rows:[{id, cells:[{text,is_rtl,elide_mode}], color, font_name, font_size}]}` | `col.browser_row_for_id` × n |
| GET | `/browser/sort` | Stored sort for a mode | `?mode` | `{column, reverse}` | `get_config(sortType/noteSortType,...)` |
| PUT | `/browser/sort` | Set stored sort | `{mode, column, reverse}` | `{ok}` | `set_config(BrowserConfig.*)` |
| GET | `/browser/mode` | Cards/notes table mode | — | `{notes_mode}` | `get_config_bool(BROWSER_TABLE_SHOW_NOTES_MODE)` |
| PUT | `/browser/mode` | Set table mode | `{notes_mode}` | `{ok}` | `set_config_bool(...)` |
| POST | `/notes/actions/find-and-replace` | Find&replace across note fields | `{note_ids[], search, replacement, regex?, match_case?, field_name?}` | `{count,changes}` | `col.find_and_replace` |
| POST | `/notes/duplicates` | Find duplicate notes by field | `{field_name, search?}` | `{dupes:[{value, note_ids[]}]}` | `col.find_dupes` |
| POST | `/notes/actions/toggle-mark` | Add/remove `marked` tag | `{note_ids[], marked}` | `{count,changes}` | `col.tags.bulk_add`/`bulk_remove(...,'marked')` |
| POST | `/notes/actions/change-notetype` | Change notetype with remap | `{note_ids[], old_notetype_id, new_notetype_id, new_fields[], new_templates[], is_cloze}` (current_schema fetched server-side) | `{changes}` | `col.models.change_notetype_of_notes` |
| GET | `/saved-searches` | List saved searches | — | `{searches:{name:query}}` | `get_config('savedFilters')` |
| PUT | `/saved-searches/{name}` | Create/update saved search | `{query}` | `{ok}` | `set_config('savedFilters',…)` |
| DELETE | `/saved-searches/{name}` | Delete saved search | — | `{ok}` | `set_config('savedFilters',…)` |
| GET | `/browser/search-options` | Default search text, ignore-accents, restore/reset flags | — | `{default_search_text, ignore_accents, restore_position_browser, reset_counts_browser, set_due_browser}` | `get_config_string`/`get_config_bool` |
| PUT | `/browser/search-options` | Set search options | partial of above | `{ok}` | `set_config_string`/`set_config_bool` |
| GET | `/browser/sidebar/collapsed` | Sidebar section collapse flags | — | `{tags,notetypes,decks,saved_searches,today,card_state,flags}` | `get_config_bool(COLLAPSE_*)` |
| PUT | `/browser/sidebar/collapsed` | Set section / tag collapse | `{section?, collapsed}` or `{tag, collapsed}` | `{ok}` | `set_config_bool(COLLAPSE_*)` / `col.tags.set_collapsed` |

> Bulk card actions invoked from Browse (set-deck, suspend, unsuspend, bury, unbury, set-flag, set-due-date, forget, reposition, grade-now) → **Cards**. Tag add/remove/find-replace → **Tags**. Bulk delete notes → `POST /notes/actions/delete` (**Notes**). Field-names union → `POST /notes/field-names` (**Notes**). Selection conversion (cards↔notes) is via re-searching.

`SearchNode` oneof covers: `deck, tag, note, template, nid, nids, field(name+text+mode:normal\|regex\|nocombining), field_name, dupe, rated, added_in_days, edited_in_days, introduced_in_days, due_in_days, due_on_day, flag(none\|any\|red…purple), card_state(new\|learn\|review\|due\|suspended\|buried), literal_text, parsable_text, negated, group{nodes,joiner}`.

---

## Tags `[parity]`

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/tags/tree` | Hierarchical tag tree | — | `TagTreeNode{name,level,collapsed,children[]}` | `col.tags.tree` |
| GET | `/tags` | Flat list of tag names | — | `{tags[]}` | `col.tags.all` |
| GET | `/tags/complete` | Autocomplete partial input | `?input&match_limit` | `{tags[]}` | `col._backend.complete_tag` |
| POST | `/notes/actions/add-tags` | Bulk add tags | `{note_ids[], tags}` (space-separated) | `{count,changes}` | `col.tags.bulk_add` |
| POST | `/notes/actions/remove-tags` | Bulk remove tags | `{note_ids[], tags}` | `{count,changes}` | `col.tags.bulk_remove` |
| POST | `/notes/actions/find-replace-tags` | Find&replace within tags | `{note_ids[], search, replacement, regex, match_case}` | `{count,changes}` | `col.tags.find_and_replace` |
| POST | `/tags/actions/rename` | Rename tag + children (prefix/merge) | `{old, new}` | `{count,changes}` | `col.tags.rename` |
| POST | `/tags/actions/reparent` | Reparent tags (empty parent→top) | `{tags[], new_parent}` | `{count,changes}` | `col.tags.reparent` |
| POST | `/tags/actions/remove` | Delete tags + children collection-wide | `{tags}` (space-separated) | `{count,changes}` | `col.tags.remove` |
| POST | `/tags/actions/clear-unused` | Remove tags on no notes | — | `{count,changes}` | `col.tags.clear_unused_tags` |
| POST | `/tags/actions/set-collapsed` | Set tag branch collapse (registers if missing) | `{name, collapsed}` | `{changes}` | `col.tags.set_collapsed` |

> Tag names contain `::`/spaces; names are passed in the **body**, not the path (avoids URL-encoding footguns). "Marked" is the reserved `marked` tag (`/notes/actions/toggle-mark`, Browse). No "create empty tag" backend call — tags exist by being added to a note or via `set-collapsed`.

---

## Media `[parity]`

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| POST | `/media/files` | Upload/store a file (auto-renames on collision) | multipart bytes or `{desired_name, data(base64), content_type?}` | `{filename}` (final stored name) | `col.media.write_data`; `add_extension_based_on_mime` |
| GET | `/media/files/{filename}` | Serve raw bytes | — | binary stream; 404 if absent | filesystem read at `col.media.dir()` + `have` |
| HEAD | `/media/files/{filename}` | Existence check | — | 200/404 | `col.media.have` |
| GET | `/media/dir` | Media folder path | — | `{path}` | `col.media.dir` |
| POST | `/media/files/actions/trash` | Bulk-trash files | `{fnames[]}` | `204` | `col.media.trash_files` |
| POST | `/media/trash/actions/empty` | Permanently empty trash | — | `204` | `col.media.empty_trash` |
| POST | `/media/trash/actions/restore` | Restore trashed files | — | `204` | `col.media.restore_trash` |
| POST | `/media/actions/check` | Media check report (long-running) | — | `{unused[], missing[], missing_media_notes[], report, have_trash}` | `col.media.check` |
| POST | `/media/actions/render-latex` | Render all missing LaTeX (long-running) | — | `{ok}` or `{note_id, error}` | `col.media.render_all_latex` |
| POST | `/media/references/in-text` | Media referenced by a field string | `{notetype_id, text, include_remote?}` | `{files[]}` | `col.media.files_in_str` |
| GET | `/media/references/notetype/{id}/static` | Static media of a notetype | — | `{files[]}` | `extract_static_media_files` |
| POST | `/media/text/strip-av` | Strip sound/img/object tags | `{text}` | `{text}` | `strip_av_tags` |
| POST | `/media/text/extract-av` | Extract AV tags (reviewer audio queue) | `{text, question_side}` | `{text, av_tags[]}` | `extract_av_tags` |
| POST | `/media/text/extract-latex` | Extract LaTeX fragments | `{text, svg, expand_clozes}` | `{text, latex[]}` | `extract_latex` |
| POST | `/media/text/encode-iri` | Percent-encode filenames in tags | `{text}` | `{text}` | `encode_iri_paths` |
| POST | `/media/text/decode-iri` | Decode filenames in tags | `{text}` | `{text}` | `decode_iri_paths` |
| POST | `/media/actions/force-resync` | Clear local media DB (sync troubleshooting) | — | `204` | `col.media.force_resync` |

> No backend getter for raw bytes nor a full filename listing — `GET /media/files/{filename}` reads the filesystem at `col.media.dir()`; a listing must enumerate the folder. Filename collisions auto-rename: clients must use the returned `filename`. Media sync itself is deferred (Sync, out of scope for v1).

---

## Stats `[parity]`

The Stats screen is backed by one `GET /graphs` call (slices below are conveniences over the same `GraphsResponse`). Per-card stats/revlog also surface in Cards.

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/graphs` | Full graphs payload for a scope+window | `?search&days` (`''`=whole collection, days `0`=all) | `GraphsResponse{future_due,reviews,intervals,hours,today,eases,difficulty,card_counts,added,retrievability,stability,true_retention,buttons,fsrs,rollover_hour}` | `col._backend.graphs` |
| GET | `/graphs/future-due` | Forecast slice | `?search&days` | `FutureDue{future_due[],have_backlog,daily_load}` | `.future_due` |
| GET | `/graphs/reviews` | Review counts+times by day | `?search&days` | `ReviewCountsAndTimes{count[],time[]}` | `.reviews` |
| GET | `/graphs/intervals` | Interval distribution | `?search&days` | `Intervals{intervals[]}` | `.intervals` |
| GET | `/graphs/hours` | Hourly breakdown (1mo/3mo/1y/all) | `?search&days` | `Hours{...}` + `rollover_hour` | `.hours` |
| GET | `/graphs/added` | Cards added per day | `?search&days` | `Added{added[]}` | `.added` |
| GET | `/graphs/card-counts` | Counts by state (incl/excl inactive) | `?search&days` | `CardCounts{including_inactive,excluding_inactive}` | `.card_counts` |
| GET | `/graphs/true-retention` | True retention by period | `?search&days` | `TrueRetentionStats{today…all_time}` | `.true_retention` |
| GET | `/graphs/today` | Today summary | `?search&days` | `Today{answer_count,answer_millis,correct_count,mature_*,learn_count,review_count,relearn_count,early_review_count}` | `.today` |
| GET | `/graphs/answer-buttons` | Button press distribution | `?search&days` | `Buttons{...}` | `.buttons` |
| GET | `/graphs/eases` | SM-2 ease distribution | `?search&days` | `Eases{eases[],average}` | `.eases` |
| GET | `/graphs/difficulty` | FSRS difficulty distribution | `?search&days` | `Eases{eases[],average}` | `.difficulty` |
| GET | `/graphs/retrievability` | FSRS retrievability | `?search&days` | `Retrievability{retrievability[],average,sum_by_card,sum_by_note}` | `.retrievability` |
| GET | `/graphs/stability` | FSRS stability | `?search&days` | `Intervals{intervals[]}` | `.stability` |
| GET | `/graphs/preferences` | Graph display prefs | — | `GraphPreferences{calendar_first_day_of_week,card_counts_separate_inactive,browser_links_supported,future_due_show_backlog}` | `get_graph_preferences` |
| PUT | `/graphs/preferences` | Set graph display prefs | GraphPreferences | `204` | `set_graph_preferences` |
| GET | `/cards/{id}/stats` | Card Info panel data | — | `CardStatsResponse{…,memory_state,fsrs_retrievability,desired_retention,fsrs_params[],preset,original_deck,revlog[]}` | `col.card_stats_data` |
| GET | `/cards/{id}/revlog` | Card review history | — | `[StatsRevlogEntry{time,review_kind,button_chosen,interval,ease,taken_secs,memory_state}]` | `col.get_review_logs` |
| GET | `/stats/studied-today` | "Studied today" string | — | `{text}` | `col.studied_today` |
| GET | `/stats/congrats` | Congrats-screen info | — | `CongratsInfoResponse{…}` | `col.sched.congratulations_info` |
| GET | `/stats/report` | Legacy HTML report `[deferred]` | `?period=month\|year\|life&scope` | `{html}` | `col.stats().report` |

> Graph scope is a **search string**, not a deck id. `hours`/`buttons` always return all four windows regardless of `days`. `graphs`/`get_graph_preferences` are `_backend`-only (no ergonomic wrapper) — server calls them directly.

---

## Import / Export `[parity]`

All calls are path-based; use `/files/uploads` and `/files/downloads/{token}` to bridge. Collection-package import/export and full restore are destructive and coordinate with collection close/reopen.

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/export/formats` | List export formats | — | `[{label,ext,key}]` | `anki.exporting.exporters` |
| POST | `/export/anki-package` | Export `.apkg` | `{out_path, options{with_scheduling,with_deck_configs,with_media,legacy}, limit{whole_collection\|deck_id\|note_ids[]\|card_ids[]}}` | `{exported_count, out_path}` | `col.export_anki_package` |
| POST | `/export/collection-package` | Export `.colpkg` (closes DB for full export) | `{out_path, include_media, legacy}` | `{out_path}` | `col.export_collection_package` |
| POST | `/export/notes-csv` | Export notes CSV/TSV | `{out_path, limit, with_html, with_tags, with_deck, with_notetype, with_guid}` | `{exported_count, out_path}` | `col.export_note_csv` |
| POST | `/export/cards-csv` | Export rendered cards CSV/TSV | `{out_path, limit, with_html}` | `{exported_count, out_path}` | `col.export_card_csv` |
| POST | `/export/research-dataset` | Export revlog dataset `[deferred]` | `{target_path, min_entries}` | `{target_path}` | `col.export_dataset_for_research` |
| POST | `/import/anki-package/inspect` | Default `.apkg` import options | `{package_path}` | `ImportAnkiPackageOptions{merge_notetypes,update_notes,update_notetypes,with_scheduling,with_deck_configs}` | `get_import_anki_package_presets` |
| POST | `/import/anki-package` | Import `.apkg` | `{package_path, options{merge_notetypes,update_notes:ALWAYS\|IF_NEWER\|NEVER,update_notetypes:…,with_scheduling,with_deck_configs}}` | `ImportLogWithChanges{log{new,updated,duplicate,conflicting,first_field_match,missing_notetype,missing_deck,empty_first_field,dupe_resolution,found_notes}, changes}` | `col.import_anki_package` |
| POST | `/import/collection-package` | Restore/replace from `.colpkg` (destructive) | `{col_path, backup_path, media_folder, media_db}` | `{ok}` | `import_collection_package` |
| POST | `/import/csv/metadata` | Inspect CSV/TSV (delimiter, columns, preview, mapping) | `{path, delimiter?}` | `CsvMetadata{delimiter,is_html,column_labels,preview[],global_notetype{id,field_columns},notetype_column,deck_column,tags_column,guid_column,deck_id,deck_name,dupe_resolution,match_scope,force_*}` | `col.get_csv_metadata` |
| POST | `/import/csv` | Import CSV/TSV with finalized metadata | `{path, metadata:CsvMetadata}` | `ImportLogWithChanges` | `col.import_csv` |
| POST | `/import/json/file` | Import JSON file | `{path}` | `ImportLogWithChanges` | `col.import_json_file` |
| POST | `/import/json/string` | Import JSON string | `{json}` | `ImportLogWithChanges` | `col.import_json_string` |
| POST | `/import/done` | Finalize/commit import session | — | `{ok}` | `import_done` |
| POST | `/files/uploads` | Upload an import file → server path | multipart | `{path}` | (transport) |
| GET | `/files/downloads/{token}` | Download an export artifact | — | file stream | (transport) |

> Duplicate handling: `DupeResolution{UPDATE,PRESERVE,DUPLICATE}`, `MatchScope{NOTETYPE,NOTETYPE_AND_DECK}`, `Delimiter{TAB,PIPE,SEMICOLON,COLON,COMMA,SPACE}`. CSV client posts back the (possibly edited) `CsvMetadata` from inspect. The opaque `occlusions` serialization is shared with Image Occlusion (Notes group).

---

## Config & Preferences `[parity]`

Aggregated Preferences screen plus generic and typed config access. Aux per-notetype/template config keys are listed here.

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/preferences` | Full aggregated Preferences | — | `{scheduling{rollover,learn_ahead_secs,new_review_mix,new_timezone,day_learn_first}, reviewing{hide_audio_play_buttons,interrupt_audio_when_answering,show_remaining_due_counts,show_intervals_on_buttons,time_limit_secs,load_balancer_enabled,fsrs_short_term_with_steps_enabled}, editing{adding_defaults_to_current_deck,paste_images_as_png,paste_strips_formatting,default_search_text,ignore_accents_in_search,render_latex}, backups{daily,weekly,monthly,minimum_interval_mins}}` | `col.get_preferences` |
| PUT | `/preferences` | Save full Preferences (transactional) | full Preferences | `{changes}` | `col.set_preferences` |
| PATCH | `/preferences/scheduling` | Update scheduling sub-section (read-modify-write) | partial scheduling | `{changes}` | get + mutate + `set_preferences` |
| PATCH | `/preferences/reviewing` | Update reviewing sub-section | partial reviewing | `{changes}` | get + mutate + `set_preferences` |
| PATCH | `/preferences/editing` | Update editing sub-section | partial editing | `{changes}` | get + mutate + `set_preferences` |
| PATCH | `/preferences/backups` | Update backup limits | partial backups | `{changes}` | get + mutate + `set_preferences` |
| GET | `/preferences/scheduler-version` | Active scheduler version | — | `{sched_ver}` | `col.sched_ver` |
| GET | `/config` | Dump entire config map (debug/bootstrap) | — | `{<key>:<json>}` | `col.all_config` |
| GET | `/config/{key}` | Get arbitrary config key | `?default` | `{key, value}` (404 if absent, no default) | `col.get_config` |
| PUT | `/config/{key}` | Set arbitrary config key | `{value, undoable?=false}` | `{changes}` | `col.set_config` / (`undoable=false`→`set_config_json_no_undo`) |
| DELETE | `/config/{key}` | Remove config key | — | `{changes}` (404 if absent) | `col.remove_config` |
| GET | `/config/bool/{enumKey}` | Typed bool by Bool enum name | — | `{key, value}` | `col.get_config_bool` |
| PUT | `/config/bool/{enumKey}` | Set typed bool | `{value, undoable?}` | `{changes}` | `col.set_config_bool` |
| GET | `/config/string/{enumKey}` | Typed string by String enum name | — | `{key, value}` | `col.get_config_string` |
| PUT | `/config/string/{enumKey}` | Set typed string | `{value, undoable?}` | `{changes}` | `col.set_config_string` |
| PUT | `/config/load-balancer` | Toggle FSRS load balancer (special setter) | `{enabled}` | `200` | `col.load_balancer_enabled` setter |
| GET | `/notetypes/{id}/aux-config/{key}` | Per-notetype aux config | `?default` | `{key, value}` | `col.get_aux_notetype_config` |
| PUT | `/notetypes/{id}/aux-config/{key}` | Set per-notetype aux config | `{value, undoable?}` | `{changes}` | `col.set_aux_notetype_config` |
| GET | `/notetypes/{id}/templates/{ord}/aux-config/{key}` | Per-template aux config | `?default` | `{key, value}` | `col.get_aux_template_config` |
| PUT | `/notetypes/{id}/templates/{ord}/aux-config/{key}` | Set per-template aux config | `{value, undoable?}` | `{changes}` | `col.set_aux_template_config` |

> Enum keys are referenced by **name** (e.g. `COLLAPSE_TAGS`, `DEFAULT_SEARCH_TEXT`); server maps name↔int and rejects unknown names (some Bool numbers are non-contiguous). PATCH sub-sections are read-modify-write (lost-update risk under concurrency — consider ETag/version guard). Don't use `/config/{key}` as a blob store (synced; keep payloads small). FSRS toggles overlap with the FSRS group; preferences own the global behavior flags.

---

## Undo `[core]`

Reviewer Undo and the cross-cutting OpChanges model. Scoped to the single open collection; mutating ops are serialized per collection.

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| GET | `/undo/status` | Undo/redo availability + labels + merge target | — | `{can_undo, undo_name, can_redo, redo_name, last_step}` | `col.undo_status` |
| POST | `/undo/actions/undo` | Undo last operation | — | `{operation, reverted_to_timestamp, counter, changes, new_status}` (409 `UndoEmpty`) | `col.undo` |
| POST | `/undo/actions/redo` | Redo last undone operation | — | same shape as undo (409 `UndoEmpty`) | `col.redo` |
| POST | `/undo/entries` | Create named custom undo entry | `{name}` | `{target}` | `col.add_custom_undo_entry` |
| POST | `/undo/entries/{target}/merge` | Merge subsequent ops into entry | — | `{changes}` | `col.merge_undo_entries` |
| GET | `/undo/name` | Legacy undo label only `[deferred]` | — | `{undo_name\|null}` | `col.undo_name` |

> `undo`/`redo` names and `operation` are **already-localized strings** from the backend (no stable enum, no full stack listing). The Python wrapper clears the notetype cache when `changes.notetype` is set — the server must use `col.undo()`/`redo()`, not raw backend, to preserve this.

---

## Collection / System `[parity]` (most) / `[core]` (open/info/progress)

Lifecycle, integrity, backups, progress, schema/scheduler version, and shared operation control. Undo/redo are homed in the Undo group (mirrored here as collection actions for parity but cross-referenced).

| Method | Path | Purpose | Key request | Key response | Backing anki call |
|---|---|---|---|---|---|
| POST | `/collections` | Create new empty collection (file created on open) | `{path, preferences?}` | `{id, path, schema_version, crt, sched_ver}` | `Collection(path)` → `open_collection` |
| POST | `/collections/{id}/actions/open` | Open existing collection | `{after_full_sync?}` | `{open, name, counts, schema_changed}` | `Collection.reopen` |
| POST | `/collections/{id}/actions/close` | Close (optional downgrade to schema 11) | `{downgrade?=false}` | `{closed}` | `Collection.close` |
| POST | `/collections/{id}/actions/close-for-full-sync` | Detach DB ahead of full sync `[deferred]` | — | `{ok}` | `Collection.close_for_full_sync` |
| GET | `/collections/{id}` | Collection info/health | — | `{name,path,card_count,note_count,is_empty,crt,mod,usn,schema_version,schema_changed,sched_ver,v3_scheduler}` | various `Collection.*` |
| GET | `/collections/{id}/health` | Lightweight liveness | — | `{db_open, counts, studied_today}` | `is_empty`/`card_count`/`note_count`/`studied_today` |
| POST | `/collections/{id}/actions/check-database` | Check DB (fsck) + rebuild caches | — | `{ok, problems[]}` | `Collection.fix_integrity` |
| POST | `/collections/{id}/actions/optimize` | Vacuum + analyze | — | `{ok}` | `Collection.optimize` |
| POST | `/collections/{id}/backups` | Create backup (respects interval unless force) | `{backup_folder, force, wait_for_completion}` | `{created}` | `Collection.create_backup` |
| POST | `/collections/{id}/backups/actions/await-completion` | Await pending backup | — | `{ok}` (throws on failure) | `Collection.await_backup_completion` |
| GET | `/operations/progress` | Poll background-op progress (shared) | — | `Progress` oneof `{database_check{stage,stage_total,stage_current}\|importing\|exporting\|compute_*\|media_*\|none}` | `col.latest_progress` |
| POST | `/operations/abort` | Abort current long-running op (shared) | — | `{ok}` | `col.set_wants_abort` |
| GET | `/collections/{id}/schema` | Schema/version + full-sync requirement | — | `{schema_version, schema_changed, usn, crt, mod}` | `schema_changed`/`db.scalar('select ver')`/`usn` |
| POST | `/collections/{id}/schema/actions/mark-modified` | Mark schema modified (forces full sync) | `{check}` | `{ok}` (409 `AbortSchemaModification`) | `Collection.mod_schema` |
| GET | `/collections/{id}/scheduler` | Scheduler version / v3 status | — | `{sched_ver, v3_scheduler}` | `sched_ver`/`v3_scheduler` |
| POST | `/collections/{id}/scheduler/actions/upgrade` | Upgrade to v2 `[deferred]` | — | `{ok}` | `upgrade_to_v2_scheduler` |
| PUT | `/collections/{id}/scheduler/v3` | Enable/disable v3 `[deferred]` | `{enabled}` | `{ok}` | `set_v3_scheduler` |
| GET | `/collections/{id}/studied-today` | Studied-today string | — | `{summary}` | `Collection.studied_today` |
| POST | `/collections/{id}/db/query` | Read-only SQL query `[deferred]` | `{sql, args[], first_row_only}` | `{rows}` | `DBProxy.*` → `db_query` |
| POST | `/collections/{id}/db/transaction` | Atomic write batch `[deferred]` | `{operations[]}` | `{ok}` or rolled-back error | `DBProxy.transact` |
| GET | `/app/update-check` | Newer-version / server messages `[deferred]` | `{version,buildhash,os,install_id,last_message_id}` | `{have_update,current_version,message}` | `check_for_update` |

> Empty-cards **report** → `GET /cards/empty`; **deletion** splits into `POST /notes/actions/delete` (`will_delete_note`) + `POST /cards/actions/delete` (partial). Collection-package export/import → **Import/Export**. Undo/redo → **Undo** group. Save is automatic (legacy `save()/autosave()` are no-ops). There is no backend `create-collection` call — a new file is created implicitly on open; the server owns path↔handle mapping (the backend has no concept of multiple named collections). `usn` is `-1` unless opened in server mode.

---

## Parity audit — gaps to fold in

The synthesis above is comprehensive; this audit (from a dedicated feature-parity critic walking every Anki UI screen) catches reviewer/UI-chrome capabilities that were missing or under-specified. **Two are blockers for a faithful reviewer.**

> **Overall assessment:** The surface is unusually thorough and well-grounded in the real anki backend - deck/note/card CRUD, the search+browser-row pagination primitive, FSRS tooling, deck-options transactional save, image occlusion, import/export, and the OpChanges envelope are all faithfully mapped to actual calls, and the deferral list (sync, scheduler upgrade, raw DB) is reasonable. The gaps are concentrated in the Reviewer's media/answer-interaction layer. Two are genuine blockers for desktop/AnkiDroid parity: type-in-the-answer (compare_answer + extract_cloze_for_typing) is completely absent despite being a core reviewer mode, and TTS audio cannot be played because write_tts_stream is not exposed (voices are listed but never synthesized, and browsers can't reproduce Anki TTS natively). Important secondary gaps: the Add screen's deck-follows-notetype lookup (default_deck_for_notetype), generic i18n (translate_string) and time formatting (format_timespan) which the UI needs for its own chrome and interval displays. Markdown rendering, HTML card-info, custom-colour palette, and restore-buried-and-suspended are nice-to-have parity conveniences. Net: close the two reviewer blockers (type-answer, TTS) and the three important add/i18n/format gaps and this would support a faithful full client; everything else is polish."

### Missing endpoints

#### 🚩 Blockers (reviewer parity)

- **Type-in-the-answer review (type:Field). The reviewer can't compare the typed answer to the expected value or render the colored diff, and can't extract the expected cloze text for typing cards. This is a first-class desktop/AnkiDroid reviewer feature triggered by {{type:Field}} / {{type:cloze:Field}} in templates.**
  - Anki: Reviewer answer side, when the current template contains a type field. Backend calls col.compare_answer(expected, provided, combining) and col._backend.extract_cloze_for_typing(text, ordinal).
  - Suggested: `POST /scheduler/compare-answer {expected, provided, combining} -> {comparison_html}; POST /notes/extract-cloze-for-typing {text, ordinal} -> {text}`
- **TTS audio synthesis. The surface lists available voices (/notetypes/tts-voices via all_tts_voices) and extracts TTS av_tags, but never exposes the call that actually renders a TTSTag to a playable audio file. Browsers have no way to reproduce Anki's TTS voices/speed, so a UI cannot play {{tts:}} fields without this.**
  - Anki: Reviewer audio playback for {{tts ...}} fields. Backend call col._backend.write_tts_stream(path, voice_id, speed, text).
  - Suggested: `POST /media/tts/synthesize {voice_id, speed, text} -> audio stream or {token} for /files/downloads/{token}`

#### ⚠️ Important

- **Add-screen 'change deck depending on notetype'. When the user switches the notetype in the Add dialog, Anki repoints the deck to the last deck used with that notetype (unless ADDING_DEFAULTS_TO_CURRENT_DECK). /notes/add-defaults only covers the initial defaults, not the per-notetype-switch lookup.**
  - Anki: Add Note dialog, on notetype change. Backend call col.default_deck_for_notetype(notetype_id).
  - Suggested: `GET /notetypes/{id}/default-deck -> {deck_id|null}`
- **Generic i18n string translation. All undo/redo/button labels the surface returns are already-localized backend strings, but a full UI also needs to translate its own chrome (menus, dialog titles, tooltips) using Anki's Fluent catalog for locale consistency. No endpoint exposes translate_string / the i18n module.**
  - Anki: Everywhere in the UI chrome. Backend call col._backend.translate_string(module_index, message_index, args) (and the tr.* wrappers).
  - Suggested: `POST /i18n/translate {module, message, args} -> {text}  (plus a GET /i18n/catalog bootstrap)`
- **Time/interval formatting. Anki renders durations ('2.3 mo', '15 s', '3.1 d') with locale-aware, context-specific formatting used on answer buttons, card info, stats and intervals. describe_next_states gives button labels, but any client-side interval display (set-due preview, card info, deck options) needs the formatter.**
  - Anki: Answer buttons, Card Info, Stats, interval fields. Backend call col._backend.format_timespan(seconds, context).
  - Suggested: `POST /i18n/format-timespan {seconds, context} -> {text}`

#### Nice-to-have

- **Markdown rendering for deck/preset descriptions. Decks support markdown_description and the congrats/deck-browser surfaces render it to HTML server-side. No endpoint exposes render_markdown, so a UI must ship its own (potentially divergent, unsanitized) markdown renderer.**
  - Anki: Deck description display in deck list / congrats screen, and Deck Options description preview. Backend call col._backend.render_markdown(markdown, sanitize).
  - Suggested: `POST /render/markdown {markdown, sanitize} -> {html}`
- **Card Info as pre-rendered HTML. The surface exposes card_stats_data (structured) and revlog, but not col.card_stats(card_id, include_revlog) which returns the fully rendered Card Info HTML that desktop/AnkiDroid show verbatim. Optional if the client rebuilds the panel from structured data, but it's a parity convenience.**
  - Anki: Browse > Card Info panel, reviewer 'Card Info'. Backend call col.card_stats(card_id, include_revlog).
  - Suggested: `GET /cards/{id}/stats?format=html -> {html}`
- **Editor custom-colour palette persistence. The note editor's colour picker stores a custom-colour palette via the backend so it persists across sessions/devices. No endpoint exposes save_custom_colours.**
  - Anki: Note editor text-colour/highlight picker. Backend call col._backend.save_custom_colours().
  - Suggested: `POST /editor/custom-colours (body carries palette; round-trips colour config)`
- **Restore buried-and-suspended cards (single op). The surface has unbury (sched.unbury_cards) and unsuspend separately, but not restore_buried_and_suspended_cards, which the browser uses to clear both states for a card selection in one undoable op.**
  - Anki: Browse right-click on a selection mixing buried+suspended cards. Backend call col._backend.restore_buried_and_suspended_cards(cids).
  - Suggested: `POST /cards/actions/restore-buried-and-suspended {card_ids[]}`
- **Add-on info lookup (get_addon_info) and help-page deep links (help_page_link). Minor: a full client may want the contextual 'Help' buttons that desktop shows on each dialog, which resolve to versioned anki manual URLs via help_page_link. Add-on info is irrelevant to a headless server.**
  - Anki: Help buttons on dialogs. Backend call col._backend.help_page_link(page).
  - Suggested: `GET /help/link?page=<HelpPage> -> {url}`

### Convention refinements

- PATCH sub-section preferences endpoints (/preferences/scheduling etc.) are flagged in the doc itself as read-modify-write with lost-update risk; for full parity with no data-loss they should carry an optimistic-concurrency guard (mtime/ETag), otherwise concurrent edits silently clobber.
- The reviewer scheduling-states 'key' handshake (set_scheduling_states / get_scheduling_states_with_context) is split across /scheduler/scheduling-states and /scheduler/answer echoing current_state/new_state. This is correct but under-specified: the doc should state that the same key must be threaded through describe-next-states -> answer for the card_state_customizer to apply, or custom JS scheduling will silently no-op.
- Card-driven vs note-driven bulk discriminator (by=card|note) is only applied to suspend/bury; forget, set-due-date, grade-now and set-flag are card-only, but the browser's notes-mode operates on note selections. The doc should specify how a notes-mode selection is converted (it says 're-searching'), which adds a round-trip the desktop avoids.
- AV tag playback ordering/replay: the surface exposes extract-av and per-card scheduling-config (autoplay, replay_question_on_answer) but does not define how the client learns the configured question/answer audio actions (question_action/answer_action enums, wait_for_audio, skip_question_when_replaying_answer) at review time except buried inside deck preset config. A reviewer needs these resolved per-card alongside the av_tags, not by re-reading the preset.

