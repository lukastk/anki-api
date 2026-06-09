# 00 — Open a Collection headless

**Status:** done (2026-06-09). Verdict: ✅ fully works, no GUI needed.

## What we learned

- `pip install anki` (via `uv add anki`) installs **`anki==25.9.4`** with **zero Qt/GUI deps**. Total footprint: 13 small packages (`protobuf`, `orjson`, `requests`, `markdown`, etc.). `aqt` is a separate package and is *not* pulled in. This confirms the headless premise at the dependency level.
- **Python pin matters:** the anki wheel does **not** support CPython 3.13 yet. `uv` auto-resolved to **CPython 3.12.12**. Production project should pin `requires-python = ">=3.9,<3.13"` (3.12 is the safe ceiling today).
- The whole CRUD loop works headless: open/create `Collection(path)`, `col.decks.id(name)`, `col.new_note(notetype)` + `col.add_note(note, did)`, `col.find_notes/find_cards(query)`, `col.get_card/get_note`, `card.question()` renders full HTML+CSS, `col.close()`, reopen → data persists.

## Key API surface (for the eventual server)

- `from anki.collection import Collection`; `col = Collection("/path/to/collection.anki2")` creates-or-opens.
- Notetypes: `col.models.by_name("Basic")` (built-ins "Basic", "Basic (and reversed card)", "Cloze", etc. exist in a fresh collection).
- Fields set dict-style: `note["Front"] = ...`; tags via `note.tags = [...]`.
- Search uses Anki's normal query DSL (`deck:`, `tag:`, etc.) — we get that for free.
- `card.question()` / `card.answer()` render the templated HTML — a custom UI could use these directly.
- Lifecycle: must `col.close()` to release the file; data is durable across reopen.

## Surprises / notes

- `col.sched_ver()` reports **2** on a fresh collection, not 3. The v3 scheduler is a separate toggle (config), not the legacy `sched_ver` field — to verify/enable in experiment 01.
- `col.add_note(note, did)` takes the deck id as a 2nd arg (note carries no deck itself).

## Artifacts

- [`spike.py`](spike.py) — the end-to-end CRUD script. `uv run python spike.py` prints `OK`.
