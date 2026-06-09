"""Server configuration, sourced from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the server.

    A single server process owns exactly one collection (see experiment 02: the
    Anki backend takes an exclusive lock on the file, so one process == one file).
    """

    collection_path: str
    enable_v3_scheduler: bool = True
    lang: str = "en"

    # Sync. Auth is persisted to a 0600 sidecar file so a login survives restarts.
    # If no persisted auth exists and sync_username/password are set, the server
    # logs in automatically on startup (endpoint=None -> AnkiWeb).
    sync_auth_path: str | None = None
    sync_username: str | None = None
    sync_password: str | None = None
    sync_endpoint: str | None = None  # None -> AnkiWeb
    # Background incremental sync interval in seconds; 0 disables it.
    autosync_interval: int = 0

    @property
    def resolved_sync_auth_path(self) -> str:
        """Where the persisted sync auth token lives (defaults next to the collection)."""
        if self.sync_auth_path:
            return self.sync_auth_path
        return os.path.join(os.path.dirname(self.collection_path), "sync_auth.json")

    @classmethod
    def from_env(cls) -> "Settings":
        path = os.environ.get("ANKI_API_COLLECTION")
        if not path:
            raise RuntimeError(
                "ANKI_API_COLLECTION must be set to the path of the .anki2 collection "
                "file to serve (it will be created if it does not exist)."
            )
        return cls(
            collection_path=os.path.abspath(path),
            enable_v3_scheduler=_env_bool("ANKI_API_V3_SCHEDULER", default=True),
            lang=os.environ.get("ANKI_API_LANG", "en"),
            sync_auth_path=os.environ.get("ANKI_API_SYNC_AUTH_PATH") or None,
            sync_username=os.environ.get("ANKI_API_SYNC_USERNAME") or None,
            sync_password=os.environ.get("ANKI_API_SYNC_PASSWORD") or None,
            sync_endpoint=os.environ.get("ANKI_API_SYNC_ENDPOINT") or None,
            autosync_interval=int(os.environ.get("ANKI_API_AUTOSYNC_INTERVAL", "0")),
        )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
