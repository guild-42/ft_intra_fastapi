import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import get_device_repo, get_identity
from repositories.base import fcm_short
from repositories.device_repo import DeviceRepository
from services.identity import IdentityVerifier

logger = logging.getLogger(__name__)
router = APIRouter()


class RegisterRequest(BaseModel):
    fcm_token: str
    platform: str = "ios"
    language: str = "en"
    pref_evalpo: bool = True
    pref_event: bool = True
    pref_review: bool = True
    pref_friend: bool = True
    friend_watch_ids: list[int] = []
    # Used only to verify identity (GET /v2/me); never stored — the 42 token
    # lives on the device, not the server (doc_v2/10).
    access_token: str
    # Terms-of-use consent the user agreed to (audit record).
    consent_version: str | None = None
    consented_at: str | None = None


class PreferencesRequest(BaseModel):
    """Lightweight preference update (no 42 token check). Only provided
    fields are written; omit a field to keep its current value."""
    fcm_token: str
    pref_evalpo: bool | None = None
    pref_event: bool | None = None
    pref_review: bool | None = None
    pref_friend: bool | None = None
    friend_watch_ids: list[int] | None = None


class DeleteDeviceRequest(BaseModel):
    fcm_token: str
    # Proves the caller owns the device being deleted.
    access_token: str


@router.post("/api/register", status_code=201)
async def register_device(
    req: RegisterRequest,
    identity: IdentityVerifier = Depends(get_identity),
    devices: DeviceRepository = Depends(get_device_repo),
):
    logger.info("register_device: verifying 42 token")
    user_data = await identity.verify(req.access_token)
    user_id = user_data["id"]
    login = user_data["login"]
    logger.info("register_device: verified user_id=%s login=%s", user_id, login)

    await devices.upsert(
        user_id=user_id,
        login=login,
        fcm_token=req.fcm_token,
        platform=req.platform,
        language=req.language,
        pref_evalpo=req.pref_evalpo,
        pref_event=req.pref_event,
        pref_review=req.pref_review,
        pref_friend=req.pref_friend,
        friend_watch_ids=req.friend_watch_ids,
        consent_version=req.consent_version,
        consented_at=req.consented_at,
    )

    logger.info("register_device: done user_id=%s login=%s", user_id, login)
    return {"status": "registered", "user_id": user_id, "login": login}


@router.delete("/api/credentials")
async def delete_credential(
    req: DeleteDeviceRequest,
    identity: IdentityVerifier = Depends(get_identity),
    devices: DeviceRepository = Depends(get_device_repo),
):
    """Delete the caller's server-side data: the device registration (fcm_token +
    prefs). The server holds no 42 cookie or token anymore, so removing the device
    doc is the entire server-side footprint. The caller proves ownership with a
    valid 42 access_token; an owner mismatch is reported as 404 (not 403) so the
    endpoint never confirms that someone else's fcm_token exists (IDOR guard)."""
    user = await identity.verify(req.access_token)
    logger.info("delete_credential: fcm=%s user_id=%s",
                fcm_short(req.fcm_token), user["id"])
    device = await devices.get_by_fcm(req.fcm_token)
    if not device or device.get("user_id") != user["id"]:
        logger.warning(
            "delete_credential: device unknown or owner mismatch "
            "(device_user=%s token_user=%s)",
            device.get("user_id") if device else None, user["id"],
        )
        raise HTTPException(status_code=404, detail="Unknown device")
    await devices.delete_by_fcm(req.fcm_token)
    return {"status": "deleted", "fcm": fcm_short(req.fcm_token)}


@router.post("/api/preferences")
async def update_preferences(
    req: PreferencesRequest,
    devices: DeviceRepository = Depends(get_device_repo),
):
    logger.info("update_preferences: fcm=%s", fcm_short(req.fcm_token))
    updated = await devices.update_prefs(
        req.fcm_token,
        pref_evalpo=req.pref_evalpo,
        pref_event=req.pref_event,
        pref_review=req.pref_review,
        pref_friend=req.pref_friend,
        friend_watch_ids=req.friend_watch_ids,
    )
    if not updated:
        logger.warning("update_preferences: unknown device fcm=%s", fcm_short(req.fcm_token))
        raise HTTPException(status_code=404, detail="Unknown device (register first)")
    return {"status": "updated"}
