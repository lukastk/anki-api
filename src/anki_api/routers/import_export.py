"""Import / Export [parity].

All backend import/export calls are file-path based, so the REST layer bridges
with temp files: exports stream the produced file back; imports accept an upload.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from anki import import_export_pb2 as ie
# all from anki.collection: importing anki.cards or anki.decks first trips a circular
# import inside the anki package, and collection re-exports the id NewTypes anyway
from anki.collection import CardId, CardIdsLimit, DeckId, DeckIdLimit, NoteId, NoteIdsLimit
from anki.utils import ids2str
from google.protobuf.json_format import MessageToDict
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, model_validator
from starlette.background import BackgroundTask

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id, parse_ids

router = APIRouter(tags=["import-export"])


class ExportLimit(BaseModel):
    """What to export: the whole collection, one deck (`deck_id`), or the notes / cards in
    `ids`.

    A limit that does not say one consistent thing is refused (422) rather than read
    generously, because the generous reading of an export limit is a WIDER export:
    `{"deck_id": "5"}` with `scope` left out used to mean the whole collection, and so did a
    misspelled key. Hence `extra="forbid"` and the validator below."""

    model_config = ConfigDict(extra="forbid")

    scope: Literal["collection", "deck", "notes", "cards"] = "collection"
    deck_id: str | None = None
    ids: list[str] | None = None

    @model_validator(mode="after")
    def _fields_match_scope(self) -> ExportLimit:
        if self.scope == "deck":
            if self.deck_id is None:
                raise ValueError("deck_id required for scope=deck")
        elif self.deck_id is not None:
            raise ValueError(f"deck_id given with scope={self.scope}; it only applies to scope=deck")
        if self.scope in ("notes", "cards"):
            if self.ids is None:
                raise ValueError(f"ids required for scope={self.scope}")
        elif self.ids is not None:
            raise ValueError(f"ids given with scope={self.scope}; they only apply to scope=notes or scope=cards")
        return self


class ExportApkg(BaseModel):
    limit: ExportLimit = ExportLimit()
    with_scheduling: bool = False
    with_media: bool = True
    with_deck_configs: bool = False
    legacy: bool = False


class ExportNotesCsv(BaseModel):
    limit: ExportLimit = ExportLimit()
    with_html: bool = True
    with_tags: bool = True
    with_deck: bool = True
    with_notetype: bool = True
    with_guid: bool = False


class ExportCardsCsv(BaseModel):
    limit: ExportLimit = ExportLimit()
    with_html: bool = True


class ImportApkgOptions(BaseModel):
    merge_notetypes: bool = False
    with_scheduling: bool = False
    with_deck_configs: bool = False


def _existing_ids(col, table: Literal["notes", "cards"], ids: list[int]) -> list[int]:
    """`ids` as given, after checking every one is a row of `table` — 404 naming the ones
    that are not. Anki's exporters skip an unknown id without a word, so an export asked for
    N notes would come back with fewer and still be a 200."""
    found = set(col.db.list(f"select id from {table} where id in {ids2str(ids)}"))
    missing = [i for i in ids if i not in found]
    if missing:
        shown = ", ".join(str(i) for i in missing[:20])
        more = f" (and {len(missing) - 20} more)" if len(missing) > 20 else ""
        raise HTTPException(status_code=404, detail=f"{len(missing)} of the {len(ids)} {table[:-1]} ids not found: {shown}{more}")
    return ids


def _build_limit(col, limit: ExportLimit) -> DeckIdLimit | NoteIdsLimit | CardIdsLimit | None:
    """The limit Anki's exporters take — one of its WRAPPER types, or None for the whole
    collection — after checking that what it names exists (404 otherwise).

    Not the `ie.ExportLimit` protobuf, which is what this returned until 2026-10-01 and
    which silently exported everything. `Collection.export_anki_package` passes whatever it
    is given through `anki.collection.pb_export_limit`, and that dispatches on
    `isinstance(limit, DeckIdLimit | NoteIdsLimit | CardIdsLimit)` and falls through to
    `whole_collection` for anything else — including a ready-made protobuf of exactly the
    right shape. So every scoped export returned the entire collection and still answered
    200 with a valid .apkg. Asking for one 30-card deck of a 1032-card collection returned
    all 1032.

    `ExportLimit`'s validator has already established that the fields fit the scope.
    """
    if limit.scope == "collection":
        return None
    if limit.scope == "deck":
        did = parse_id(limit.deck_id)
        if col.decks.get_legacy(did) is None:
            raise HTTPException(status_code=404, detail=f"deck {limit.deck_id} not found")
        return DeckIdLimit(DeckId(did))
    if limit.scope == "notes":
        return NoteIdsLimit([NoteId(i) for i in _existing_ids(col, "notes", parse_ids(limit.ids))])
    return CardIdsLimit([CardId(i) for i in _existing_ids(col, "cards", parse_ids(limit.ids))])


def _tempfile(suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="anki-export-")
    os.close(fd)
    return path


@contextmanager
def _export_file(suffix: str) -> Iterator[str]:
    """A temp file for an exporter to write. Removed if the export raises; on success it is
    `_download`'s background task that removes it, once the response has been sent."""
    path = _tempfile(suffix)
    try:
        yield path
    except BaseException:
        os.unlink(path)
        raise


def _download(path: str, filename: str, media_type: str) -> FileResponse:
    return FileResponse(path, filename=filename, media_type=media_type,
                        background=BackgroundTask(os.unlink, path))


# --- exports ---

@router.post("/export/apkg")
def export_apkg(body: ExportApkg, handle: CollectionHandle = Depends(get_handle)) -> FileResponse:
    """An .apkg of exactly what `limit` names (422 if the limit contradicts itself, 404 if it names a deck, note or card that does not exist)."""
    with handle.locked() as col:
        limit = _build_limit(col, body.limit)
        with _export_file(".apkg") as path:
            col.export_anki_package(
                out_path=path,
                options=ie.ExportAnkiPackageOptions(
                    with_scheduling=body.with_scheduling,
                    with_media=body.with_media,
                    with_deck_configs=body.with_deck_configs,
                    legacy=body.legacy,
                ),
                limit=limit,
            )
    return _download(path, "export.apkg", "application/octet-stream")


@router.post("/export/notes-csv")
def export_notes_csv(body: ExportNotesCsv, handle: CollectionHandle = Depends(get_handle)) -> FileResponse:
    """A tab-separated export of exactly the notes `limit` names (same 422 / 404 rules as /export/apkg)."""
    with handle.locked() as col:
        limit = _build_limit(col, body.limit)
        with _export_file(".csv") as path:
            col.export_note_csv(
                out_path=path, limit=limit, with_html=body.with_html,
                with_tags=body.with_tags, with_deck=body.with_deck,
                with_notetype=body.with_notetype, with_guid=body.with_guid,
            )
    return _download(path, "notes.csv", "text/csv")


@router.post("/export/cards-csv")
def export_cards_csv(body: ExportCardsCsv, handle: CollectionHandle = Depends(get_handle)) -> FileResponse:
    """A tab-separated question/answer export of exactly the cards `limit` names (same 422 / 404 rules as /export/apkg)."""
    with handle.locked() as col:
        limit = _build_limit(col, body.limit)
        with _export_file(".csv") as path:
            col.export_card_csv(out_path=path, limit=limit, with_html=body.with_html)
    return _download(path, "cards.csv", "text/csv")


# --- imports ---

def _save_upload(file: UploadFile, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="anki-import-")
    with os.fdopen(fd, "wb") as out:
        out.write(file.file.read())
    return path


@router.post("/import/apkg")
def import_apkg(
    file: UploadFile,
    merge_notetypes: bool = False,
    with_scheduling: bool = False,
    with_deck_configs: bool = False,
    handle: CollectionHandle = Depends(get_handle),
) -> dict:
    path = _save_upload(file, ".apkg")
    try:
        with handle.locked() as col:
            log = col.import_anki_package(
                ie.ImportAnkiPackageRequest(
                    package_path=path,
                    options=ie.ImportAnkiPackageOptions(
                        merge_notetypes=merge_notetypes,
                        with_scheduling=with_scheduling,
                        with_deck_configs=with_deck_configs,
                    ),
                )
            )
        return MessageToDict(log, preserving_proto_field_name=True)
    finally:
        os.unlink(path)


@router.post("/import/csv/metadata")
def csv_metadata(file: UploadFile, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Detected metadata (delimiter, column count, html-ness) for an uploaded CSV,
    used to build the import request."""
    path = _save_upload(file, ".csv")
    try:
        with handle.locked() as col:
            return MessageToDict(col.get_csv_metadata(path, None), preserving_proto_field_name=True)
    finally:
        os.unlink(path)


@router.post("/import/csv")
def import_csv(
    file: UploadFile,
    deck_id: str = "",
    notetype_id: str = "",
    handle: CollectionHandle = Depends(get_handle),
) -> dict:
    """Import notes from a CSV using detected metadata, into the given deck +
    notetype (column order maps to the notetype's fields). 404 for a deck or notetype
    that does not exist."""
    path = _save_upload(file, ".csv")
    try:
        with handle.locked() as col:
            metadata = col.get_csv_metadata(path, None)
            if deck_id:
                # the importer does not reject an unknown deck id: it creates a deck NAMED
                # after the id and imports into that
                did = parse_id(deck_id)
                if col.decks.get_legacy(did) is None:
                    raise HTTPException(status_code=404, detail=f"deck {deck_id} not found")
                metadata.deck_id = did
            if notetype_id:
                # nor an unknown notetype id: it imports nothing, reports the rows under
                # `missing_notetype` and succeeds
                ntid = parse_id(notetype_id)
                if col.models.get(ntid) is None:
                    raise HTTPException(status_code=404, detail=f"notetype {notetype_id} not found")
                metadata.global_notetype.id = ntid
            log = col.import_csv(ie.ImportCsvRequest(path=path, metadata=metadata))
        return MessageToDict(log, preserving_proto_field_name=True)
    finally:
        os.unlink(path)
