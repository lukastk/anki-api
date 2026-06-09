"""The single-owner, single-writer collection handle.

Findings from the experiments that this encodes:
  - exp 02: the backend takes an exclusive lock on the file (a 2nd open raises
    DBError). One process owns one collection; we hold it open for the server's
    lifetime and serialize every access through one lock.
  - exp 03: FastAPI sync `def` endpoints run in a threadpool; a threading.Lock
    around collection access is the whole concurrency story.
  - exp 04: sync is a client operation; the auth token is persisted to a sidecar
    file so a login survives restarts, and auto-login from configured credentials
    re-establishes it if the token is missing.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import anki.lang
from anki.collection import Collection
from anki.sync_pb2 import SyncAuth
from google.protobuf.json_format import MessageToDict, ParseDict

from .config import Settings
from .errors import CollectionUnavailable

log = logging.getLogger("anki_api.sync")


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

        # Sync state. The auth (hkey + endpoint) is persisted so a login survives
        # restarts; server_media_usn comes from the last incremental sync and is
        # needed for a full download.
        self._auth_path = settings.resolved_sync_auth_path
        self.sync_auth: SyncAuth | None = self._load_auth()
        self.server_media_usn: int = 0

    @contextmanager
    def locked(self) -> Iterator[Collection]:
        """Acquire the writer lock and yield the open collection.

        Raises CollectionUnavailable (-> HTTP 503) if the collection is closed,
        e.g. during a full-sync swap.
        """
        with self._lock:
            if self._col is None:
                raise CollectionUnavailable("collection is closed")
            yield self._col

    @property
    def path(self) -> str:
        return self._settings.collection_path

    @property
    def settings(self) -> Settings:
        return self._settings

    def close(self) -> None:
        with self._lock:
            if self._col is not None:
                self._col.close()
                self._col = None

    # --- sync auth persistence ---

    def _load_auth(self) -> SyncAuth | None:
        if not os.path.exists(self._auth_path):
            return None
        try:
            with open(self._auth_path) as f:
                return ParseDict(json.load(f), SyncAuth())
        except Exception as e:  # corrupt/unreadable token file shouldn't kill startup
            log.warning("ignoring unreadable sync auth at %s: %s", self._auth_path, e)
            return None

    def save_sync_auth(self, auth: SyncAuth) -> None:
        """Persist the auth token (0600) and keep it in memory."""
        os.makedirs(os.path.dirname(self._auth_path), exist_ok=True)
        data = json.dumps(MessageToDict(auth, preserving_proto_field_name=True))
        # Write 0600 from creation (don't briefly expose the token world-readable).
        fd = os.open(self._auth_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.chmod(self._auth_path, 0o600)
        self.sync_auth = auth

    def clear_sync_auth(self) -> None:
        if os.path.exists(self._auth_path):
            os.remove(self._auth_path)
        self.sync_auth = None

    def ensure_logged_in(self) -> bool:
        """Best-effort: log in from configured credentials if not already authed.

        Returns True if a usable auth token is present afterwards. Never raises —
        a transient login failure is logged and retried on the next call (e.g. the
        next autosync tick)."""
        if self.sync_auth is not None:
            return True
        s = self._settings
        if not (s.sync_username and s.sync_password):
            return False
        try:
            with self.locked() as col:
                auth = col.sync_login(s.sync_username, s.sync_password, s.sync_endpoint or None)
            self.save_sync_auth(auth)
            log.info("auto-logged in to sync endpoint %s", auth.endpoint or "ankiweb")
            return True
        except Exception as e:
            log.warning("auto-login failed (will retry): %s", e)
            return False
