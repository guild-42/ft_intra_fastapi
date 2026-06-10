"""Register / credential routes against the in-memory FakeClient: identity
binding on register, and the IDOR ownership check on DELETE /api/credentials
(B-RG01–05)."""
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deps import get_cookie_repo, get_device_repo, get_identity
from repositories.cookie_repo import CookieRepository
from repositories.device_repo import DeviceRepository
from tests.conftest import FakeClient


def make_client(identity, fake):
    import api.routes_register as rr

    app = FastAPI()
    app.include_router(rr.router)
    app.dependency_overrides[get_identity] = lambda: identity
    app.dependency_overrides[get_device_repo] = lambda: DeviceRepository(fake)
    app.dependency_overrides[get_cookie_repo] = lambda: CookieRepository(fake)
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
        "fcm_token": "tokA", "access_token": "acc", "cookie": "session-cookie",
    })
    assert resp.status_code == 201
    assert resp.json()["user_id"] == 42
    device = fake.store["devices"]["tokA"]
    assert device["user_id"] == 42
    assert device["login"] == "me"
    # cookie stored under the verified user
    assert any(
        c.get("user_id") == 42 for c in fake.store.get("cookies", {}).values()
    )


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
    """B-RG03 (IDOR): a valid token of user B cannot delete user A's data,
    and the response must not confirm the device exists."""
    fake = FakeClient()
    fake.store["devices"] = {
        "tokA": {"user_id": 42, "fcm_token": "tokA", "access_token": "x"},
    }
    client = make_client(_identity(user_id=999, login="attacker"), fake)
    resp = client.request("DELETE", "/api/credentials", json={
        "type": "token", "fcm_token": "tokA", "access_token": "attacker-token",
    })
    assert resp.status_code == 404
    assert fake.store["devices"]["tokA"]["access_token"] == "x"


def test_delete_credential_token_clears_all_user_devices():
    """B-RG04: token delete clears every device of the verified user (an
    orphaned doc from a rotated fcm token must not keep the token alive)."""
    fake = FakeClient()
    fake.store["devices"] = {
        "tokA": {"user_id": 42, "fcm_token": "tokA",
                 "access_token": "x", "refresh_token": "r", "pref_review": True},
        "tokOld": {"user_id": 42, "fcm_token": "tokOld",
                   "access_token": "x2", "refresh_token": "r2",
                   "pref_review": True},
        "tokOther": {"user_id": 7, "fcm_token": "tokOther",
                     "access_token": "y", "pref_review": True},
    }
    client = make_client(_identity(user_id=42), fake)
    resp = client.request("DELETE", "/api/credentials", json={
        "type": "token", "fcm_token": "tokA", "access_token": "acc",
    })
    assert resp.status_code == 200
    assert resp.json()["cleared"] == 2
    assert "access_token" not in fake.store["devices"]["tokA"]
    assert "access_token" not in fake.store["devices"]["tokOld"]
    assert fake.store["devices"]["tokOther"]["access_token"] == "y"


def test_preferences_unknown_device_is_404():
    """B-RG05: pref update without prior register is rejected."""
    client = make_client(_identity(), FakeClient())
    resp = client.post("/api/preferences", json={
        "fcm_token": "ghost", "pref_review": True,
    })
    assert resp.status_code == 404
