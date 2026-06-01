"""Location-based campus check-in.

The app fires these when the user crosses their campus geofence. Identity is
NOT taken from the request body — the access_token is verified against
api.intra.42.fr/v2/me (IdentityVerifier), and the resulting 42 user_id/login is
what gets checked in.
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config import CHECKIN_TTL_SECONDS
from deps import get_checkin_repo, get_identity
from repositories.checkin_repo import CheckinRepository
from services.identity import IdentityVerifier

logger = logging.getLogger(__name__)
router = APIRouter()


class CheckinRequest(BaseModel):
    access_token: str
    campus_id: int


class HeartbeatRequest(BaseModel):
    access_token: str


@router.post("/api/checkin", status_code=201)
async def checkin(
    req: CheckinRequest,
    identity: IdentityVerifier = Depends(get_identity),
    repo: CheckinRepository = Depends(get_checkin_repo),
):
    logger.info("checkin: campus_id=%s (verifying token)", req.campus_id)
    user = await identity.verify(req.access_token)
    await repo.upsert(
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
async def checkout(
    req: CheckinRequest,
    identity: IdentityVerifier = Depends(get_identity),
    repo: CheckinRepository = Depends(get_checkin_repo),
):
    logger.info("checkout: (verifying token)")
    user = await identity.verify(req.access_token)
    await repo.set_checkout(user["id"], reason="manual")
    return {"status": "checked_out", "user_id": user["id"]}


@router.post("/api/checkin/heartbeat")
async def heartbeat(
    req: HeartbeatRequest,
    identity: IdentityVerifier = Depends(get_identity),
    repo: CheckinRepository = Depends(get_checkin_repo),
):
    user = await identity.verify(req.access_token)
    ok = await repo.heartbeat(user["id"], ttl_seconds=CHECKIN_TTL_SECONDS)
    logger.info("heartbeat: user_id=%s active=%s", user["id"], ok)
    return {"status": "ok" if ok else "not_checked_in", "user_id": user["id"]}


@router.get("/api/checkins")
async def list_checkins(
    campus_id: int | None = None,
    repo: CheckinRepository = Depends(get_checkin_repo),
):
    logger.info("list_checkins: campus_id=%s", campus_id)
    rows = await repo.list_active(campus_id=campus_id)
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
