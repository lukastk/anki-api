"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .collection_handle import CollectionHandle
from .config import Settings
from .errors import register_exception_handlers
from .routers import (
    cards, deck_presets, decks, filtered_decks, fsrs, import_export, media, notes, notetypes,
    preferences, review, search, stats, system, tags, tts, typing_answer, undo, util,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        handle = CollectionHandle(settings)
        app.state.handle = handle
        try:
            yield
        finally:
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
                   stats, preferences, media, import_export, fsrs, filtered_decks, undo,
                   typing_answer, tts, util):
        app.include_router(module.router, prefix="/v1")

    return app
