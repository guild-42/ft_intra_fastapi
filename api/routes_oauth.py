import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

from config import FT_API_CLIENT_ID, FT_API_CLIENT_SECRET, FT_TOKEN_URL

logger = logging.getLogger(__name__)
router = APIRouter()


class ExchangeRequest(BaseModel):
    code: str
    redirect_uri: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/api/oauth/exchange")
async def exchange_code(req: ExchangeRequest):
    logger.info("oauth_exchange: exchanging auth code for redirect_uri=%s",
                req.redirect_uri)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            FT_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": FT_API_CLIENT_ID,
                "client_secret": FT_API_CLIENT_SECRET,
                "code": req.code,
                "redirect_uri": req.redirect_uri,
            },
        )

    if resp.status_code != 200:
        logger.warning("oauth_exchange: 42 OAuth error %d: %s",
                       resp.status_code, resp.text)
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"42 OAuth error: {resp.text}",
        )

    data = resp.json()
    logger.info("oauth_exchange: success scope=%s expires_in=%s",
                data.get("scope"), data.get("expires_in"))
    return {
        "access_token": data["access_token"],
        "token_type": data.get("token_type", "bearer"),
        "expires_in": data.get("expires_in"),
        "refresh_token": data.get("refresh_token"),
        "scope": data.get("scope"),
        "created_at": data.get("created_at"),
    }


@router.post("/api/oauth/refresh")
async def refresh_token(req: RefreshRequest):
    """Exchange a refresh_token for a fresh access token. The 42 app is a
    confidential client, so the refresh grant needs client_secret — which lives
    only on the server. The app calls this instead of hitting 42 directly (it
    has no secret). No token is stored server-side; the new tokens are returned
    to the device (doc_v2/10)."""
    logger.info("oauth_refresh: refreshing access token")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            FT_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": FT_API_CLIENT_ID,
                "client_secret": FT_API_CLIENT_SECRET,
                "refresh_token": req.refresh_token,
            },
        )
    if resp.status_code != 200:
        logger.warning("oauth_refresh: 42 OAuth error %d", resp.status_code)
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"42 OAuth error: {resp.text}",
        )
    data = resp.json()
    logger.info("oauth_refresh: success expires_in=%s", data.get("expires_in"))
    return {
        "access_token": data["access_token"],
        "token_type": data.get("token_type", "bearer"),
        "expires_in": data.get("expires_in"),
        "refresh_token": data.get("refresh_token"),
        "scope": data.get("scope"),
        "created_at": data.get("created_at"),
    }
