import hashlib
import logging

import httpx
from bs4 import BeautifulSoup

from config import INTRA_NOTIFICATIONS_URL
from pollers.base import BasePoller

logger = logging.getLogger(__name__)


class CookieExpiredError(Exception):
    pass


def parse_notifications_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("li.notification-item")
    results = []
    for item in items:
        title_el = item.select_one("h4.notification--title")
        date_el = item.select_one("span[data-long-date]")
        body_el = item.select_one(".notification-item--body")

        title = title_el.get_text(strip=True) if title_el else ""
        source_date = date_el.get("data-long-date", "") if date_el else ""
        body_text = body_el.get_text(strip=True) if body_el else ""
        if title and body_text.startswith(title):
            body_text = body_text[len(title):].strip()

        if not title:
            continue

        sig = hashlib.sha1(f"{title}|{body_text}|{source_date}".encode()).hexdigest()[:16]
        results.append({
            "signature": sig,
            "title": title,
            "body": body_text,
            "source_date": source_date or None,
        })
    return results


# Keyword patterns for a peer-evaluation / slot-booking related notification.
# These are per-user events (only visible on the affected user's own page),
# so they are delivered by ReviewPoller, not the global poller.
_REVIEW_PATTERNS = (
    "evaluation",
    "correction",
    "corrector",
    "peer-evaluation",
    "booked a slot",
    "slot has been booked",
    "you have an evaluation",
)


def classify_notification(title: str, body: str = "") -> str:
    text = f"{title} {body}".lower()
    if "evaluation points sale" in text or "point sale" in text:
        return "evalpo_sale"
    if any(p in text for p in _REVIEW_PATTERNS):
        return "review"
    return "new_event"


class NotificationPoller(BasePoller):
    name = "notification_poller"
    interval_seconds = 300

    def __init__(self, cookie_repo, notification_repo, device_repo, state_repo, push):
        self._cookies = cookie_repo
        self._notifications = notification_repo
        self._devices = device_repo
        self._state = state_repo
        self._push = push

    async def poll(self) -> list[dict]:
        cookie = await self._cookies.get_valid()
        if not cookie:
            logger.warning("No valid cookie available, skipping poll")
            return []

        async with httpx.AsyncClient(follow_redirects=False, timeout=20) as client:
            resp = await client.get(
                INTRA_NOTIFICATIONS_URL,
                headers={
                    "Cookie": f"_intra_42_session_production={cookie}",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                },
            )

        if resp.status_code in (301, 302, 303, 307, 308):
            logger.warning("Cookie expired (HTTP %d redirect)", resp.status_code)
            await self._cookies.invalidate(cookie)
            raise CookieExpiredError(f"HTTP {resp.status_code}")

        if resp.status_code != 200:
            logger.error("Unexpected status %d from notifications page", resp.status_code)
            return []

        return parse_notifications_html(resp.text)

    async def diff(self, new_items: list[dict]) -> list[dict]:
        changes = []
        for item in new_items:
            is_new = await self._notifications.insert(
                signature=item["signature"],
                title=item["title"],
                body=item["body"],
                source_date=item["source_date"],
            )
            if is_new:
                changes.append(item)
        return changes

    async def notify(self, changes: list[dict]) -> None:
        for item in changes:
            ntype = classify_notification(item["title"], item.get("body", ""))
            # Per-user types (e.g. review) are delivered by their own poller;
            # this global poller only fans out campus-wide announcements.
            if ntype not in ("evalpo_sale", "new_event"):
                continue
            devices = await self._devices.get_for_notification(ntype)
            if not devices:
                logger.info("No devices registered for %s, skipping push", ntype)
                continue

            tokens = [d["fcm_token"] for d in devices]
            logger.info(
                "Sending push for '%s' to %d devices", item["title"], len(tokens)
            )
            await self._push.send(
                tokens=tokens,
                title=item["title"],
                body=item["body"],
                data={"type": ntype, "source_date": item["source_date"] or ""},
            )

    async def run(self) -> None:
        try:
            await super().run()
            await self._state.update(self.name, success=True)
        except CookieExpiredError:
            logger.warning("All cookies expired. Polling paused until app provides new cookie.")
            await self._state.update(self.name, success=False)
        except Exception:
            logger.exception("NotificationPoller error")
            await self._state.update(self.name, success=False)
