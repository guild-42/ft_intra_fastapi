"""Tests for location-based check-in (DESIGN.md B-CK01..B-CK06).

Route-level tests use a FastAPI TestClient with the 42 token verification and DB
calls mocked. DB-level tests exercise the real db.py logic against the in-memory
FakeClient from conftest (idempotency, active-only listing, expiry sweep).
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import api.routes_checkin as rc  # noqa: E402
from tests.conftest import FakeClient  # noqa: E402


def make_client():
    app = FastAPI()
    app.include_router(rc.router)
    return TestClient(app)


# ───── route-level (mocked) ─────


def test_checkin_verifies_token_and_upserts(monkeypatch):
    """B-CK01: valid token → 201 + upsert with the verified identity."""
    monkeypatch.setattr(
        rc, "_verify_token",
        AsyncMock(return_value={"id": 42, "login": "ssekikaw"}),
    )
    upsert = AsyncMock(return_value={})
    monkeypatch.setattr(db, "upsert_checkin", upsert)

    resp = make_client().post(
        "/api/checkin", json={"access_token": "tok", "campus_id": 26}
    )

    assert resp.status_code == 201
    assert resp.json() == {
        "status": "checked_in", "user_id": 42, "login": "ssekikaw", "campus_id": 26,
    }
    # The login written is the verified one, NOT anything from the request body.
    assert upsert.await_args.kwargs["user_id"] == 42
    assert upsert.await_args.kwargs["login"] == "ssekikaw"
    assert upsert.await_args.kwargs["campus_id"] == 26


def test_checkin_rejects_invalid_token(monkeypatch):
    """B-CK02: bad token → 401, no DB write."""
    monkeypatch.setattr(
        rc, "_verify_token",
        AsyncMock(side_effect=HTTPException(status_code=401, detail="bad")),
    )
    upsert = AsyncMock()
    monkeypatch.setattr(db, "upsert_checkin", upsert)

    resp = make_client().post(
        "/api/checkin", json={"access_token": "bad", "campus_id": 26}
    )

    assert resp.status_code == 401
    upsert.assert_not_awaited()


def test_checkout_route(monkeypatch):
    """B-CK04 (route): checkout verifies token then closes the check-in."""
    monkeypatch.setattr(
        rc, "_verify_token", AsyncMock(return_value={"id": 7, "login": "u"})
    )
    set_checkout = AsyncMock(return_value=True)
    monkeypatch.setattr(db, "set_checkout", set_checkout)

    resp = make_client().post(
        "/api/checkout", json={"access_token": "tok", "campus_id": 26}
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "checked_out"
    assert set_checkout.await_args.args[0] == 7


def test_list_checkins_route(monkeypatch):
    """B-CK05 (route): list returns the shaped active check-ins."""
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        db, "list_active_checkins",
        AsyncMock(return_value=[
            {"user_id": 1, "login": "a", "campus_id": 26,
             "source": "geo", "checked_in_at": now},
        ]),
    )

    resp = make_client().get("/api/checkins?campus_id=26")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["checkins"][0]["login"] == "a"
    assert body["checkins"][0]["checked_in_at"] is not None


# ───── db-level (FakeClient) ─────


def _use_fake_db(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(db, "get_client", lambda: fake)
    return fake


def test_checkin_is_idempotent(monkeypatch):
    """B-CK03: checking in twice keeps one doc and preserves checked_in_at."""
    _use_fake_db(monkeypatch)

    async def scenario():
        first = await db.upsert_checkin(42, "ssekikaw", 26, ttl_seconds=3600)
        await asyncio.sleep(0)
        await db.upsert_checkin(42, "ssekikaw", 26, ttl_seconds=3600)
        rows = await db.list_active_checkins(campus_id=26)
        return first, rows

    first, rows = asyncio.run(scenario())
    assert len(rows) == 1
    # Original check-in time survives the second (idempotent) check-in. The
    # second upsert refreshes only heartbeat/expiry (its return value omits
    # checked_in_at by design), but the stored doc keeps the first timestamp.
    assert rows[0]["checked_in_at"] == first["checked_in_at"]


def test_list_active_excludes_inactive_and_expired(monkeypatch):
    """B-CK05: only fresh, active check-ins are listed."""
    _use_fake_db(monkeypatch)

    async def scenario():
        await db.upsert_checkin(1, "active", 26, ttl_seconds=3600)
        await db.upsert_checkin(2, "leaving", 26, ttl_seconds=3600)
        await db.set_checkout(2)  # inactive
        # An active-but-expired row (sweeper hasn't run yet).
        await db.upsert_checkin(3, "stale", 26, ttl_seconds=3600)
        client = db.get_client()
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        client.store["checkins"]["3"]["expires_at"] = past
        return await db.list_active_checkins(campus_id=26)

    rows = asyncio.run(scenario())
    logins = {r["login"] for r in rows}
    assert logins == {"active"}


def test_sweeper_expires_stale_checkins(monkeypatch):
    """B-CK06: expire_stale_checkins closes only past-expiry active rows."""
    _use_fake_db(monkeypatch)

    async def scenario():
        await db.upsert_checkin(1, "fresh", 26, ttl_seconds=3600)
        await db.upsert_checkin(2, "stale", 26, ttl_seconds=3600)
        client = db.get_client()
        client.store["checkins"]["2"]["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        expired = await db.expire_stale_checkins()
        remaining = await db.list_active_checkins()
        return expired, remaining

    expired, remaining = asyncio.run(scenario())
    assert expired == 1
    assert {r["login"] for r in remaining} == {"fresh"}
