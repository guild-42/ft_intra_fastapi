"""Test endpoints for verifying push notification flow."""
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

import config
from deps import (
    get_device_repo,
    get_notification_repo,
    get_poller_state_repo,
    get_push,
)
from repositories.device_repo import DeviceRepository
from repositories.notification_repo import NotificationRepository
from repositories.poller_state_repo import PollerStateRepository
from services.push import PushService

logger = logging.getLogger(__name__)


async def require_debug_enabled():
    """These endpoints are unauthenticated; hide them (404, not 403, to avoid
    advertising their existence) unless DEBUG_ENDPOINTS_ENABLED is set."""
    if not config.DEBUG_ENDPOINTS_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(dependencies=[Depends(require_debug_enabled)])


# One template per notification type, mirroring the exact data payload each
# poller sends — so tapping the test push exercises the app's deep-link
# routing (review → /evaluations, evalpo/event → /notifications,
# friend_online → /campus).
_PUSH_TEMPLATES = {
    "new_event": {
        "title": "New event: Test workshop",
        "body": "[TEST] Join us in cluster 1",
        "data": lambda now: {"type": "new_event", "source_date": now},
        "pref": "new_event",
    },
    "review": {
        "title": "Evaluation scheduled",
        "body": "[TEST] libft · you correct peer · tomorrow 10:00",
        "data": lambda now: {"type": "review", "scale_team_id": "424242"},
        "pref": "review",
    },
    "friend_online": {
        "title": "Friend online",
        "body": "[TEST] peer logged in at c1r2s3",
        "data": lambda now: {"type": "friend_online", "user_id": "424242"},
        "pref": "friend_online",
    },
}


@router.post("/api/test-push")
async def test_push(
    type: str = "new_event",
    devices: DeviceRepository = Depends(get_device_repo),
    push: PushService = Depends(get_push),
):
    """Send a test push of the given type (?type=new_event|review|
    friend_online) to every device opted into that preference, with the same
    data payload the real poller would send. Useful because real intra events
    are unpredictable."""
    template = _PUSH_TEMPLATES.get(type)
    if template is None:
        raise HTTPException(
            status_code=400,
            detail=f"type must be one of {sorted(_PUSH_TEMPLATES)}",
        )
    logger.info("test_push: dispatching %s test push", type)
    device_list = await devices.get_for_notification(template["pref"])
    if not device_list:
        logger.warning("test_push: no devices opted into %s", type)
        return {"status": "no_devices", "type": type, "sent": 0}

    now = datetime.now(timezone.utc).isoformat()
    tokens = [d["fcm_token"] for d in device_list]
    sent = await push.send(
        tokens=tokens,
        title=template["title"],
        body=template["body"],
        data=template["data"](now),
    )

    logger.info("test_push: sent %d/%d", sent, len(tokens))
    return {"status": "ok", "type": type, "devices": len(tokens), "sent": sent}


@router.post("/api/test-notification")
async def test_notification(
    notifications: NotificationRepository = Depends(get_notification_repo),
    devices: DeviceRepository = Depends(get_device_repo),
    push: PushService = Depends(get_push),
):
    """Insert a fake event notification + trigger push (mirrors EventsPoller)."""
    logger.info("test_notification: inserting fake new_event notification")
    now = datetime.now(timezone.utc)
    title = "New event: Test workshop"
    body = f"[TEST] announced at {now.isoformat()}"
    source_date = now.isoformat()

    sig = hashlib.sha1(f"test|{now.isoformat()}".encode()).hexdigest()[:16]
    inserted = await notifications.insert(sig, title, body, source_date)

    device_list = await devices.get_for_notification("new_event")
    tokens = [d["fcm_token"] for d in device_list]
    sent = 0
    if tokens:
        sent = await push.send(
            tokens=tokens,
            title=title,
            body=body,
            data={"type": "new_event", "signature": sig},
        )

    return {
        "status": "ok",
        "inserted": inserted,
        "signature": sig,
        "devices": len(tokens),
        "sent": sent,
    }


@router.post("/api/poll-now")
async def poll_now(
    request: Request,
    state: PollerStateRepository = Depends(get_poller_state_repo),
):
    """Trigger the events poller immediately (don't wait for the interval)."""
    logger.info("poll_now: manually triggering events poller")
    # Reuse the scheduler's instance (set in main.py lifespan) — a fresh
    # instance could double-push the same diff alongside the scheduled run.
    poller = getattr(request.app.state, "events_poller", None)
    if poller is None:
        raise HTTPException(status_code=503, detail="poller not started")
    await poller.run()
    poller_state = await state.get("events_poller")
    logger.info("poll_now: poller finished, state=%s", poller_state)
    return {"status": "ok", "poller_state": poller_state}
