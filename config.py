import os

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
REVIEW_POLL_INTERVAL_SECONDS = int(os.getenv("REVIEW_POLL_INTERVAL_SECONDS", "300"))
FRIEND_POLL_INTERVAL_SECONDS = int(os.getenv("FRIEND_POLL_INTERVAL_SECONDS", "120"))
FT_API_BASE = "https://api.intra.42.fr/v2"
INTRA_NOTIFICATIONS_URL = "https://profile.intra.42.fr/notifications"

# Campuses the friend poller scans (comma-separated env override). 26 = Tokyo.
FRIEND_POLLER_CAMPUS_IDS = [
    int(x) for x in os.getenv("FRIEND_POLLER_CAMPUS_IDS", "26").split(",") if x.strip()
]

# Location-based check-in: how long a check-in stays active without a heartbeat
# (default 3h), and how often the sweeper auto-checks-out expired ones (10min).
CHECKIN_TTL_SECONDS = int(os.getenv("CHECKIN_TTL_SECONDS", "10800"))
CHECKOUT_SWEEP_INTERVAL_SECONDS = int(
    os.getenv("CHECKOUT_SWEEP_INTERVAL_SECONDS", "600")
)
