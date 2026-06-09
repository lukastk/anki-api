"""CLI entrypoint: `anki-api` (or `python -m anki_api`)."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "anki_api.app:create_app",
        factory=True,
        host=os.environ.get("ANKI_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("ANKI_API_PORT", "8765")),
        # One process owns the collection (exclusive lock) -> never >1 worker.
        workers=1,
    )


if __name__ == "__main__":
    main()
