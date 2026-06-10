import logging
import time
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import firestore_client
from config import (
    CORS_ALLOW_ORIGINS,
    LOG_LEVEL,
    POLL_INTERVAL_SECONDS,
    REVIEW_POLL_INTERVAL_SECONDS,
    FRIEND_POLL_INTERVAL_SECONDS,
    CHECKOUT_SWEEP_INTERVAL_SECONDS,
)
from deps import (
    get_checkin_repo,
    get_cookie_repo,
    get_device_repo,
    get_ft_client,
    get_notification_repo,
    get_poller_state_repo,
    get_push,
)
from api.routes_register import router as register_router
from api.routes_notifications import router as notifications_router
from api.routes_health import router as health_router
from api.routes_oauth import router as oauth_router
from api.routes_test import router as test_router
from api.routes_checkin import router as checkin_router
from pollers.notification_poller import NotificationPoller
from pollers.review_poller import ReviewPoller
from pollers.friend_poller import FriendPoller
from pollers.checkout_sweeper import CheckoutSweeper

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
# google/grpc/firestore emit a flood of DEBUG lines that drown out our own logs
# when LOG_LEVEL=DEBUG; pin them to WARNING so the backend's logs stay readable.
for noisy in ("google", "grpc", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.info("Logging configured at level %s", LOG_LEVEL)

scheduler = AsyncIOScheduler()


def _build_pollers():
    """Construct each poller with its injected repositories/services. Repos wrap
    the shared Firestore client; push/ft_client are process singletons."""
    notification = NotificationPoller(
        cookie_repo=get_cookie_repo(),
        notification_repo=get_notification_repo(),
        device_repo=get_device_repo(),
        state_repo=get_poller_state_repo(),
        push=get_push(),
    )
    review = ReviewPoller(
        device_repo=get_device_repo(),
        notification_repo=get_notification_repo(),
        state_repo=get_poller_state_repo(),
        push=get_push(),
    )
    friend = FriendPoller(
        device_repo=get_device_repo(),
        state_repo=get_poller_state_repo(),
        ft_client=get_ft_client(),
        push=get_push(),
    )
    sweeper = CheckoutSweeper(
        checkin_repo=get_checkin_repo(),
        state_repo=get_poller_state_repo(),
    )
    return notification, review, friend, sweeper


@asynccontextmanager
async def lifespan(app: FastAPI):
    await firestore_client.init_db()
    logger.info("Database initialized")

    notification, review, friend, sweeper = _build_pollers()
    # Shared with /api/poll-now so a manual trigger reuses the same instance
    # (a second instance risks double-pushing the same diff).
    app.state.notification_poller = notification

    scheduler.add_job(
        notification.run,
        "interval",
        seconds=POLL_INTERVAL_SECONDS,
        id="notification_poller",
        replace_existing=True,
    )
    scheduler.add_job(
        review.run,
        "interval",
        seconds=REVIEW_POLL_INTERVAL_SECONDS,
        id="review_poller",
        replace_existing=True,
    )
    scheduler.add_job(
        friend.run,
        "interval",
        seconds=FRIEND_POLL_INTERVAL_SECONDS,
        id="friend_poller",
        replace_existing=True,
    )
    scheduler.add_job(
        sweeper.run,
        "interval",
        seconds=CHECKOUT_SWEEP_INTERVAL_SECONDS,
        id="checkout_sweeper",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started (notif=%ds, review=%ds, friend=%ds)",
        POLL_INTERVAL_SECONDS,
        REVIEW_POLL_INTERVAL_SECONDS,
        FRIEND_POLL_INTERVAL_SECONDS,
    )

    yield

    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(title="ft_intra42 backend", lifespan=lifespan)

# Mobile-only client → no browser origins needed; closed unless explicitly
# opened via CORS_ALLOW_ORIGINS (P0-4).
if CORS_ALLOW_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every request's method/path, response status and latency. Bodies are
    never logged (they carry access tokens / cookies)."""
    start = time.perf_counter()
    logger.info("→ %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        logger.exception("✗ %s %s failed after %.0fms",
                         request.method, request.url.path, elapsed)
        raise
    elapsed = (time.perf_counter() - start) * 1000
    logger.info("← %s %s %d (%.0fms)",
                request.method, request.url.path, response.status_code, elapsed)
    return response


app.include_router(health_router)
app.include_router(oauth_router)
app.include_router(register_router)
app.include_router(notifications_router)
app.include_router(test_router)
app.include_router(checkin_router)
