"""The single-owner, single-writer collection handle.

Findings from the experiments that this encodes:
  - exp 02: the backend takes an exclusive lock on the file (a 2nd open raises
    DBError). One process owns one collection; we hold it open for the server's
    lifetime and serialize every access through one lock.
  - exp 03: FastAPI sync `def` endpoints run in a threadpool; a threading.Lock
    around collection access is the whole concurrency story.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import anki.lang
from anki.collection import Collection

from .config import Settings
from .errors import CollectionUnavailable


class CollectionHandle:
    """Owns one open Collection and the lock that serializes access to it."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        # Initialise the process-global i18n (the GUI does this on startup). Some
        # backend helpers (e.g. find_dupes -> strip_html_media) read it; it's None
        # otherwise and they crash.
        anki.lang.set_lang(settings.lang)
        self._col: Collection | None = Collection(settings.collection_path)
        if settings.enable_v3_scheduler and not self._col.v3_scheduler():
            self._col.set_v3_scheduler(True)

    @contextmanager
    def locked(self) -> Iterator[Collection]:
        """Acquire the writer lock and yield the open collection.

        Raises CollectionUnavailable (-> HTTP 503) if the collection is closed,
        e.g. during a future full-sync swap.
        """
        with self._lock:
            if self._col is None:
                raise CollectionUnavailable("collection is closed")
            yield self._col

    @property
    def path(self) -> str:
        return self._settings.collection_path

    def close(self) -> None:
        with self._lock:
            if self._col is not None:
                self._col.close()
                self._col = None
