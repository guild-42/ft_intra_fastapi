from datetime import datetime, timezone
from fastapi import APIRouter
import db

router = APIRouter()


@router.get("/health")
async def health():
    try:
        poller_state = await db.get_poller_state("notification_poller")
        valid_cookies = await db.count_collection("cookies", is_valid=True)
        devices = await db.count_collection("devices")
        active_checkins = await db.count_collection("checkins", is_active=True)

        return {
            "status": "ok",
            "time": datetime.now(timezone.utc).isoformat(),
            "poller": poller_state,
            "valid_cookies": valid_cookies,
            "registered_devices": devices,
            "active_checkins": active_checkins,
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}
