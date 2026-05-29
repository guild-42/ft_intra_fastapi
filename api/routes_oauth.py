import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

router = APIRouter()

CLIENT_ID = os.getenv("FT_API_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("FT_API_CLIENT_SECRET", "")
TOKEN_URL = "https://api.intra.42.fr/oauth/token"


class ExchangeRequest(BaseModel):
    code: str
    redirect_uri: str


@router.post("/api/oauth/exchange")
async def exchange_code(req: ExchangeRequest):
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": req.code,
                "redirect_uri": req.redirect_uri,
            },
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"42 OAuth error: {resp.text}",
        )

    data = resp.json()
    return {
        "access_token": data["access_token"],
        "token_type": data.get("token_type", "bearer"),
        "expires_in": data.get("expires_in"),
        "refresh_token": data.get("refresh_token"),
        "scope": data.get("scope"),
        "created_at": data.get("created_at"),
    }
