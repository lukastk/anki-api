import pytest

from anki_api.config import Settings, _env_bool


def test_from_env_requires_collection(monkeypatch):
    monkeypatch.delenv("ANKI_API_COLLECTION", raising=False)
    with pytest.raises(RuntimeError, match="ANKI_API_COLLECTION"):
        Settings.from_env()


def test_from_env_absolutizes_path(monkeypatch):
    monkeypatch.setenv("ANKI_API_COLLECTION", "rel/col.anki2")
    monkeypatch.delenv("ANKI_API_V3_SCHEDULER", raising=False)
    s = Settings.from_env()
    assert s.collection_path.startswith("/")
    assert s.collection_path.endswith("rel/col.anki2")
    assert s.enable_v3_scheduler is True  # default


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("", False), ("nonsense", False),
])
def test_env_bool(monkeypatch, raw, expected):
    monkeypatch.setenv("X", raw)
    assert _env_bool("X", default=True) is expected


def test_env_bool_default_when_unset(monkeypatch):
    monkeypatch.delenv("X", raising=False)
    assert _env_bool("X", default=True) is True
    assert _env_bool("X", default=False) is False
