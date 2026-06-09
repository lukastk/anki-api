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
        )


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
