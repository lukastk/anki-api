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
    # What the autosync loop does when a full sync is REQUIRED. "off" (default,
    # and the only general-purpose-safe choice): log it and leave it — a full sync
    # overwrites one side, so the direction stays a deliberate manual call to
    # /sync/full-{upload,download}. "download": the loop MAY auto-resolve by
    # full-DOWNLOADING (adopting the server), but ONLY when this collection has no
    # un-synced schema change of its own (never-synced included) — so nothing
    # local-only is discarded that the server lacks. Auto-UPLOAD is never a policy
    # (it would overwrite the server from a possibly-stale copy). Intended for a
    # deployment where this collection is a downstream replica of an external
    # source of truth, not a primary you review on. See routers/sync.run_autosync.
    autosync_full: str = "off"
    # Optional best-effort notifier. When set, it is run as `<cmd> <title> <body>`
    # (argv, never a shell string) whenever the autosync loop auto-resolves a full
    # sync or is blocked needing a manual one, so a human can learn about it.
    # Failures are swallowed — a notifier must never break syncing.
    autosync_notify_cmd: str | None = None

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
            autosync_full=_env_choice("ANKI_API_AUTOSYNC_FULL", default="off",
                                      choices=_AUTOSYNC_FULL_CHOICES),
            autosync_notify_cmd=os.environ.get("ANKI_API_AUTOSYNC_NOTIFY_CMD") or None,
        )


# Policies the autosync loop accepts for a required full sync. "upload" is
# intentionally absent — it is never safe to overwrite the server unattended.
_AUTOSYNC_FULL_CHOICES = frozenset({"off", "download"})


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_choice(name: str, *, default: str, choices: frozenset[str]) -> str:
    val = (os.environ.get(name) or default).strip().lower()
    if val not in choices:
        raise RuntimeError(
            f"{name}={val!r} is invalid; expected one of {sorted(choices)}."
        )
    return val
