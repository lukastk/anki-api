"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .collection_handle import CollectionHandle
from .config import Settings
from .errors import register_exception_handlers
from .routers import (
    cards, deck_presets, decks, filtered_decks, fsrs, image_occlusion, import_export, media, notes,
    notetypes, preferences, review, search, stats, sync, system, tags, tts, typing_answer, undo,
    util,
)

log = logging.getLogger("anki_api.sync")


async def _autosync_loop(handle: CollectionHandle, interval: int) -> None:
    """Run an incremental sync every `interval` seconds (the sync itself is
    blocking, so it runs in a worker thread). Errors are logged, never fatal."""
    while True:
        await asyncio.sleep(interval)
        try:
            result = await asyncio.to_thread(sync.run_autosync, handle)
            log.info("autosync: %s", result)
        except Exception as e:  # a bad tick must not kill the loop
            log.warning("autosync tick failed: %s", e)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        handle = CollectionHandle(settings)
        app.state.handle = handle
        # Establish sync auth up front (persisted token, or auto-login from creds).
        handle.ensure_logged_in()
        autosync_task = None
        if settings.autosync_interval > 0:
            autosync_task = asyncio.create_task(_autosync_loop(handle, settings.autosync_interval))
        try:
            yield
        finally:
            if autosync_task is not None:
                autosync_task.cancel()
            handle.close()
            app.state.handle = None

    app = FastAPI(
        title="anki-api",
        version="0.1.0",
        summary="Headless REST API over an Anki collection.",
        lifespan=lifespan,
    )
    register_exception_handlers(app)

    for module in (system, decks, deck_presets, notes, notetypes, cards, review, search, tags,
                   stats, preferences, media, import_export, fsrs, filtered_decks, sync,
                   image_occlusion, undo, typing_answer, tts, util):
        app.include_router(module.router, prefix="/v1")

    return app
