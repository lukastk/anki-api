"""Shared schemas: the OpChanges mutation envelope and common request shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OpChangesModel(BaseModel):
    """Which views the client should refresh after a mutation.

    Mirrors anki's `collection_pb2.OpChanges`. A reactive UI uses these flags to
    decide what to invalidate; if every flag is false the op was a no-op.
    """

    card: bool = False
    note: bool = False
    deck: bool = False
    tag: bool = False
    notetype: bool = False
    config: bool = False
    deck_config: bool = False
    mtime: bool = False
    browser_table: bool = False
    browser_sidebar: bool = False
    note_text: bool = False
    study_queues: bool = False


class Mutation(BaseModel):
    """Uniform envelope returned by mutating endpoints."""

    id: str | None = Field(default=None, description="present for create ops (OpChangesWithId)")
    count: int | None = Field(default=None, description="present for count ops (OpChangesWithCount)")
    changes: OpChangesModel = Field(default_factory=OpChangesModel)


# The OpChanges proto field names we mirror, kept in one place.
_OPCHANGES_FIELDS = (
    "card", "note", "deck", "tag", "notetype", "config",
    "deck_config", "mtime", "browser_table", "browser_sidebar",
    "note_text", "study_queues",
)


def op_changes(changes) -> OpChangesModel:
    """Build an OpChangesModel from an anki OpChanges proto (or the .changes of a
    wrapper like OpChangesWithId/WithCount)."""
    return OpChangesModel(**{name: getattr(changes, name) for name in _OPCHANGES_FIELDS})


def mutation(changes, *, id: int | None = None, count: int | None = None) -> Mutation:
    """Build the uniform mutation envelope from an anki OpChanges-bearing result."""
    return Mutation(
        id=str(id) if id is not None else None,
        count=count,
        changes=op_changes(changes),
    )
