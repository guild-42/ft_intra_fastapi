"""Test endpoints for verifying push notification flow."""
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

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
router = APIRouter()


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


@router.get("/api/test-token-state")
async def test_token_state(devices: DeviceRepository = Depends(get_device_repo)):
    """DIAGNOSTIC (temporary): which device docs still hold an OAuth token.
    Returns booleans/counts only — never token values."""
    out = []
    async for snap in devices._db.collection("devices").stream():
        d = snap.to_dict() or {}
        out.append({
            "fcm": str(snap.id)[:12] + "…",
            "user_id": d.get("user_id"),
            "has_access": "access_token" in d,
            "has_refresh": "refresh_token" in d,
            "pref_review": d.get("pref_review"),
            "updated_at": str(d.get("updated_at")),
        })
    with_token = sum(1 for x in out if x["has_access"] or x["has_refresh"])
    return {"total": len(out), "with_token": with_token, "devices": out}


@router.post("/api/poll-now")
async def poll_now(state: PollerStateRepository = Depends(get_poller_state_repo)):
    """Trigger the notification poller immediately (don't wait 5 min)."""
    logger.info("poll_now: manually triggering notification poller")
    # Build the poller with the same injected dependencies main.py uses.
    from deps import (
        get_cookie_repo,
        get_device_repo,
        get_notification_repo,
        get_poller_state_repo,
        get_push,
    )
    from pollers.notification_poller import NotificationPoller

    poller = NotificationPoller(
        cookie_repo=get_cookie_repo(),
        notification_repo=get_notification_repo(),
        device_repo=get_device_repo(),
        state_repo=get_poller_state_repo(),
        push=get_push(),
    )
    await poller.run()
    poller_state = await state.get("notification_poller")
    logger.info("poll_now: poller finished, state=%s", poller_state)
    return {"status": "ok", "poller_state": poller_state}
