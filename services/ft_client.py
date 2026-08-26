"""42 public-data API client (app-level, client_credentials grant).

The token is scoped to ``public`` with no resource owner — enough to read public
data such as campus locations, which the friend poller needs. The app token is
cached in-process until shortly before expiry.

The client_secret comes from FtCredentials rather than config directly: 42
expires it on a schedule, so a rejected secret triggers a promotion of the
staged replacement and one retry instead of failing every poll until someone
notices (see services/ft_credentials.py)."""
import logging
import time

import httpx

from config import FT_API_BASE, FT_TOKEN_URL

logger = logging.getLogger(__name__)


class FtClient:
    def __init__(self, credentials):
        self._credentials = credentials
        self._token: str | None = None
        self._token_expiry: float = 0.0

    async def _request_token(self, secret: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=15) as client:
            return await client.post(
                FT_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._credentials.client_id,
                    "client_secret": secret,
                },
            )

    async def get_app_token(self) -> str | None:
        if self._token and time.time() < self._token_expiry - 60:
            logger.debug("ft_client.get_app_token: using cached app token")
            return self._token
        logger.info("ft_client.get_app_token: requesting new client_credentials token")
        secret = await self._credentials.current()
        resp = await self._request_token(secret)

        # 401 here means the secret itself was rejected (expired/rotated), not a
        # transient error — so try promoting the staged replacement before giving up.
        if resp.status_code == 401:
            logger.warning(
                "ft_client.get_app_token: secret rejected by 42, attempting rotation"
            )
            rotated = await self._credentials.rotate_if_possible()
            if rotated:
                resp = await self._request_token(rotated)

        if resp.status_code != 200:
            logger.error("client_credentials token error %d: %s",
                         resp.status_code, resp.text)
            await self._credentials.record_auth(False, resp.text)
            return None
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 7200))
        logger.info("ft_client.get_app_token: new app token (expires_in=%ss)",
                    data.get("expires_in", 7200))
        await self._credentials.record_auth(True)
        return self._token

    async def get_user(self, login: str) -> dict | None:
        """Resolve a 42 login to its public user record (id + login). Used to
        turn a friend-request target login into a user id. Returns None if the
        login is unknown."""
        token = await self.get_app_token()
        if not token:
            return None
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{FT_API_BASE}/users/{login}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            logger.info("ft_client.get_user: %s -> %d", login, resp.status_code)
            return None
        return resp.json()

    async def get_user_scale_teams(self, user_id: int) -> list[dict] | None:
        """A user's evaluations (both roles) from the PUBLIC API.

        Confirmed to return 200 for an app token (client_credentials, scope
        ``public``) — no 42 user token involved, so this stays inside the
        doc_v2/10 rule that the server never holds one. Lets the server notice a
        newly booked review immediately instead of waking every device blindly on
        a timer.

        Returns None on failure so the caller can tell "nothing new" apart from
        "couldn't look" and avoid diffing against an empty list.
        """
        token = await self.get_app_token()
        if not token:
            logger.warning("ft_client.get_user_scale_teams: no app token")
            return None
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{FT_API_BASE}/users/{user_id}/scale_teams",
                params={"sort": "-updated_at", "page[size]": 40},
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            logger.warning("ft_client.get_user_scale_teams: user=%s -> %d",
                           user_id, resp.status_code)
            return None
        return resp.json()

    async def get_campus_events(self, campus_id: int) -> list[dict]:
        """Upcoming events for a campus (public data, app token). Sorted by most
        recently created so the diff catches newly-announced events. One page of
        100 is plenty for event volume."""
        token = await self.get_app_token()
        if not token:
            logger.warning("ft_client.get_campus_events: no app token, returning []")
            return []
        logger.debug("ft_client.get_campus_events: fetching campus=%d", campus_id)
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{FT_API_BASE}/campus/{campus_id}/events",
                params={"page[size]": 100, "sort": "-created_at"},
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            logger.error("campus events error %d", resp.status_code)
            return []
        events = resp.json()
        logger.debug("ft_client.get_campus_events: campus=%d → %d event(s)",
                     campus_id, len(events))
        return events

    async def get_campus_active_locations(self, campus_id: int) -> list[dict]:
        """Active (currently-logged-in) locations for a campus. Returns the raw
        location dicts; each has a nested ``user`` with ``id`` and ``login``."""
        token = await self.get_app_token()
        if not token:
            logger.warning("ft_client.get_campus_active_locations: no app token, returning []")
            return []
        logger.debug("ft_client.get_campus_active_locations: fetching campus=%d", campus_id)
        out: list[dict] = []
        async with httpx.AsyncClient(timeout=20) as client:
            # Busy campuses exceed one page of 100; follow page[number] until a
            # short page. Capped at 5 pages (500 actives) as a runaway guard.
            for page in range(1, 6):
                resp = await client.get(
                    f"{FT_API_BASE}/campus/{campus_id}/locations",
                    params={
                        "filter[active]": "true",
                        "page[size]": 100,
                        "page[number]": page,
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code != 200:
                    logger.error("campus locations error %d (page %d)",
                                 resp.status_code, page)
                    break
                batch = resp.json()
                out.extend(batch)
                if len(batch) < 100:
                    break
        logger.debug("ft_client.get_campus_active_locations: campus=%d → %d location(s)",
                     campus_id, len(out))
        return out
