import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import db
from config import (
    POLL_INTERVAL_SECONDS,
    REVIEW_POLL_INTERVAL_SECONDS,
    FRIEND_POLL_INTERVAL_SECONDS,
    CHECKOUT_SWEEP_INTERVAL_SECONDS,
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
poller = NotificationPoller()
review_poller = ReviewPoller()
friend_poller = FriendPoller()
checkout_sweeper = CheckoutSweeper()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    logger.info("Database initialized")

    scheduler.add_job(
        poller.run,
        "interval",
        seconds=POLL_INTERVAL_SECONDS,
        id="notification_poller",
        replace_existing=True,
    )
    scheduler.add_job(
        review_poller.run,
        "interval",
        seconds=REVIEW_POLL_INTERVAL_SECONDS,
        id="review_poller",
        replace_existing=True,
    )
    scheduler.add_job(
        friend_poller.run,
        "interval",
        seconds=FRIEND_POLL_INTERVAL_SECONDS,
        id="friend_poller",
        replace_existing=True,
    )
    scheduler.add_job(
        checkout_sweeper.run,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(oauth_router)
app.include_router(register_router)
app.include_router(notifications_router)
app.include_router(test_router)
app.include_router(checkin_router)
