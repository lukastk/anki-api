"""Review log [mosaic-v4]: bulk read, history replay, and exact orphan cleanup.

Insert is the history replay for atom cards. Exact deletion is a deliberately narrow
migration repair: every row is named by both ids and is deletable only while its card
does not exist. Both writes transact raw SQL so Anki marks the collection modified.
"""

from __future__ import annotations

import time

from anki.utils import ids2str
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_id, parse_ids
from ..schemas.common import RequestModel

router = APIRouter(prefix="/revlog", tags=["revlog"])

_COLUMNS = ("id", "cid", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type")


class RevlogEntry(RequestModel):
    card_id: str
    id_ms: str = Field(description="the row id: the review's epoch MILLISECONDS; unique, not in the future")
    ease: int = Field(ge=1, le=4, description="1 again, 2 hard, 3 good, 4 easy")
    interval: int = Field(description="ivl: days if positive, seconds if negative (learning)")
    last_interval: int = Field(description="lastIvl, same units as interval")
    factor: int = Field(description="ease per-mille, e.g. 2500 (0 for learning rows)")
    time_ms: int = Field(ge=0, description="time spent answering, milliseconds")
    type: int = Field(ge=0, le=3, description="0 learn, 1 review, 2 relearn, 3 filtered; 4/5 are Anki's own (manual, rescheduled)")


class InsertRevlog(RequestModel):
    entries: list[RevlogEntry]


class ExactRevlogRow(RequestModel):
    id: str
    card_id: str


class DeleteExactRevlog(RequestModel):
    rows: list[ExactRevlogRow]


def _split_ids(values: list[str] | None) -> list[int] | None:
    """`card_ids` may be repeated, comma-separated, or both."""
    if values is None:
        return None
    return parse_ids([v for value in values for v in value.split(",") if v])


@router.get("")
def read_revlog(
    since_ms: int | None = Query(default=None, description="revlog id >= since_ms (inclusive)"),
    until_ms: int | None = Query(default=None, description="revlog id < until_ms (exclusive)"),
    card_ids: list[str] | None = Query(default=None, description="repeatable or comma-separated"),
    types: list[int] | None = Query(default=None, description="revlog types to include (repeatable)"),
    limit: int = Query(default=10_000, ge=1, le=100_000),
    handle: CollectionHandle = Depends(get_handle),
) -> dict:
    """Review-log rows ordered by id (epoch ms, a string like every id). `truncated` is true when more rows match than `limit`."""
    cids = _split_ids(card_ids)
    where, args = [], []
    if since_ms is not None:
        where.append("id >= ?")
        args.append(since_ms)
    if until_ms is not None:
        where.append("id < ?")
        args.append(until_ms)
    if cids is not None:
        where.append(f"cid in {ids2str(cids)}")
    if types is not None:
        where.append(f"type in {ids2str(types)}")
    sql = f"select {', '.join(_COLUMNS)} from revlog"
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by id limit ?"
    args.append(limit + 1)
    with handle.locked() as col:
        rows = col.db.all(sql, *args)
    return {
        "entries": [
            {"id": str(rid), "card_id": str(cid), "usn": usn, "ease": ease, "interval": ivl,
             "last_interval": last_ivl, "factor": factor, "time_ms": time_ms, "type": rtype}
            for rid, cid, usn, ease, ivl, last_ivl, factor, time_ms, rtype in rows[:limit]
        ],
        "truncated": len(rows) > limit,
    }


@router.post("")
def insert_revlog(body: InsertRevlog, handle: CollectionHandle = Depends(get_handle)) -> dict:
    """Insert review-log rows (usn -1, so they sync). All or nothing: every row is validated
    before any is written — 404 for an unknown card (the first one), 422 for an id that is
    repeated, already in the table, or in the future.

    The write runs in `col.db.transact` (the backend's db_begin/db_commit), which is also
    what marks the collection modified: the commit bumps `col.mod`, so the next incremental
    sync sees a change. A bare `col.db.executemany` outside a transaction autocommits
    WITHOUT bumping `col.mod` (verified on anki 25.09.4 and 26.09.3). `col.save()` is a deprecated no-op
    and is not called anywhere in this code base."""
    rows = []
    seen: set[int] = set()
    now_ms = int(time.time() * 1000)
    for e in body.entries:
        rid = parse_id(e.id_ms)
        if rid in seen:
            raise HTTPException(status_code=422, detail=f"id_ms {rid} appears more than once in the request")
        if rid > now_ms:
            raise HTTPException(status_code=422, detail=f"id_ms {rid} is in the future")
        if rid <= 0:
            raise HTTPException(status_code=422, detail=f"id_ms {rid} is not a positive epoch-ms stamp")
        seen.add(rid)
        rows.append((rid, parse_id(e.card_id), -1, e.ease, e.interval, e.last_interval, e.factor, e.time_ms, e.type))
    if not rows:
        return {"inserted": 0}
    with handle.locked() as col:
        cids = list(dict.fromkeys(r[1] for r in rows))
        existing_cards = set(col.db.list(f"select id from cards where id in {ids2str(cids)}"))
        missing = next((cid for cid in cids if cid not in existing_cards), None)
        if missing is not None:
            raise HTTPException(status_code=404, detail=f"card {missing} not found")
        taken = col.db.list(f"select id from revlog where id in {ids2str(sorted(seen))} order by id")
        if taken:
            raise HTTPException(status_code=422, detail=f"revlog id(s) already present: {', '.join(map(str, taken))}")
        placeholders = ", ".join("?" * len(_COLUMNS))
        col.db.transact(lambda: col.db.executemany(
            f"insert into revlog ({', '.join(_COLUMNS)}) values ({placeholders})", rows,
        ))
    return {"inserted": len(rows)}


@router.post("/delete-exact")
def delete_exact_orphan_revlog(
    body: DeleteExactRevlog, handle: CollectionHandle = Depends(get_handle),
) -> dict:
    """Delete explicitly named orphan rows, atomically.

    Every request row names both its revlog id and stored card id. The entire call
    refuses before writing if a row is absent, the card id does not match, or that
    card currently exists. This is for removing stale history before re-importing
    cards with reused ids; it cannot erase the history of a live card.
    """
    requested: list[tuple[int, int]] = []
    seen: set[int] = set()
    for row in body.rows:
        rid, cid = parse_id(row.id), parse_id(row.card_id)
        if rid in seen:
            raise HTTPException(status_code=422, detail=f"revlog id {rid} appears more than once in the request")
        seen.add(rid)
        requested.append((rid, cid))
    if not requested:
        return {"deleted": 0, "rows": []}
    with handle.locked() as col:
        stored = dict(col.db.all(
            f"select id, cid from revlog where id in {ids2str([rid for rid, _ in requested])}",
        ))
        for rid, cid in requested:
            if rid not in stored:
                raise HTTPException(status_code=404, detail=f"revlog id {rid} not found")
            if stored[rid] != cid:
                raise HTTPException(
                    status_code=409,
                    detail=f"revlog id {rid} belongs to card {stored[rid]}, not requested card {cid}",
                )
        live = set(col.db.list(
            f"select id from cards where id in {ids2str([cid for _, cid in requested])}",
        ))
        if live:
            raise HTTPException(
                status_code=409, detail=f"refusing to delete history for live card(s): {', '.join(map(str, sorted(live)))}",
            )
        col.db.transact(lambda: col.db.executemany(
            "delete from revlog where id = ? and cid = ?", requested,
        ))
    rows = [{"id": str(rid), "card_id": str(cid)} for rid, cid in requested]
    return {"deleted": len(rows), "rows": rows}
