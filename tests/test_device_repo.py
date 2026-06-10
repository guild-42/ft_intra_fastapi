"""DeviceRepository token-deletion logic against the in-memory FakeClient.

Covers the "delete my token from server" semantics: clearing must wipe the
OAuth token from EVERY device the user owns (a rotated fcm_token leaves an
orphaned doc that otherwise keeps the token + pref_review=True), while leaving
identity (user_id / login) and other-notification prefs intact.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repositories.device_repo import DeviceRepository  # noqa: E402
from tests.conftest import FakeClient  # noqa: E402


def _seed(store, doc_id, **over):
    base = {
        "user_id": 260029,
        "login": "ssekikaw",
        "fcm_token": doc_id,
        "platform": "iOS",
        "pref_evalpo": True,
        "pref_event": True,
        "pref_review": True,
        "pref_friend": True,
        "access_token": "acc",
        "refresh_token": "ref",
        "token_expires_at": "2026-01-01",
    }
    base.update(over)
    store.setdefault("devices", {})[doc_id] = base


def test_clear_user_tokens_wipes_every_device_of_that_user():
    client = FakeClient()
    # Two devices for the same user (e.g. an fcm rotation left a stale doc),
    # plus one device for a different user that must stay untouched.
    _seed(client.store, "fcm_current")
    _seed(client.store, "fcm_stale")
    _seed(client.store, "fcm_other", user_id=999, login="other")

    cleared = asyncio.run(DeviceRepository(client).clear_user_tokens(260029))

    assert cleared == 2
    for doc_id in ("fcm_current", "fcm_stale"):
        d = client.store["devices"][doc_id]
        # token fields gone…
        assert "access_token" not in d
        assert "refresh_token" not in d
        assert "token_expires_at" not in d
        # …review off…
        assert d["pref_review"] is False
        # …but identity + other prefs preserved.
        assert d["user_id"] == 260029
        assert d["login"] == "ssekikaw"
        assert d["pref_evalpo"] is True
        assert d["pref_friend"] is True

    other = client.store["devices"]["fcm_other"]
    assert other["access_token"] == "acc"
    assert other["pref_review"] is True


def test_clear_user_tokens_counts_only_token_bearing_docs():
    client = FakeClient()
    _seed(client.store, "with_token")
    # A device with review off and no token (other-notifications only).
    _seed(client.store, "no_token", pref_review=False)
    del client.store["devices"]["no_token"]["access_token"]
    del client.store["devices"]["no_token"]["refresh_token"]
    del client.store["devices"]["no_token"]["token_expires_at"]

    cleared = asyncio.run(DeviceRepository(client).clear_user_tokens(260029))

    # Both scanned, but only the token-bearing one counts as cleared.
    assert cleared == 1
    assert "access_token" not in client.store["devices"]["with_token"]


def test_delete_by_fcm_removes_device():
    client = FakeClient()
    client.store["devices"] = {
        "tok_dead": {"user_id": 1, "fcm_token": "tok_dead"},
        "tok_live": {"user_id": 2, "fcm_token": "tok_live"},
    }
    asyncio.run(DeviceRepository(client).delete_by_fcm("tok_dead"))
    assert "tok_dead" not in client.store["devices"]
    assert "tok_live" in client.store["devices"]
