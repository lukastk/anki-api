"""Tag endpoints [parity]: the tag tree/sidebar + bulk tagging operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..collection_handle import CollectionHandle
from ..deps import get_handle
from ..ids import parse_ids
from ..schemas.common import Mutation, mutation

router = APIRouter(prefix="/tags", tags=["tags"])


class TagsOnNotes(BaseModel):
    note_ids: list[str]
    tags: list[str]


class RenameTag(BaseModel):
    old: str
    new: str


class Reparent(BaseModel):
    tags: list[str]
    new_parent: str


class DeleteTags(BaseModel):
    tags: list[str]


class SetCollapsed(BaseModel):
    tag: str
    collapsed: bool


def _tree(node) -> dict:
    return {
        "name": node.name,
        "level": node.level,
        "collapsed": node.collapsed,
        "children": [_tree(c) for c in node.children],
    }


@router.get("")
def list_tags(handle: CollectionHandle = Depends(get_handle)) -> list[str]:
    with handle.locked() as col:
        return list(col.tags.all())


@router.get("/tree")
def tag_tree(handle: CollectionHandle = Depends(get_handle)) -> dict:
    with handle.locked() as col:
        return _tree(col.tags.tree())


@router.post("/actions/add")
def add_tags(body: TagsOnNotes, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.tags.bulk_add(parse_ids(body.note_ids), " ".join(body.tags))
        return mutation(out.changes, count=out.count)


@router.post("/actions/remove")
def remove_tags(body: TagsOnNotes, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.tags.bulk_remove(parse_ids(body.note_ids), " ".join(body.tags))
        return mutation(out.changes, count=out.count)


@router.post("/rename")
def rename_tag(body: RenameTag, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.tags.rename(body.old, body.new)
        return mutation(out.changes, count=out.count)


@router.post("/reparent")
def reparent_tags(body: Reparent, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.tags.reparent(body.tags, body.new_parent)
        return mutation(out.changes, count=out.count)


@router.post("/actions/delete")
def delete_tags(body: DeleteTags, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    """Remove the given tags entirely (from all notes)."""
    with handle.locked() as col:
        out = col.tags.remove(" ".join(body.tags))
        return mutation(out.changes, count=out.count)


@router.post("/set-collapsed")
def set_collapsed(body: SetCollapsed, handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        return mutation(col.tags.set_collapsed(body.tag, body.collapsed))


@router.post("/clear-unused")
def clear_unused(handle: CollectionHandle = Depends(get_handle)) -> Mutation:
    with handle.locked() as col:
        out = col.tags.clear_unused_tags()
        return mutation(out.changes, count=out.count)
