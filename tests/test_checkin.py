"""Tests for location-based check-in (DESIGN.md B-CK01..B-CK06).

Route-level tests use a FastAPI TestClient with the identity verifier and the
checkin repository overridden via dependency_overrides. Repository-level tests
exercise the real CheckinRepository logic against the in-memory FakeClient from
conftest (idempotency, active-only listing, expiry sweep)."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api.routes_checkin as rc  # noqa: E402
from deps import get_checkin_repo, get_identity  # noqa: E402
from repositories.checkin_repo import CheckinRepository  # noqa: E402
from tests.conftest import FakeClient  # noqa: E402


def make_client(identity=None, repo=None):
    app = FastAPI()
    app.include_router(rc.router)
    if identity is not None:
        app.dependency_overrides[get_identity] = lambda: identity
    if repo is not None:
        app.dependency_overrides[get_checkin_repo] = lambda: repo
    return TestClient(app)


# ───── route-level (overridden deps) ─────


def test_checkin_verifies_token_and_upserts():
    """B-CK01: valid token → 201 + upsert with the verified identity."""
    identity = AsyncMock()
    identity.verify = AsyncMock(return_value={"id": 42, "login": "ssekikaw"})
    repo = AsyncMock(spec=CheckinRepository)
    repo.upsert = AsyncMock(return_value={})

    resp = make_client(identity, repo).post(
        "/api/checkin", json={"access_token": "tok", "campus_id": 26}
    )

    assert resp.status_code == 201
    assert resp.json() == {
        "status": "checked_in", "user_id": 42, "login": "ssekikaw", "campus_id": 26,
    }
    # The login written is the verified one, NOT anything from the request body.
    assert repo.upsert.await_args.kwargs["user_id"] == 42
    assert repo.upsert.await_args.kwargs["login"] == "ssekikaw"
    assert repo.upsert.await_args.kwargs["campus_id"] == 26


def test_checkin_rejects_invalid_token():
    """B-CK02: bad token → 401, no DB write."""
    identity = AsyncMock()
    identity.verify = AsyncMock(side_effect=HTTPException(status_code=401, detail="bad"))
    repo = AsyncMock(spec=CheckinRepository)
    repo.upsert = AsyncMock()

    resp = make_client(identity, repo).post(
        "/api/checkin", json={"access_token": "bad", "campus_id": 26}
    )

    assert resp.status_code == 401
    repo.upsert.assert_not_awaited()


def test_checkout_route():
    """B-CK04 (route): checkout verifies token then closes the check-in."""
    identity = AsyncMock()
    identity.verify = AsyncMock(return_value={"id": 7, "login": "u"})
    repo = AsyncMock(spec=CheckinRepository)
    repo.set_checkout = AsyncMock(return_value=True)

    resp = make_client(identity, repo).post(
        "/api/checkout", json={"access_token": "tok", "campus_id": 26}
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "checked_out"
    assert repo.set_checkout.await_args.args[0] == 7


def test_list_checkins_route():
    """B-CK05 (route): list returns the shaped active check-ins."""
    now = datetime.now(timezone.utc)
    repo = AsyncMock(spec=CheckinRepository)
    repo.list_active = AsyncMock(return_value=[
        {"user_id": 1, "login": "a", "campus_id": 26,
         "source": "geo", "checked_in_at": now},
    ])

    resp = make_client(repo=repo).get("/api/checkins?campus_id=26")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["checkins"][0]["login"] == "a"
    assert body["checkins"][0]["checked_in_at"] is not None


# ───── repository-level (FakeClient) ─────


def test_checkin_is_idempotent():
    """B-CK03: checking in twice keeps one doc and preserves checked_in_at."""
    repo = CheckinRepository(FakeClient())

    async def scenario():
        first = await repo.upsert(42, "ssekikaw", 26, ttl_seconds=3600)
        await asyncio.sleep(0)
        await repo.upsert(42, "ssekikaw", 26, ttl_seconds=3600)
        rows = await repo.list_active(campus_id=26)
        return first, rows

    first, rows = asyncio.run(scenario())
    assert len(rows) == 1
    # Original check-in time survives the second (idempotent) check-in. The
    # second upsert refreshes only heartbeat/expiry (its return value omits
    # checked_in_at by design), but the stored doc keeps the first timestamp.
    assert rows[0]["checked_in_at"] == first["checked_in_at"]


def test_list_active_excludes_inactive_and_expired():
    """B-CK05: only fresh, active check-ins are listed."""
    fake = FakeClient()
    repo = CheckinRepository(fake)

    async def scenario():
        await repo.upsert(1, "active", 26, ttl_seconds=3600)
        await repo.upsert(2, "leaving", 26, ttl_seconds=3600)
        await repo.set_checkout(2)  # inactive
        # An active-but-expired row (sweeper hasn't run yet).
        await repo.upsert(3, "stale", 26, ttl_seconds=3600)
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        fake.store["checkins"]["3"]["expires_at"] = past
        return await repo.list_active(campus_id=26)

    rows = asyncio.run(scenario())
    logins = {r["login"] for r in rows}
    assert logins == {"active"}


def test_sweeper_expires_stale_checkins():
    """B-CK06: expire_stale closes only past-expiry active rows."""
    fake = FakeClient()
    repo = CheckinRepository(fake)

    async def scenario():
        await repo.upsert(1, "fresh", 26, ttl_seconds=3600)
        await repo.upsert(2, "stale", 26, ttl_seconds=3600)
        fake.store["checkins"]["2"]["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        expired = await repo.expire_stale()
        remaining = await repo.list_active()
        return expired, remaining

    expired, remaining = asyncio.run(scenario())
    assert expired == 1
    assert {r["login"] for r in remaining} == {"fresh"}
