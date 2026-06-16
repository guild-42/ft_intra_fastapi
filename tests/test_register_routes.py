"""Register / credential routes against the in-memory FakeClient: identity
binding on register, and the IDOR ownership check on DELETE /api/credentials.
The server stores no 42 cookie or token (doc_v2/10) — register only persists
fcm_token + prefs, and credential delete removes the device doc."""
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deps import get_device_repo, get_identity
from repositories.device_repo import DeviceRepository
from tests.conftest import FakeClient


def make_client(identity, fake):
    import api.routes_register as rr

    app = FastAPI()
    app.include_router(rr.router)
    app.dependency_overrides[get_identity] = lambda: identity
    app.dependency_overrides[get_device_repo] = lambda: DeviceRepository(fake)
    return TestClient(app)


def _identity(user_id=42, login="me"):
    identity = AsyncMock()
    identity.verify = AsyncMock(return_value={"id": user_id, "login": login})
    return identity


def test_register_binds_device_to_verified_identity():
    """B-RG01: the device doc gets the token-verified user, not caller input."""
    fake = FakeClient()
    client = make_client(_identity(42, "me"), fake)
    resp = client.post("/api/register", json={
        "fcm_token": "tokA", "access_token": "acc",
    })
    assert resp.status_code == 201
    assert resp.json()["user_id"] == 42
    device = fake.store["devices"]["tokA"]
    assert device["user_id"] == 42
    assert device["login"] == "me"
    # The 42 token is never persisted server-side.
    assert "access_token" not in device
    assert "refresh_token" not in device
    assert "cookies" not in fake.store


def test_register_rejects_invalid_token():
    """B-RG02: identity failure propagates (401), nothing is stored."""
    identity = AsyncMock()
    identity.verify = AsyncMock(
        side_effect=HTTPException(status_code=401, detail="bad token"))
    fake = FakeClient()
    client = make_client(identity, fake)
    resp = client.post("/api/register", json={
        "fcm_token": "tokA", "access_token": "bad",
    })
    assert resp.status_code == 401
    assert "devices" not in fake.store


def test_delete_credential_owner_mismatch_is_404():
    """B-RG03 (IDOR): a valid token of user B cannot delete user A's device,
    and the response must not confirm the device exists."""
    fake = FakeClient()
    fake.store["devices"] = {
        "tokA": {"user_id": 42, "fcm_token": "tokA"},
    }
    client = make_client(_identity(user_id=999, login="attacker"), fake)
    resp = client.request("DELETE", "/api/credentials", json={
        "fcm_token": "tokA", "access_token": "attacker-token",
    })
    assert resp.status_code == 404
    assert "tokA" in fake.store["devices"]


def test_delete_credential_removes_owned_device():
    """B-RG04: the verified owner's device doc is deleted (full server-side
    footprint removal)."""
    fake = FakeClient()
    fake.store["devices"] = {
        "tokA": {"user_id": 42, "fcm_token": "tokA"},
        "tokOther": {"user_id": 7, "fcm_token": "tokOther"},
    }
    client = make_client(_identity(user_id=42), fake)
    resp = client.request("DELETE", "/api/credentials", json={
        "fcm_token": "tokA", "access_token": "acc",
    })
    assert resp.status_code == 200
    assert "tokA" not in fake.store["devices"]
    assert "tokOther" in fake.store["devices"]


def test_preferences_unknown_device_is_404():
    """B-RG05: pref update without prior register is rejected."""
    client = make_client(_identity(), FakeClient())
    resp = client.post("/api/preferences", json={
        "fcm_token": "ghost", "pref_review": True,
    })
    assert resp.status_code == 404
