"""Keeps the 42 client_secret alive.

Two jobs, both aimed at the failure that took the app down on 2026-06-30 and
2026-08-22: the secret expired and nothing noticed until users reported it.

1. Self-heal — if 42 is rejecting the current secret, promote the staged
   replacement. This is the automatic part: once a replacement is staged, the
   switchover needs nobody.
2. Warn early — a replacement can only be staged by a human (42 exposes no API
   for it), so warn well before expiry, by push and in the logs, while there is
   still time to act.
"""
import logging

from config import ADMIN_USER_IDS, CREDENTIAL_CHECK_INTERVAL_SECONDS, FT_SECRET_WARN_DAYS
from pollers.base import BasePoller

logger = logging.getLogger(__name__)


class CredentialMonitor(BasePoller):
    name = "credential_monitor"
    interval_seconds = CREDENTIAL_CHECK_INTERVAL_SECONDS

    def __init__(self, credentials, state_repo, device_repo_factory=None, push=None):
        self._credentials = credentials
        self._state = state_repo
        self._device_repo_factory = device_repo_factory
        self._push = push

    async def poll(self) -> list[dict]:
        return []

    async def diff(self, new_items: list[dict]) -> list[dict]:
        return []

    async def notify(self, changes: list[dict]) -> None:
        return None

    async def _alert(self, title: str, body: str):
        logger.error("CredentialMonitor ALERT: %s — %s", title, body)
        if not (self._push and self._device_repo_factory and ADMIN_USER_IDS):
            return
        try:
            repo = self._device_repo_factory()
            tokens = []
            for uid in ADMIN_USER_IDS:
                tokens += [d["fcm_token"] for d in await repo.get_all_for_user(uid)
                           if d.get("fcm_token")]
            if tokens:
                await self._push.send(tokens, title, body,
                                      data={"type": "credential_alert"})
        except Exception:
            logger.exception("CredentialMonitor: failed to push alert")

    async def run(self) -> None:
        logger.debug("CredentialMonitor: run start")
        ok = False
        try:
            secret = await self._credentials.current()
            if await self._credentials.validate(secret):
                ok = True
                await self._credentials.record_auth(True)
            else:
                # Don't wait for the next login/poll to discover this.
                logger.warning("CredentialMonitor: current secret rejected, rotating")
                rotated = await self._credentials.rotate_if_possible()
                if rotated:
                    ok = True
                    await self._credentials.record_auth(True)
                    await self._alert(
                        "42 secret rotated",
                        "The 42 client_secret expired and the staged replacement "
                        "was promoted automatically. Stage the next one.",
                    )
                else:
                    await self._credentials.record_auth(False, "secret rejected")
                    await self._alert(
                        "42 auth is DOWN",
                        "The 42 client_secret is rejected and no replacement is "
                        "staged. Login and notifications are broken until a new "
                        "secret is staged (./rotate-secret.sh).",
                    )

            status = await self._credentials.status()
            days = status.get("days_until_expiry")
            if (days is not None and days <= FT_SECRET_WARN_DAYS
                    and not status.get("next_secret_staged")):
                await self._alert(
                    "42 secret expires soon",
                    f"The 42 client_secret expires in {days} day(s) and no "
                    f"replacement is staged. Copy the NEXT SECRET from the 42 "
                    f"dashboard and run ./rotate-secret.sh --next <secret>.",
                )
            await self._state.update(self.name, success=ok)
        except Exception:
            logger.exception("CredentialMonitor: run failed")
            await self._state.update(self.name, success=False)
        logger.debug("CredentialMonitor: run done (ok=%s)", ok)
