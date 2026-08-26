"""Detects review changes server-side so the wake push is event-driven.

Before this, the only mechanism was EvalWakePoller: a content-less silent push
to every pref_review device every 30 minutes, whether or not anything had
happened. That is bad twice over — a booking made right after a wake waits up to
half an hour, and iOS budgets silent pushes per app per day, so spending ~48 of
them daily on blind polls makes the ones that matter *less* likely to land.

This poller asks the PUBLIC API what a user's evaluations look like
(``/v2/users/{id}/scale_teams`` with the app token — no 42 user token, so the
doc_v2/10 rule holds), diffs it, and wakes only that user's devices, only when
something actually changed. Push volume drops by an order of magnitude and
latency drops to the poll interval.

What is stored is a set of opaque signatures (``<scale_team_id>:<state>``) —
never review content, marks, peers or times. The device still fetches the
details itself with its own token, exactly as before.
"""
import logging

from config import REVIEW_POLL_INTERVAL_SECONDS, REVIEW_POLLER_MAX_USERS
from pollers.base import BasePoller

logger = logging.getLogger(__name__)


def _signature(team: dict) -> str | None:
    """Opaque per-review state marker. Includes filled-ness so a review that
    gets graded is a change, not just a new booking."""
    tid = team.get("id")
    if tid is None:
        return None
    return f"{tid}:{'filled' if team.get('filled_at') else 'scheduled'}"


class ReviewPoller(BasePoller):
    name = "review_poller"
    interval_seconds = REVIEW_POLL_INTERVAL_SECONDS

    def __init__(self, device_repo, state_repo, ft_client, push):
        self._devices = device_repo
        self._state = state_repo
        self._ft = ft_client
        self._push = push

    async def poll(self) -> list[dict]:
        return []

    async def diff(self, new_items: list[dict]) -> list[dict]:
        return []

    async def notify(self, changes: list[dict]) -> None:
        return None

    async def _users(self) -> dict[int, list[str]]:
        """pref_review devices grouped by their 42 user id."""
        out: dict[int, list[str]] = {}
        for d in await self._devices.get_for_notification("review"):
            uid, token = d.get("user_id"), d.get("fcm_token")
            if uid is None or not token:
                continue
            out.setdefault(int(uid), []).append(token)
        return out

    async def run(self) -> None:
        logger.info("ReviewPoller: run start")
        try:
            users = await self._users()
            if not users:
                logger.info("ReviewPoller: no pref_review devices")
                await self._state.update(self.name, success=True)
                return

            # 42 allows 2 req/sec; one request per user per tick. Cap the fan-out
            # so a growing user base can't blow the rate limit silently.
            uids = sorted(users)[:REVIEW_POLLER_MAX_USERS]
            if len(users) > len(uids):
                logger.warning(
                    "ReviewPoller: %d users exceed cap %d — %d not polled this "
                    "tick; raise REVIEW_POLLER_MAX_USERS or the interval",
                    len(users), REVIEW_POLLER_MAX_USERS, len(users) - len(uids))

            state = await self._state.get(self.name) or {}
            woken = 0
            for uid in uids:
                teams = await self._ft.get_user_scale_teams(uid)
                if teams is None:
                    continue  # lookup failed: don't diff against nothing

                sigs = {s for s in (_signature(t) for t in teams) if s}
                key = f"seen_{uid}"
                previous = set(state.get(key) or [])

                # First sight of a user seeds the baseline: without this every
                # existing review would fire a notification on first run.
                if previous:
                    fresh = sigs - previous
                    if fresh:
                        logger.info("ReviewPoller: user=%s %d change(s) → waking "
                                    "%d device(s)", uid, len(fresh), len(users[uid]))
                        await self._push.send_silent(
                            users[uid], data={"type": "eval_wake"})
                        woken += 1
                else:
                    logger.info("ReviewPoller: seeding baseline for user=%s "
                                "(%d review(s))", uid, len(sigs))

                # Store bounded + sorted: Firestore documents have a size limit
                # and this grows with every review the user ever has.
                await self._state.save_fields(
                    self.name, **{key: sorted(sigs)[-200:]})

            logger.info("ReviewPoller: run done (%d user(s), %d woken)",
                        len(uids), woken)
            await self._state.update(self.name, success=True)
        except Exception:
            logger.exception("ReviewPoller run error")
            await self._state.update(self.name, success=False)
