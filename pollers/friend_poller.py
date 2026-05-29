"""Friend login push poller.

Polls a campus's active locations once per cycle (one API call, not per-user),
diffs against the previous active set, and for each *newly* logged-in user
fans out a push to every device that (a) has that user in its friend watch
list and (b) opted into friend notifications (``pref_friend``).

The previous active set is persisted in the poller_state doc so logins are
detected across cycles even after a backend restart.
"""
import logging

import db
import ft_client
from config import FRIEND_POLLER_CAMPUS_IDS
from pollers.base import BasePoller
from push.fcm import send_push

logger = logging.getLogger(__name__)


class FriendPoller(BasePoller):
    name = "friend_poller"
    interval_seconds = 120

    async def poll(self) -> list[dict]:
        return []

    async def diff(self, new_items: list[dict]) -> list[dict]:
        return []

    async def notify(self, changes: list[dict]) -> None:
        return None

    async def _run_for_campus(self, campus_id: int, prev: set[int]) -> set[int]:
        locations = await ft_client.get_campus_active_locations(campus_id)
        active_now: set[int] = set()
        login_by_id: dict[int, str] = {}
        for loc in locations:
            user = loc.get("user") or {}
            uid = user.get("id")
            if uid is None:
                continue
            active_now.add(uid)
            login_by_id[uid] = user.get("login", str(uid))

        new_logins = active_now - prev
        for uid in new_logins:
            devices = await db.get_devices_watching(uid)
            tokens = [d["fcm_token"] for d in devices]
            if not tokens:
                continue
            login = login_by_id.get(uid, str(uid))
            logger.info("FriendPoller: %s logged in → %d watcher device(s)",
                        login, len(tokens))
            await send_push(
                tokens=tokens,
                title=f"🟢 {login} logged in",
                body="on campus now",
                data={"type": "friend_online", "user_id": str(uid)},
            )
        return active_now

    async def run(self) -> None:
        try:
            state = await db.get_poller_state(self.name) or {}
            prev_by_campus = state.get("active_by_campus", {})
            new_by_campus: dict[str, list[int]] = {}
            for campus_id in FRIEND_POLLER_CAMPUS_IDS:
                prev = set(prev_by_campus.get(str(campus_id), []))
                active_now = await self._run_for_campus(campus_id, prev)
                new_by_campus[str(campus_id)] = sorted(active_now)
            await db.save_poller_state_fields(
                self.name, active_by_campus=new_by_campus)
            await db.update_poller_state(self.name, success=True)
        except Exception:
            logger.exception("FriendPoller run error")
            await db.update_poller_state(self.name, success=False)
