"""CollectionHandle: lifecycle, the single-owner lock, and concurrency.

This is where we directly assert the design from experiments 02/03 — one process
owns one collection, and a single lock serializes concurrent writers safely.
"""

import concurrent.futures

import pytest

from anki_api.collection_handle import CollectionHandle
from anki_api.config import Settings
from anki_api.errors import CollectionUnavailable


def test_opens_with_v3_scheduler(handle: CollectionHandle):
    # Fresh collections default to v3 in modern Anki; the handle ensures it on.
    with handle.locked() as col:
        assert col.v3_scheduler() is True


def test_locked_after_close_raises(handle: CollectionHandle):
    handle.close()
    with pytest.raises(CollectionUnavailable):
        with handle.locked():
            pass


def test_close_is_idempotent(handle: CollectionHandle):
    handle.close()
    handle.close()  # must not raise


def test_second_open_of_same_file_is_blocked(settings: Settings):
    """The backend takes an exclusive lock (experiment 02): a 2nd owner fails."""
    from anki.errors import DBError

    first = CollectionHandle(settings)
    try:
        with pytest.raises(DBError):
            CollectionHandle(settings)
    finally:
        first.close()


def test_concurrent_writers_are_serialized(handle: CollectionHandle):
    """Many threads adding notes through the lock: no loss, no corruption."""
    n_threads, per_thread = 8, 25

    def add_batch(tid: int) -> int:
        added = 0
        for i in range(per_thread):
            with handle.locked() as col:
                nt = col.models.by_name("Basic")
                note = col.new_note(nt)
                note["Front"] = f"t{tid}-{i}"
                note["Back"] = "x"
                col.add_note(note, col.decks.id("Conc"))
                added += 1
        return added

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as ex:
        results = list(ex.map(add_batch, range(n_threads)))

    assert sum(results) == n_threads * per_thread
    with handle.locked() as col:
        assert col.note_count() == n_threads * per_thread
