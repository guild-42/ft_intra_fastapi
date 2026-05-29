from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
import db
from config import FT_API_BASE

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


@router.post("/api/register", status_code=201)
async def register_device(req: RegisterRequest):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{FT_API_BASE}/me",
            headers={"Authorization": f"Bearer {req.access_token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid 42 access token")

    user_data = resp.json()
    user_id = user_data["id"]
    login = user_data["login"]

    await db.upsert_device(
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
    )

    if req.cookie:
        await db.store_cookie(user_id=user_id, login=login, cookie=req.cookie)

    return {"status": "registered", "user_id": user_id, "login": login}


@router.post("/api/preferences")
async def update_preferences(req: PreferencesRequest):
    updated = await db.update_device_prefs(
        req.fcm_token,
        pref_evalpo=req.pref_evalpo,
        pref_event=req.pref_event,
        pref_review=req.pref_review,
        pref_friend=req.pref_friend,
        friend_watch_ids=req.friend_watch_ids,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Unknown device (register first)")
    return {"status": "updated"}


@router.post("/api/cookie", status_code=201)
async def register_cookie(req: CookieOnlyRequest):
    await db.store_cookie(user_id=req.user_id, login=req.login, cookie=req.cookie)
    return {"status": "cookie_stored"}
