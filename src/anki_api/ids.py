"""ID handling.

Anki ids are 64-bit integers that exceed JS Number.MAX_SAFE_INTEGER, so the API
serializes every id as a STRING in JSON and parses it back to int server-side.
These helpers centralise the conversion.
"""

from __future__ import annotations

from fastapi import HTTPException


def parse_id(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"invalid id: {value!r}")


def parse_ids(values: list[str]) -> list[int]:
    return [parse_id(v) for v in values]


def to_id(value: int) -> str:
    return str(value)
