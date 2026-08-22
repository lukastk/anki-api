"""Unit coverage for the autosync full-sync policy decision (no I/O)."""

import pytest

from anki_api.routers.sync import _autosync_full_action


@pytest.mark.parametrize("required", ["full_sync", "full_download", "full_upload"])
def test_policy_off_never_resolves(required):
    """The general-purpose default leaves every required full sync for a manual call."""
    assert _autosync_full_action(required, schema_changed=False, policy="off") == "blocked"
    assert _autosync_full_action(required, schema_changed=True, policy="off") == "blocked"


@pytest.mark.parametrize("required", ["full_download", "full_sync"])
def test_policy_download_adopts_server_when_no_local_schema_change(required):
    """Server is ahead and we hold no un-synced schema change -> safe to download."""
    assert _autosync_full_action(required, schema_changed=False, policy="download") == "download"


def test_policy_download_blocks_on_local_schema_change():
    """A local (incl. never-synced) schema change must not be silently discarded."""
    assert _autosync_full_action("full_download", schema_changed=True, policy="download") == "blocked"
    assert _autosync_full_action("full_sync", schema_changed=True, policy="download") == "blocked"


def test_policy_download_never_auto_uploads():
    """full_upload means THIS side is ahead; downloading would drop it — leave it manual."""
    assert _autosync_full_action("full_upload", schema_changed=False, policy="download") == "blocked"
    assert _autosync_full_action("full_upload", schema_changed=True, policy="download") == "blocked"
