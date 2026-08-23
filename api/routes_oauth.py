import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import httpx

from config import FT_TOKEN_URL
from deps import get_ft_credentials
from services.ft_credentials import FtCredentials

logger = logging.getLogger(__name__)
router = APIRouter()


class ExchangeRequest(BaseModel):
    code: str
    redirect_uri: str


class RefreshRequest(BaseModel):
    refresh_token: str


async def _token_request(creds: FtCredentials, payload: dict) -> httpx.Response:
    """POST to 42's token endpoint, retrying once through a secret rotation when
    the credential itself is rejected.

    Safe to retry: 42 consumes an authorization_code only on a *successful*
    exchange, so a 401 invalid_client leaves the code usable."""
    secret = await creds.current()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            FT_TOKEN_URL,
            data={**payload, "client_id": creds.client_id, "client_secret": secret},
        )
        if resp.status_code == 401:
            logger.warning("oauth: secret rejected by 42, attempting rotation")
            rotated = await creds.rotate_if_possible()
            if rotated:
                resp = await client.post(
                    FT_TOKEN_URL,
                    data={**payload, "client_id": creds.client_id,
                          "client_secret": rotated},
                )
    await creds.record_auth(resp.status_code == 200,
                            None if resp.status_code == 200 else resp.text)
    return resp


def _tokens(data: dict) -> dict:
    return {
        "access_token": data["access_token"],
        "token_type": data.get("token_type", "bearer"),
        "expires_in": data.get("expires_in"),
        "refresh_token": data.get("refresh_token"),
        "scope": data.get("scope"),
        "created_at": data.get("created_at"),
    }


@router.post("/api/oauth/exchange")
async def exchange_code(req: ExchangeRequest,
                        creds: FtCredentials = Depends(get_ft_credentials)):
    logger.info("oauth_exchange: exchanging auth code for redirect_uri=%s",
                req.redirect_uri)
    resp = await _token_request(creds, {
        "grant_type": "authorization_code",
        "code": req.code,
        "redirect_uri": req.redirect_uri,
    })
    if resp.status_code != 200:
        logger.warning("oauth_exchange: 42 OAuth error %d: %s",
                       resp.status_code, resp.text)
        raise HTTPException(status_code=resp.status_code,
                            detail=f"42 OAuth error: {resp.text}")
    data = resp.json()
    logger.info("oauth_exchange: success scope=%s expires_in=%s",
                data.get("scope"), data.get("expires_in"))
    return _tokens(data)


@router.post("/api/oauth/refresh")
async def refresh_token(req: RefreshRequest,
                        creds: FtCredentials = Depends(get_ft_credentials)):
    """Exchange a refresh_token for a fresh access token. The 42 app is a
    confidential client, so the refresh grant needs client_secret — which lives
    only on the server. The app calls this instead of hitting 42 directly (it
    has no secret). No token is stored server-side; the new tokens are returned
    to the device (doc_v2/10)."""
    logger.info("oauth_refresh: refreshing access token")
    resp = await _token_request(creds, {
        "grant_type": "refresh_token",
        "refresh_token": req.refresh_token,
    })
    if resp.status_code != 200:
        logger.warning("oauth_refresh: 42 OAuth error %d", resp.status_code)
        raise HTTPException(status_code=resp.status_code,
                            detail=f"42 OAuth error: {resp.text}")
    data = resp.json()
    logger.info("oauth_refresh: success expires_in=%s", data.get("expires_in"))
    return _tokens(data)
