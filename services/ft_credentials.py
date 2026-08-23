"""Supplies the 42 client_secret, and rotates it without human help.

42 expires an app's client_secret on a fixed date and pre-generates the
replacement about a week earlier, but exposes neither over the API — there is no
endpoint that returns the current secret, the next one, or the expiry (verified
against /v2/apps, /oauth/token/info and the app detail endpoint). Scraping the
dashboard is out: this project dropped 42 cookie scraping for ToU compliance.

So the switchover is automated from the other end. The replacement secret is
staged ahead of time (one command, or via the expiry warning it emits), and when
the current secret starts failing this service validates the staged one and
promotes it in place. No restart, no redeploy, and no human at the moment of
expiry — which is the part that actually broke twice.

env stays as the bootstrap source so a cold start with an empty Firestore still
works, and so nothing breaks the first time this ships.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from config import FT_API_CLIENT_ID, FT_API_CLIENT_SECRET, FT_TOKEN_URL

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60


class FtCredentials:
    def __init__(self, repo_factory, client_id: str = FT_API_CLIENT_ID,
                 env_secret: str = FT_API_CLIENT_SECRET):
        self._repo_factory = repo_factory
        self._client_id = client_id
        self._env_secret = env_secret
        self._cached: str | None = None
        self._cached_at: float = 0.0
        # Serialises rotation so concurrent 401s don't each try to promote.
        self._lock = asyncio.Lock()

    @property
    def client_id(self) -> str:
        return self._client_id

    def invalidate(self):
        self._cached = None
        self._cached_at = 0.0

    async def current(self) -> str:
        """The secret to authenticate with. Firestore wins; env is the fallback
        for a cold start (and is migrated into Firestore on first use)."""
        if self._cached and (time.time() - self._cached_at) < _CACHE_TTL_SECONDS:
            return self._cached
        secret = None
        try:
            data = await self._repo_factory().get()
            if data and data.get("secret"):
                secret = data["secret"]
        except Exception:
            # A Firestore hiccup must not take auth down while env still works.
            logger.exception("ft_credentials.current: store read failed, using env")
        if not secret:
            secret = self._env_secret
            logger.info("ft_credentials.current: no stored secret, using env value")
            await self._seed_from_env(secret)
        self._cached = secret
        self._cached_at = time.time()
        return secret

    async def _seed_from_env(self, secret: str):
        """First run after deploy: copy env's secret into the store so it can be
        rotated from then on."""
        if not secret:
            return
        try:
            await self._repo_factory().save(client_id=self._client_id, secret=secret)
            logger.info("ft_credentials: seeded stored credential from env")
        except Exception:
            logger.exception("ft_credentials: failed to seed credential store")

    async def validate(self, secret: str) -> bool:
        """Does 42 accept this secret right now? Used before promoting a staged
        secret so a typo can never replace a working one."""
        if not secret:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    FT_TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": secret,
                    },
                )
        except Exception:
            logger.exception("ft_credentials.validate: request failed")
            return False
        return resp.status_code == 200

    async def rotate_if_possible(self) -> str | None:
        """Called after 42 rejects the current secret. Promotes the staged
        replacement if 42 accepts it. Returns the new secret, or None when there
        is nothing valid to switch to (then a human must stage one)."""
        async with self._lock:
            repo = self._repo_factory()
            try:
                data = await repo.get()
            except Exception:
                logger.exception("ft_credentials.rotate: store read failed")
                return None

            staged = (data or {}).get("next_secret")
            if not staged:
                logger.error(
                    "ft_credentials.rotate: current secret rejected and no "
                    "next_secret staged — stage one with rotate-secret.sh"
                )
                return None

            # Another worker may have promoted while we waited on the lock.
            if staged == self._cached:
                return None

            if not await self.validate(staged):
                logger.error(
                    "ft_credentials.rotate: staged next_secret is also rejected "
                    "by 42 — it is stale or wrong; stage the current one"
                )
                return None

            await repo.promote_next()
            self._cached = staged
            self._cached_at = time.time()
            logger.warning(
                "ft_credentials.rotate: promoted staged secret — 42 auth restored "
                "without a restart"
            )
            return staged

    async def record_auth(self, ok: bool, error: str | None = None):
        try:
            await self._repo_factory().record_auth(ok, error)
        except Exception:
            logger.debug("ft_credentials.record_auth: store write failed", exc_info=True)

    async def status(self) -> dict:
        """Credential health for /health: is 42 auth working, and how close is
        the secret to expiring."""
        out = {"auth_ok": None, "last_auth_at": None, "expires_at": None,
               "days_until_expiry": None, "next_secret_staged": False}
        try:
            data = await self._repo_factory().get() or {}
        except Exception:
            logger.debug("ft_credentials.status: store read failed", exc_info=True)
            return out
        out["auth_ok"] = data.get("last_auth_ok")
        last_at = data.get("last_auth_at")
        out["last_auth_at"] = last_at.isoformat() if hasattr(last_at, "isoformat") else last_at
        out["next_secret_staged"] = bool(data.get("next_secret"))
        expires = data.get("secret_expires_at")
        if hasattr(expires, "isoformat"):
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            out["expires_at"] = expires.isoformat()
            out["days_until_expiry"] = (
                expires - datetime.now(timezone.utc)
            ).days
        return out
