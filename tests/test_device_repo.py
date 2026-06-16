"""DeviceRepository persistence against the in-memory FakeClient.

The server stores NO 42 OAuth token (doc_v2/10): upsert must persist only
fcm_token + prefs + identity, never a token, and delete_by_fcm removes the doc.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repositories.device_repo import DeviceRepository  # noqa: E402
from tests.conftest import FakeClient  # noqa: E402


def test_upsert_never_persists_a_42_token():
    client = FakeClient()
    asyncio.run(DeviceRepository(client).upsert(
        user_id=260029, login="ssekikaw", fcm_token="fcmA",
        pref_review=True, pref_friend=True,
        consent_version="v1", consented_at="2026-06-16T00:00:00Z",
    ))
    doc = client.store["devices"]["fcmA"]
    assert doc["user_id"] == 260029
    assert doc["login"] == "ssekikaw"
    assert doc["pref_review"] is True
    assert doc["consent_version"] == "v1"
    # No 42 secret is ever written to the server.
    assert "access_token" not in doc
    assert "refresh_token" not in doc
    assert "token_expires_at" not in doc


def test_get_for_notification_filters_by_pref():
    client = FakeClient()
    repo = DeviceRepository(client)
    asyncio.run(repo.upsert(user_id=1, login="a", fcm_token="a", pref_review=True))
    asyncio.run(repo.upsert(user_id=2, login="b", fcm_token="b", pref_review=False))
    out = asyncio.run(repo.get_for_notification("review"))
    fcms = {d["fcm_token"] for d in out}
    assert fcms == {"a"}


def test_delete_by_fcm_removes_device():
    client = FakeClient()
    client.store["devices"] = {
        "tok_dead": {"user_id": 1, "fcm_token": "tok_dead"},
        "tok_live": {"user_id": 2, "fcm_token": "tok_live"},
    }
    asyncio.run(DeviceRepository(client).delete_by_fcm("tok_dead"))
    assert "tok_dead" not in client.store["devices"]
    assert "tok_live" in client.store["devices"]
