"""Per-user review notification poller.

Peer-evaluation / slot-booking notifications are only visible on the affected
user's own intra notifications page, so — unlike the campus-wide
``NotificationPoller`` which uses a single shared cookie — this poller scrapes
each registered user's page with *their own* cookie and pushes only to *their*
devices (gated by ``pref_review``).

Dedup is namespaced per user (``{user_id}:{signature}``) so two users seeing
similar notifications don't suppress each other.
"""
import logging

import httpx

import db
from config import INTRA_NOTIFICATIONS_URL
from pollers.base import BasePoller
from pollers.notification_poller import (
    parse_notifications_html,
    classify_notification,
)
from push.fcm import send_push

logger = logging.getLogger(__name__)

_REDIRECTS = (301, 302, 303, 307, 308)
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")


class ReviewPoller(BasePoller):
    name = "review_poller"
    interval_seconds = 300

    # poll/diff/notify are not used directly — run() drives a per-user loop.
    async def poll(self) -> list[dict]:
        return []

    async def diff(self, new_items: list[dict]) -> list[dict]:
        return []

    async def notify(self, changes: list[dict]) -> None:
        return None

    async def _scrape(self, cookie: str) -> list[dict] | None:
        """Returns parsed notifications, or None if the cookie is expired."""
        async with httpx.AsyncClient(follow_redirects=False, timeout=20) as client:
            resp = await client.get(
                INTRA_NOTIFICATIONS_URL,
                headers={
                    "Cookie": f"_intra_42_session_production={cookie}",
                    "User-Agent": _UA,
                },
            )
        if resp.status_code in _REDIRECTS:
            return None
        if resp.status_code != 200:
            logger.error("ReviewPoller: status %d", resp.status_code)
            return []
        return parse_notifications_html(resp.text)

    async def _run_for_user(self, user_id, login, cookie) -> None:
        items = await self._scrape(cookie)
        if items is None:
            logger.warning("ReviewPoller: cookie expired for user %s", login)
            await db.invalidate_cookie(cookie)
            return

        for item in items:
            if classify_notification(item["title"], item["body"]) != "review":
                continue
            # Per-user dedup namespace.
            sig = f"{user_id}:{item['signature']}"
            is_new = await db.insert_notification(
                signature=sig,
                title=item["title"],
                body=item["body"],
                source_date=item["source_date"],
            )
            if not is_new:
                continue

            devices = await db.get_devices_for_user(user_id, "pref_review")
            tokens = [d["fcm_token"] for d in devices]
            if not tokens:
                continue
            logger.info("ReviewPoller: push '%s' to %d device(s) of %s",
                        item["title"], len(tokens), login)
            await send_push(
                tokens=tokens,
                title=item["title"],
                body=item["body"],
                data={"type": "review", "source_date": item["source_date"] or ""},
            )

    async def run(self) -> None:
        try:
            cookies = await db.get_valid_cookies()
            for c in cookies:
                try:
                    await self._run_for_user(c["user_id"], c["login"], c["cookie"])
                except Exception:
                    logger.exception("ReviewPoller: error for user %s", c.get("login"))
            await db.update_poller_state(self.name, success=True)
        except Exception:
            logger.exception("ReviewPoller run error")
            await db.update_poller_state(self.name, success=False)
