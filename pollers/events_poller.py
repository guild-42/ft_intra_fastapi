"""Campus events push poller (official public API, app token).

Replaces the cookie-scraped event notifications. Fetches each configured
campus's events via ``/v2/campus/:id/events`` with the app's client_credentials
token (public data — no user token, no scraping), diffs against what we've
already seen (notification_repo signature dedup), and pushes ``pref_event``
devices for each newly-announced event.

Events are public, so storing the signature + announcing them carries no
personal data (see doc_v2/10).
"""
import logging

from config import EVENT_POLLER_CAMPUS_IDS
from pollers.base import BasePoller

logger = logging.getLogger(__name__)


class EventsPoller(BasePoller):
    name = "events_poller"
    interval_seconds = 600

    def __init__(self, notification_repo, device_repo, state_repo, ft_client, push):
        self._notifications = notification_repo
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

    async def _run_for_campus(self, campus_id: int) -> None:
        events = await self._ft.get_campus_events(campus_id)
        logger.info("EventsPoller: campus=%d has %d event(s)", campus_id, len(events))
        # API returns most-recent first; announce oldest-new first for natural order.
        for event in reversed(events):
            eid = event.get("id")
            if eid is None:
                continue
            name = event.get("name") or "Event"
            kind = event.get("kind") or "event"
            sig = f"event:{campus_id}:{eid}"
            title = f"New event: {name}"
            body = event.get("location") or kind
            is_new = await self._notifications.insert(
                signature=sig, title=title, body=body,
                source_date=event.get("begin_at"))
            if not is_new:
                continue
            devices = await self._devices.get_for_notification("new_event")
            tokens = [d["fcm_token"] for d in devices]
            if not tokens:
                logger.info("EventsPoller: no pref_event devices for '%s'", name)
                continue
            logger.info("EventsPoller: push '%s' to %d device(s)", name, len(tokens))
            sent = await self._push.send(
                tokens=tokens,
                title=title, body=body,
                data={"type": "new_event", "event_id": str(eid)})
            if sent:
                await self._notifications.mark_pushed(sig)

    async def run(self) -> None:
        logger.info("EventsPoller: run start (campuses=%s)", EVENT_POLLER_CAMPUS_IDS)
        try:
            for campus_id in EVENT_POLLER_CAMPUS_IDS:
                try:
                    await self._run_for_campus(campus_id)
                except Exception:
                    logger.exception("EventsPoller: error for campus %d", campus_id)
            await self._state.update(self.name, success=True)
            logger.info("EventsPoller: run done")
        except Exception:
            logger.exception("EventsPoller run error")
            await self._state.update(self.name, success=False)
