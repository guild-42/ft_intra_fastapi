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


@router.post("/api/test-push")
async def test_push(
    devices: DeviceRepository = Depends(get_device_repo),
    push: PushService = Depends(get_push),
):
    """Send a test push notification to all registered devices.

    Useful when actual intra notifications are unpredictable.
    """
    logger.info("test_push: dispatching test push to evalpo_sale devices")
    device_list = await devices.get_for_notification("evalpo_sale")
    if not device_list:
        logger.warning("test_push: no devices registered")
        return {"status": "no_devices", "sent": 0}

    tokens = [d["fcm_token"] for d in device_list]
    title = "🧪 Test notification"
    body = f"Backend → FCM → device push works! ({datetime.now(timezone.utc).isoformat()})"

    sent = await push.send(
        tokens=tokens,
        title=title,
        body=body,
        data={"type": "test", "timestamp": datetime.now(timezone.utc).isoformat()},
    )

    logger.info("test_push: sent %d/%d", sent, len(tokens))
    return {"status": "ok", "devices": len(tokens), "sent": sent}


@router.post("/api/test-notification")
async def test_notification(
    notifications: NotificationRepository = Depends(get_notification_repo),
    devices: DeviceRepository = Depends(get_device_repo),
    push: PushService = Depends(get_push),
):
    """Insert a fake notification + trigger push as if scraped from intra."""
    logger.info("test_notification: inserting fake evalpo_sale notification")
    now = datetime.now(timezone.utc)
    title = "Evaluation points sales"
    body = f"[TEST] sale started at {now.isoformat()}"
    source_date = now.isoformat()

    sig = hashlib.sha1(f"test|{now.isoformat()}".encode()).hexdigest()[:16]
    inserted = await notifications.insert(sig, title, body, source_date)

    device_list = await devices.get_for_notification("evalpo_sale")
    tokens = [d["fcm_token"] for d in device_list]
    sent = 0
    if tokens:
        sent = await push.send(
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
async def poll_now(
    request: Request,
    state: PollerStateRepository = Depends(get_poller_state_repo),
):
    """Trigger the notification poller immediately (don't wait 5 min)."""
    logger.info("poll_now: manually triggering notification poller")
    # Reuse the scheduler's instance (set in main.py lifespan) — a fresh
    # instance could double-push the same diff alongside the scheduled run.
    poller = getattr(request.app.state, "notification_poller", None)
    if poller is None:
        raise HTTPException(status_code=503, detail="poller not started")
    await poller.run()
    poller_state = await state.get("notification_poller")
    logger.info("poll_now: poller finished, state=%s", poller_state)
    return {"status": "ok", "poller_state": poller_state}
