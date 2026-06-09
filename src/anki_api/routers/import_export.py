"""Import / Export [parity].

All backend import/export calls are file-path based, so the REST layer bridges
with temp files: exports stream the produced file back; imports accept an upload.
"""

from __future__ import annotations

import os
import tempfile

from anki import import_export_pb2 as ie
from google.protobuf.json_format import MessageToDict
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id, parse_ids

router = APIRouter(tags=["import-export"])


class ExportLimit(BaseModel):
    scope: str = "collection"  # collection | deck | notes | cards
    deck_id: str | None = None
    ids: list[str] | None = None


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


def _build_limit(limit: ExportLimit) -> ie.ExportLimit:
    out = ie.ExportLimit()
    if limit.scope == "collection":
        out.whole_collection.SetInParent()  # Empty presence marker
    elif limit.scope == "deck":
        if limit.deck_id is None:
            raise HTTPException(status_code=422, detail="deck_id required for scope=deck")
        out.deck_id = parse_id(limit.deck_id)
    elif limit.scope == "notes":
        out.note_ids.note_ids.extend(parse_ids(limit.ids or []))
    elif limit.scope == "cards":
        out.card_ids.cids.extend(parse_ids(limit.ids or []))
    else:
        raise HTTPException(status_code=422, detail=f"unknown export scope {limit.scope!r}")
    return out


def _tempfile(suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="anki-export-")
    os.close(fd)
    return path


def _download(path: str, filename: str, media_type: str) -> FileResponse:
    return FileResponse(path, filename=filename, media_type=media_type,
                        background=BackgroundTask(os.unlink, path))


# --- exports ---

@router.post("/export/apkg")
def export_apkg(body: ExportApkg, handle: CollectionHandle = Depends(get_handle)) -> FileResponse:
    path = _tempfile(".apkg")
    with handle.locked() as col:
        col.export_anki_package(
            out_path=path,
            options=ie.ExportAnkiPackageOptions(
                with_scheduling=body.with_scheduling,
                with_media=body.with_media,
                with_deck_configs=body.with_deck_configs,
                legacy=body.legacy,
            ),
            limit=_build_limit(body.limit),
        )
    return _download(path, "export.apkg", "application/octet-stream")


@router.post("/export/notes-csv")
def export_notes_csv(body: ExportNotesCsv, handle: CollectionHandle = Depends(get_handle)) -> FileResponse:
    path = _tempfile(".csv")
    with handle.locked() as col:
        col.export_note_csv(
            out_path=path, limit=_build_limit(body.limit), with_html=body.with_html,
            with_tags=body.with_tags, with_deck=body.with_deck,
            with_notetype=body.with_notetype, with_guid=body.with_guid,
        )
    return _download(path, "notes.csv", "text/csv")


@router.post("/export/cards-csv")
def export_cards_csv(body: ExportCardsCsv, handle: CollectionHandle = Depends(get_handle)) -> FileResponse:
    path = _tempfile(".csv")
    with handle.locked() as col:
        col.export_card_csv(out_path=path, limit=_build_limit(body.limit), with_html=body.with_html)
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
    notetype (column order maps to the notetype's fields)."""
    path = _save_upload(file, ".csv")
    try:
        with handle.locked() as col:
            metadata = col.get_csv_metadata(path, None)
            if deck_id:
                metadata.deck_id = parse_id(deck_id)
            if notetype_id:
                metadata.global_notetype.id = parse_id(notetype_id)
            log = col.import_csv(ie.ImportCsvRequest(path=path, metadata=metadata))
        return MessageToDict(log, preserving_proto_field_name=True)
    finally:
        os.unlink(path)
