"""Collection / system endpoints: health and collection info."""

from __future__ import annotations

import os
import time

from google.protobuf.json_format import MessageToDict
from fastapi import APIRouter, Depends

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..schemas.common import Mutation, mutation

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/collection")
def collection_info(handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        return {
            "path": handle.path,
            "created": str(col.db.scalar("select crt from col")),  # epoch seconds
            "schema_modified": str(col.db.scalar("select scm from col")),
            "modified": str(col.mod),
            "v3_scheduler": col.v3_scheduler(),
            "note_count": col.note_count(),
            "card_count": col.card_count(),
        }


@router.get("/collection/timing")
def collection_timing(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Anki's day boundary (sched_timing_today): `days_elapsed` since the collection was
    created, and `next_day_at`, when today ends (the rollover hour, local time). Stamps are
    epoch seconds as strings; `created` is the collection creation stamp (col.crt), the
    same value GET /collection reports."""
    with handle.locked() as col:
        timing = col._backend.sched_timing_today()
        return {
            "days_elapsed": timing.days_elapsed,
            "next_day_at": str(timing.next_day_at),
            "now": str(int(time.time())),
            "created": str(col.crt),
            "rollover_hour": col.get_config("rollover", 4),
        }


@router.post("/collection/backup")
def backup_collection(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Back up the LIVE collection to backups/ (Anki's own .colpkg backups, with its
    built-in rotation). `created` is false when the collection is unchanged since
    the last backup. Complements /sync/backup-remote (which captures the server
    side); run both before a full sync to possess both pre-overwrite states."""
    with handle.locked() as col:
        folder = os.path.join(os.path.dirname(handle.path), "backups")
        os.makedirs(folder, exist_ok=True)
        created = col.create_backup(backup_folder=folder, force=True, wait_for_completion=True)
        return {"created": created, "folder": folder}


@router.post("/collection/check-database")
def check_database(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Tools > Check Database (fsck). Returns the report and whether it was ok."""
    with handle.locked() as col:
        report, ok = col.fix_integrity()
        return {"report": report, "ok": ok}


@router.post("/collection/optimize")
def optimize(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Vacuum/optimize the underlying database."""
    with handle.locked() as col:
        col.optimize()
        return {"ok": True}


@router.get("/collection/empty-cards")
def empty_cards(handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Report of notes that produce empty cards (Tools > Empty Cards)."""
    with handle.locked() as col:
        return MessageToDict(col.get_empty_cards(), preserving_proto_field_name=True)


@router.post("/collection/empty-cards/remove")
def remove_empty_cards(handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        report = col.get_empty_cards()
        card_ids = [cid for note in report.notes for cid in note.card_ids]
        if not card_ids:
            return Mutation(count=0)
        out = col.remove_cards_and_orphaned_notes(card_ids)
        return mutation(out.changes, count=out.count)
