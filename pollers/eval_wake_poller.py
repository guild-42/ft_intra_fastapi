"""Eval "alarm clock" poller.

The server intentionally does NOT hold any 42 user token (doc_v2/10 decision).
To still surface evaluation updates, it periodically sends a content-less silent
push to every device that opted into review notifications (``pref_review``).
On receipt the app wakes, calls ``/me/scale_teams`` + ``/me/feedbacks`` with the
token stored locally on the device, diffs against its local store, and posts a
local notification for anything new.

The server therefore transmits only a wake signal — never 42 data or a token.
iOS throttles silent push, so this is best-effort / non-realtime (accepted).
"""
import logging

from pollers.base import BasePoller

logger = logging.getLogger(__name__)


class EvalWakePoller(BasePoller):
    name = "eval_wake_poller"
    interval_seconds = 1800

    def __init__(self, device_repo, state_repo, push):
        self._devices = device_repo
        self._state = state_repo
        self._push = push

    async def poll(self) -> list[dict]:
        return []

    async def diff(self, new_items: list[dict]) -> list[dict]:
        return []

    async def notify(self, changes: list[dict]) -> None:
        return None

    async def run(self) -> None:
        logger.info("EvalWakePoller: run start")
        try:
            devices = await self._devices.get_for_notification("review")
            tokens = [d["fcm_token"] for d in devices]
            if tokens:
                logger.info("EvalWakePoller: waking %d pref_review device(s)", len(tokens))
                await self._push.send_silent(tokens, data={"type": "eval_wake"})
            else:
                logger.info("EvalWakePoller: no pref_review devices")
            await self._state.update(self.name, success=True)
            logger.info("EvalWakePoller: run done")
        except Exception:
            logger.exception("EvalWakePoller run error")
            await self._state.update(self.name, success=False)
