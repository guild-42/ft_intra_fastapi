"""Location-based campus check-in.

The app fires these when the user crosses their campus geofence. Identity is
NOT taken from the request body — the access_token is verified against
api.intra.42.fr/v2/me (same anti-impersonation pattern as routes_register),
and the resulting 42 user_id/login is what gets checked in.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

import db
from config import FT_API_BASE, CHECKIN_TTL_SECONDS

router = APIRouter()


class CheckinRequest(BaseModel):
    access_token: str
    campus_id: int


class HeartbeatRequest(BaseModel):
    access_token: str


async def _verify_token(access_token: str) -> dict:
    """Resolve a verified 42 user from an OAuth access token. Raises 401 if the
    token is invalid/expired."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{FT_API_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid 42 access token")
    return resp.json()


@router.post("/api/checkin", status_code=201)
async def checkin(req: CheckinRequest):
    user = await _verify_token(req.access_token)
    await db.upsert_checkin(
        user_id=user["id"],
        login=user["login"],
        campus_id=req.campus_id,
        source="geo",
        ttl_seconds=CHECKIN_TTL_SECONDS,
    )
    return {
        "status": "checked_in",
        "user_id": user["id"],
        "login": user["login"],
        "campus_id": req.campus_id,
    }


@router.post("/api/checkout")
async def checkout(req: CheckinRequest):
    user = await _verify_token(req.access_token)
    await db.set_checkout(user["id"], reason="manual")
    return {"status": "checked_out", "user_id": user["id"]}


@router.post("/api/checkin/heartbeat")
async def heartbeat(req: HeartbeatRequest):
    user = await _verify_token(req.access_token)
    ok = await db.heartbeat_checkin(user["id"], ttl_seconds=CHECKIN_TTL_SECONDS)
    return {"status": "ok" if ok else "not_checked_in", "user_id": user["id"]}


@router.get("/api/checkins")
async def list_checkins(campus_id: int | None = None):
    rows = await db.list_active_checkins(campus_id=campus_id)
    return {
        "campus_id": campus_id,
        "count": len(rows),
        "checkins": [
            {
                "user_id": r.get("user_id"),
                "login": r.get("login"),
                "campus_id": r.get("campus_id"),
                "source": r.get("source"),
                "checked_in_at": (
                    r["checked_in_at"].isoformat()
                    if r.get("checked_in_at") is not None
                    else None
                ),
            }
            for r in rows
        ],
    }
