"""Auto-checkout safety net.

The app checks users out on geofence exit, but that event can be missed (app
killed, GPS off, network gap). This sweeper closes any check-in whose expiry has
passed, so the Campus tab never shows stale presence.
"""
import logging

from config import CHECKOUT_SWEEP_INTERVAL_SECONDS
from pollers.base import BasePoller

logger = logging.getLogger(__name__)


class CheckoutSweeper(BasePoller):
    name = "checkout_sweeper"
    interval_seconds = CHECKOUT_SWEEP_INTERVAL_SECONDS

    def __init__(self, checkin_repo, state_repo):
        self._checkins = checkin_repo
        self._state = state_repo

    # This poller doesn't fetch/diff/notify — it just expires stale rows. The
    # abstract methods are satisfied with no-ops and run() is overridden.
    async def poll(self) -> list[dict]:
        return []

    async def diff(self, new_items: list[dict]) -> list[dict]:
        return []

    async def notify(self, changes: list[dict]) -> None:
        return None

    async def run(self) -> None:
        logger.debug("CheckoutSweeper: run start")
        try:
            expired = await self._checkins.expire_stale()
            if expired:
                logger.info("CheckoutSweeper auto-checked-out %d stale check-ins", expired)
            await self._state.update(self.name, success=True)
            logger.debug("CheckoutSweeper: run done")
        except Exception:
            logger.exception("CheckoutSweeper error")
            await self._state.update(self.name, success=False)
