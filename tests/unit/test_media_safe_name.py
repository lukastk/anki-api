import pytest
from fastapi import HTTPException

from anki_api.routers.media import _safe_name


def test_accepts_plain_filename():
    assert _safe_name("image.png") == "image.png"


@pytest.mark.parametrize("bad", ["", "..", ".", "a/b", "..\\..\\x", "dir/file.png"])
def test_rejects_unsafe_names(bad):
    with pytest.raises(HTTPException) as exc:
        _safe_name(bad)
    assert exc.value.status_code == 400
