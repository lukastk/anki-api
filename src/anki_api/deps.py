"""Dependency wiring: access to the process-wide CollectionHandle."""

from __future__ import annotations

from fastapi import Request

from .collection_handle import CollectionHandle
from .errors import CollectionUnavailable


def get_handle(request: Request) -> CollectionHandle:
    handle: CollectionHandle | None = getattr(request.app.state, "handle", None)
    if handle is None:
        raise CollectionUnavailable("collection handle not initialised")
    return handle
