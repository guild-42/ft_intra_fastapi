import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from deps import get_poller_state_repo
from repositories.poller_state_repo import PollerStateRepository

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health(state: PollerStateRepository = Depends(get_poller_state_repo)):
    try:
        poller_state = await state.get("events_poller")
        devices = await state.count_collection("devices")
        active_checkins = await state.count_collection("checkins", is_active=True)

        logger.debug("health: devices=%d active_checkins=%d",
                     devices, active_checkins)
        return {
            "status": "ok",
            "time": datetime.now(timezone.utc).isoformat(),
            "poller": poller_state,
            "registered_devices": devices,
            "active_checkins": active_checkins,
        }
    except Exception as e:
        logger.exception("health check failed")
        return {"status": "error", "detail": str(e)}
