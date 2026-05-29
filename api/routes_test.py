"""Test endpoints for verifying push notification flow."""
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter

import db
from push.fcm import send_push

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/test-push")
async def test_push():
    """Send a test push notification to all registered devices.

    Useful when actual intra notifications are unpredictable.
    """
    devices = await db.get_devices_for_notification("evalpo_sale")
    if not devices:
        return {"status": "no_devices", "sent": 0}

    tokens = [d["fcm_token"] for d in devices]
    title = "🧪 Test notification"
    body = f"Backend → FCM → device push works! ({datetime.now(timezone.utc).isoformat()})"

    sent = await send_push(
        tokens=tokens,
        title=title,
        body=body,
        data={"type": "test", "timestamp": datetime.now(timezone.utc).isoformat()},
    )

    return {"status": "ok", "devices": len(tokens), "sent": sent}


@router.post("/api/test-notification")
async def test_notification():
    """Insert a fake notification + trigger push as if scraped from intra."""
    now = datetime.now(timezone.utc)
    title = "Evaluation points sales"
    body = f"[TEST] sale started at {now.isoformat()}"
    source_date = now.isoformat()

    sig = hashlib.sha1(f"test|{now.isoformat()}".encode()).hexdigest()[:16]
    inserted = await db.insert_notification(sig, title, body, source_date)

    devices = await db.get_devices_for_notification("evalpo_sale")
    tokens = [d["fcm_token"] for d in devices]
    sent = 0
    if tokens:
        sent = await send_push(
            tokens=tokens,
            title=title,
            body=body,
            data={"type": "evalpo_sale", "signature": sig},
        )

    return {
        "status": "ok",
        "inserted": inserted,
        "signature": sig,
        "devices": len(tokens),
        "sent": sent,
    }


@router.post("/api/poll-now")
async def poll_now():
    """Trigger the notification poller immediately (don't wait 5 min)."""
    from pollers.notification_poller import NotificationPoller
    poller = NotificationPoller()
    await poller.run()
    state = await db.get_poller_state("notification_poller")
    return {"status": "ok", "poller_state": state}
