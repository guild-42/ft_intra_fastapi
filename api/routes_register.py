import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import get_cookie_repo, get_device_repo, get_identity
from repositories.base import fcm_short
from repositories.cookie_repo import CookieRepository
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
    access_token: str
    cookie: str | None = None
    # Only sent on the review opt-in path; presence triggers token storage.
    refresh_token: str | None = None
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


class CookieOnlyRequest(BaseModel):
    cookie: str
    login: str = "admin"
    user_id: int = 0


class DeleteCredentialRequest(BaseModel):
    type: str  # 'cookie' or 'token'
    fcm_token: str
    # Proves the caller owns the device whose credential is being deleted.
    access_token: str


@router.post("/api/register", status_code=201)
async def register_device(
    req: RegisterRequest,
    identity: IdentityVerifier = Depends(get_identity),
    devices: DeviceRepository = Depends(get_device_repo),
    cookies: CookieRepository = Depends(get_cookie_repo),
):
    logger.info("register_device: verifying 42 token, has_cookie=%s has_refresh=%s",
                req.cookie is not None, req.refresh_token is not None)
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
        access_token=req.access_token,
        refresh_token=req.refresh_token,
        consent_version=req.consent_version,
        consented_at=req.consented_at,
    )

    if req.cookie:
        await cookies.store(user_id=user_id, login=login, cookie=req.cookie)

    logger.info("register_device: done user_id=%s login=%s", user_id, login)
    return {"status": "registered", "user_id": user_id, "login": login}


@router.delete("/api/credentials")
async def delete_credential(
    req: DeleteCredentialRequest,
    identity: IdentityVerifier = Depends(get_identity),
    devices: DeviceRepository = Depends(get_device_repo),
    cookies: CookieRepository = Depends(get_cookie_repo),
):
    """Delete a stored credential. The caller must prove ownership by supplying a
    valid 42 access_token: the verified 42 user_id must match the device doc's
    owner, otherwise an attacker who merely knows an fcm_token could wipe another
    user's stored cookie / OAuth token (IDOR). Cookies are deleted for that user;
    the OAuth token is cleared on the device.
    """
    user = await identity.verify(req.access_token)
    logger.info("delete_credential: type=%s fcm=%s user_id=%s",
                req.type, fcm_short(req.fcm_token), user["id"])
    device = await devices.get_by_fcm(req.fcm_token)
    # Owner mismatch is reported as 404 (not 403) so the endpoint never confirms
    # that someone else's fcm_token exists.
    if not device or device.get("user_id") != user["id"]:
        logger.warning(
            "delete_credential: device unknown or owner mismatch "
            "(device_user=%s token_user=%s)",
            device.get("user_id") if device else None, user["id"],
        )
        raise HTTPException(status_code=404, detail="Unknown device")
    if req.type == "cookie":
        removed = await cookies.delete_user(device["user_id"])
        return {"status": "deleted", "type": "cookie", "removed": removed}
    if req.type == "token":
        # Clear the token from ALL of this verified user's devices, not just the
        # calling fcm: a rotated fcm leaves an orphaned doc that still holds the
        # token (and pref_review=True), so a single-device clear looks like the
        # delete failed and lets the poller keep using the stale token.
        cleared = await devices.clear_user_tokens(user["id"])
        return {"status": "deleted", "type": "token", "cleared": cleared}
    logger.warning("delete_credential: bad type=%r", req.type)
    raise HTTPException(status_code=400, detail="type must be 'cookie' or 'token'")


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


@router.post("/api/cookie", status_code=201)
async def register_cookie(
    req: CookieOnlyRequest,
    cookies: CookieRepository = Depends(get_cookie_repo),
):
    logger.info("register_cookie: user_id=%s login=%s", req.user_id, req.login)
    await cookies.store(user_id=req.user_id, login=req.login, cookie=req.cookie)
    return {"status": "cookie_stored"}
