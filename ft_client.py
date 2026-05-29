"""Minimal 42 API client for the backend's own (app-level) requests.

Uses the ``client_credentials`` grant — a token scoped to ``public`` with no
resource owner. That is enough to read public data such as campus locations,
which the friend poller needs. Tokens are cached in-process until shortly
before expiry.
"""
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

CLIENT_ID = os.getenv("FT_API_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("FT_API_CLIENT_SECRET", "")
TOKEN_URL = "https://api.intra.42.fr/oauth/token"
FT_API_BASE = "https://api.intra.42.fr/v2"

_token: str | None = None
_token_expiry: float = 0.0


async def get_app_token() -> str | None:
    global _token, _token_expiry
    if _token and time.time() < _token_expiry - 60:
        return _token
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
    if resp.status_code != 200:
        logger.error("client_credentials token error %d: %s",
                     resp.status_code, resp.text)
        return None
    data = resp.json()
    _token = data["access_token"]
    _token_expiry = time.time() + int(data.get("expires_in", 7200))
    return _token


async def get_campus_active_locations(campus_id: int) -> list[dict]:
    """Active (currently-logged-in) locations for a campus. Returns the raw
    location dicts; each has a nested ``user`` with ``id`` and ``login``."""
    token = await get_app_token()
    if not token:
        return []
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as client:
        # Single page of 100 is plenty for active users at one campus.
        resp = await client.get(
            f"{FT_API_BASE}/campus/{campus_id}/locations",
            params={"filter[active]": "true", "page[size]": 100},
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            logger.error("campus locations error %d", resp.status_code)
            return []
        out = resp.json()
    return out
