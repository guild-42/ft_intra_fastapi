import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response

from deps import get_ft_credentials, get_poller_state_repo
from repositories.poller_state_repo import PollerStateRepository
from services.ft_credentials import FtCredentials

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health(state: PollerStateRepository = Depends(get_poller_state_repo),
                 creds: FtCredentials = Depends(get_ft_credentials)):
    """Liveness. Always 200 while the process is serving.

    Deliberately does NOT fail on a broken 42 credential: the container
    healthcheck polls this, and failing it would pull the whole app out of the
    proxy — taking down endpoints that don't need 42 at all and turning a
    partial outage into a total one. The 42 state is reported in the body, and
    /health/deps is the endpoint that actually fails for monitoring.
    """
    try:
        poller_state = await state.get("events_poller")
        devices = await state.count_collection("devices")
        active_checkins = await state.count_collection("checkins", is_active=True)
        ft_api = await creds.status()

        logger.debug("health: devices=%d active_checkins=%d", devices, active_checkins)
        return {
            "status": "ok",
            "time": datetime.now(timezone.utc).isoformat(),
            "poller": poller_state,
            "registered_devices": devices,
            "active_checkins": active_checkins,
            "ft_api": ft_api,
        }
    except Exception as e:
        logger.exception("health check failed")
        return {"status": "error", "detail": str(e)}


@router.get("/health/deps")
async def health_deps(response: Response,
                      creds: FtCredentials = Depends(get_ft_credentials)):
    """Dependency health for external monitoring — 503 when 42 auth is broken.

    Kept separate from /health on purpose so an uptime check can alert on a dead
    credential without the container healthcheck deregistering the app.
    """
    ft_api = await creds.status()
    degraded = ft_api.get("auth_ok") is False
    expiring = (
        ft_api.get("days_until_expiry") is not None
        and ft_api["days_until_expiry"] <= 0
    )
    if degraded or expiring:
        response.status_code = 503
        return {"status": "degraded", "ft_api": ft_api}
    return {"status": "ok", "ft_api": ft_api}
