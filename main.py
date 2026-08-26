import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import firestore_client
from config import (
    CORS_ALLOW_ORIGINS,
    LOG_LEVEL,
    EVENT_POLL_INTERVAL_SECONDS,
    EVAL_WAKE_INTERVAL_SECONDS,
    FRIEND_POLL_INTERVAL_SECONDS,
    CHECKOUT_SWEEP_INTERVAL_SECONDS,
    CREDENTIAL_CHECK_INTERVAL_SECONDS,
    REVIEW_POLL_INTERVAL_SECONDS,
)
from deps import (
    get_checkin_repo,
    get_credential_repo,
    get_device_repo,
    get_friendship_repo,
    get_ft_client,
    get_ft_credentials,
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
from api.routes_legal import router as legal_router
from api.routes_landing import router as landing_router
from api.routes_friends import router as friends_router
from pollers.events_poller import EventsPoller
from pollers.eval_wake_poller import EvalWakePoller
from pollers.friend_poller import FriendPoller
from pollers.checkout_sweeper import CheckoutSweeper
from pollers.credential_monitor import CredentialMonitor
from pollers.review_poller import ReviewPoller

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
    the shared Firestore client; push/ft_client are process singletons.

    No cookie scraping and no server-held 42 token (doc_v2/10): events come from
    the public API, eval is a content-less wake push, friend uses public
    locations."""
    events = EventsPoller(
        notification_repo=get_notification_repo(),
        device_repo=get_device_repo(),
        state_repo=get_poller_state_repo(),
        ft_client=get_ft_client(),
        push=get_push(),
    )
    eval_wake = EvalWakePoller(
        device_repo=get_device_repo(),
        state_repo=get_poller_state_repo(),
        push=get_push(),
    )
    friend = FriendPoller(
        device_repo=get_device_repo(),
        friendship_repo=get_friendship_repo(),
        state_repo=get_poller_state_repo(),
        ft_client=get_ft_client(),
        push=get_push(),
    )
    sweeper = CheckoutSweeper(
        checkin_repo=get_checkin_repo(),
        state_repo=get_poller_state_repo(),
    )
    credentials = CredentialMonitor(
        credentials=get_ft_credentials(),
        state_repo=get_poller_state_repo(),
        device_repo_factory=get_device_repo,
        push=get_push(),
        credential_repo_factory=get_credential_repo,
    )
    review = ReviewPoller(
        device_repo=get_device_repo(),
        state_repo=get_poller_state_repo(),
        ft_client=get_ft_client(),
        push=get_push(),
    )
    return events, eval_wake, friend, sweeper, credentials, review


@asynccontextmanager
async def lifespan(app: FastAPI):
    await firestore_client.init_db()
    logger.info("Database initialized")

    events, eval_wake, friend, sweeper, credentials, review = _build_pollers()
    # Shared with /api/poll-now so a manual trigger reuses the same instance.
    app.state.events_poller = events

    scheduler.add_job(
        events.run,
        "interval",
        seconds=EVENT_POLL_INTERVAL_SECONDS,
        id="events_poller",
        replace_existing=True,
    )
    scheduler.add_job(
        eval_wake.run,
        "interval",
        seconds=EVAL_WAKE_INTERVAL_SECONDS,
        id="eval_wake_poller",
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
    scheduler.add_job(
        review.run,
        "interval",
        seconds=REVIEW_POLL_INTERVAL_SECONDS,
        id="review_poller",
        replace_existing=True,
    )
    scheduler.add_job(
        credentials.run,
        "interval",
        seconds=CREDENTIAL_CHECK_INTERVAL_SECONDS,
        id="credential_monitor",
        replace_existing=True,
        # Run shortly after boot too: a secret that expired while the process was
        # down should self-heal on startup, not one interval later.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
    )
    scheduler.start()
    logger.info(
        "Scheduler started (events=%ds, eval_wake=%ds, friend=%ds, credentials=%ds, review=%ds)",
        EVENT_POLL_INTERVAL_SECONDS,
        EVAL_WAKE_INTERVAL_SECONDS,
        FRIEND_POLL_INTERVAL_SECONDS,
        CREDENTIAL_CHECK_INTERVAL_SECONDS,
        REVIEW_POLL_INTERVAL_SECONDS,
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
app.include_router(legal_router)
app.include_router(landing_router)
app.include_router(friends_router)
