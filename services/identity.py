"""42 identity verification — the single anti-impersonation boundary.

Previously the `GET /v2/me` bearer check was copy-pasted in routes_checkin
(_verify_token), routes_register (_verify_42_user) and re-derived in the review
poller. It now lives here once, so the 42 API can be mocked at one seam."""
import logging

import httpx
from fastapi import HTTPException

from config import FT_API_BASE

logger = logging.getLogger(__name__)


class IdentityVerifier:
    def __init__(self, base_url: str = FT_API_BASE, timeout: float = 10):
        self._base = base_url
        self._timeout = timeout

    async def verify(self, access_token: str) -> dict:
        """Resolve a verified 42 user from an OAuth access token. Identity comes
        from the token, never from the request body. Raises 401 if the token is
        invalid/expired."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code != 200:
            logger.warning("IdentityVerifier: /me returned %d (token invalid/expired)",
                           resp.status_code)
            raise HTTPException(status_code=401, detail="Invalid 42 access token")
        return resp.json()
