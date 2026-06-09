"""Unit-test the exception->HTTP mapping in isolation.

anki BackendError subclasses take (message, help_page, context, backtrace);
we construct them with a message + Nones so str() works in the handler.
"""

import pytest
from anki import errors as anki_errors
from fastapi import FastAPI
from fastapi.testclient import TestClient

from anki_api.errors import CollectionUnavailable, register_exception_handlers


def _raise_app(exc: Exception) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def _backend(cls, msg="boom"):
    return cls(msg, None, None, None)


@pytest.mark.parametrize(
    "cls,expected_status,expected_code",
    [
        (anki_errors.NotFoundError, 404, "not_found"),
        (anki_errors.DeletedError, 404, "deleted"),
        (anki_errors.ExistsError, 409, "already_exists"),
        (anki_errors.FilteredDeckError, 409, "filtered_deck"),
        (anki_errors.CardTypeError, 422, "card_type_error"),
        (anki_errors.TemplateError, 422, "template_error"),
        (anki_errors.InvalidInput, 400, "invalid_input"),
        (anki_errors.SearchError, 400, "invalid_search"),
        (anki_errors.UndoEmpty, 409, "undo_empty"),
    ],
)
def test_backend_error_mapping(cls, expected_status, expected_code):
    resp = _raise_app(_backend(cls)).get("/boom")
    assert resp.status_code == expected_status
    assert resp.json()["error"] == expected_code
    assert resp.json()["message"] == "boom"


def test_unknown_backend_error_is_loud_500():
    # A BackendError subtype we don't map must surface as 500, not be swallowed.
    resp = _raise_app(_backend(anki_errors.NetworkError)).get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"] == "backend_error"


def test_db_error_is_409():
    resp = _raise_app(_backend(anki_errors.DBError)).get("/boom")
    assert resp.status_code == 409
    assert resp.json()["error"] == "collection_busy"


def test_abort_schema_modification_is_409():
    # Not a BackendError subclass -> handled by its own registered handler.
    resp = _raise_app(anki_errors.AbortSchemaModification("schema")).get("/boom")
    assert resp.status_code == 409
    assert resp.json()["error"] == "schema_modification_required"


def test_collection_unavailable_is_503():
    resp = _raise_app(CollectionUnavailable("closed")).get("/boom")
    assert resp.status_code == 503
    assert resp.json()["error"] == "collection_unavailable"
