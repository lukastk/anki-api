import pytest
from fastapi import HTTPException

from anki_api.ids import parse_id, parse_ids, to_id


def test_parse_id_valid():
    assert parse_id("1781013713142") == 1781013713142


def test_parse_id_preserves_large_ints_beyond_js_safe():
    big = 9007199254740993  # > Number.MAX_SAFE_INTEGER
    assert parse_id(str(big)) == big


@pytest.mark.parametrize("bad", ["", "abc", "1.5", "0x10", "  ", None])
def test_parse_id_invalid_raises_400(bad):
    with pytest.raises(HTTPException) as exc:
        parse_id(bad)  # type: ignore[arg-type]
    assert exc.value.status_code == 400


def test_parse_ids_roundtrip():
    assert parse_ids(["1", "2", "3"]) == [1, 2, 3]


def test_parse_ids_propagates_invalid():
    with pytest.raises(HTTPException):
        parse_ids(["1", "nope"])


def test_to_id_is_string():
    assert to_id(42) == "42"
    assert isinstance(to_id(42), str)
