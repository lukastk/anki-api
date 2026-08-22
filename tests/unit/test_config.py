import pytest

from anki_api.config import Settings, _env_bool, _env_choice


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


def test_env_choice_default_and_normalisation(monkeypatch):
    monkeypatch.delenv("X", raising=False)
    assert _env_choice("X", default="off", choices=frozenset({"off", "download"})) == "off"
    monkeypatch.setenv("X", "  DOWNLOAD ")
    assert _env_choice("X", default="off", choices=frozenset({"off", "download"})) == "download"


def test_env_choice_rejects_unknown(monkeypatch):
    monkeypatch.setenv("X", "upload")
    with pytest.raises(RuntimeError, match="invalid"):
        _env_choice("X", default="off", choices=frozenset({"off", "download"}))


def test_autosync_full_defaults_off(monkeypatch):
    monkeypatch.setenv("ANKI_API_COLLECTION", "col.anki2")
    monkeypatch.delenv("ANKI_API_AUTOSYNC_FULL", raising=False)
    monkeypatch.delenv("ANKI_API_AUTOSYNC_NOTIFY_CMD", raising=False)
    s = Settings.from_env()
    assert s.autosync_full == "off"          # general-purpose default: unchanged behaviour
    assert s.autosync_notify_cmd is None


def test_autosync_full_download_and_notify_from_env(monkeypatch):
    monkeypatch.setenv("ANKI_API_COLLECTION", "col.anki2")
    monkeypatch.setenv("ANKI_API_AUTOSYNC_FULL", "download")
    monkeypatch.setenv("ANKI_API_AUTOSYNC_NOTIFY_CMD", "/usr/bin/true")
    s = Settings.from_env()
    assert s.autosync_full == "download"
    assert s.autosync_notify_cmd == "/usr/bin/true"


def test_autosync_full_rejects_upload(monkeypatch):
    monkeypatch.setenv("ANKI_API_COLLECTION", "col.anki2")
    monkeypatch.setenv("ANKI_API_AUTOSYNC_FULL", "upload")
    with pytest.raises(RuntimeError, match="invalid"):
        Settings.from_env()
