"""Map Anki backend exceptions to HTTP responses.

We deliberately do NOT swallow unexpected errors — anything we don't explicitly
recognise propagates and becomes a 500, so bugs stay loud.
"""

from __future__ import annotations

from anki import errors as anki_errors
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class CollectionUnavailable(RuntimeError):
    """Raised when the collection is closed (e.g. mid full-sync) or not yet open."""


def _error_body(code: str, message: str) -> dict:
    return {"error": code, "message": message}


# (exception type) -> (http status, error code). Order matters: most specific first.
_MAPPING: list[tuple[type[Exception], int, str]] = [
    (anki_errors.NotFoundError, 404, "not_found"),
    (anki_errors.DeletedError, 404, "deleted"),
    (anki_errors.ExistsError, 409, "already_exists"),
    (anki_errors.FilteredDeckError, 409, "filtered_deck"),
    (anki_errors.CardTypeError, 422, "card_type_error"),
    (anki_errors.TemplateError, 422, "template_error"),
    (anki_errors.InvalidInput, 400, "invalid_input"),
    (anki_errors.SearchError, 400, "invalid_search"),
    (anki_errors.UndoEmpty, 409, "undo_empty"),
    (anki_errors.AbortSchemaModification, 409, "schema_modification_required"),
    (anki_errors.DBError, 409, "collection_busy"),
    (CollectionUnavailable, 503, "collection_unavailable"),
]


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CollectionUnavailable)
    async def _unavailable(_: Request, exc: CollectionUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content=_error_body("collection_unavailable", str(exc)))

    @app.exception_handler(anki_errors.BackendError)
    async def _anki(_: Request, exc: anki_errors.BackendError) -> JSONResponse:
        for exc_type, status, code in _MAPPING:
            if isinstance(exc, exc_type):
                return JSONResponse(status_code=status, content=_error_body(code, str(exc)))
        # Unknown backend error: surface it loudly as a 500.
        return JSONResponse(status_code=500, content=_error_body("backend_error", str(exc)))

    @app.exception_handler(anki_errors.DBError)
    async def _db(_: Request, exc: anki_errors.DBError) -> JSONResponse:
        return JSONResponse(status_code=409, content=_error_body("collection_busy", str(exc)))
