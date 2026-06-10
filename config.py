import os

# Root log level for the whole backend. Set LOG_LEVEL=DEBUG to see every
# Firestore read/write and request flow when debugging; INFO in normal ops.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
REVIEW_POLL_INTERVAL_SECONDS = int(os.getenv("REVIEW_POLL_INTERVAL_SECONDS", "300"))
FRIEND_POLL_INTERVAL_SECONDS = int(os.getenv("FRIEND_POLL_INTERVAL_SECONDS", "120"))
FT_API_BASE = "https://api.intra.42.fr/v2"
INTRA_NOTIFICATIONS_URL = "https://profile.intra.42.fr/notifications"

# 42 OAuth app credentials — read ONCE here (single source of truth). Previously
# these were re-read via os.getenv in ft_client.py / routes_oauth.py /
# review_poller.py independently; now those import from config.
FT_API_CLIENT_ID = os.getenv("FT_API_CLIENT_ID", "")
FT_API_CLIENT_SECRET = os.getenv("FT_API_CLIENT_SECRET", "")
FT_TOKEN_URL = "https://api.intra.42.fr/oauth/token"

# Campuses the friend poller scans (comma-separated env override). 26 = Tokyo.
FRIEND_POLLER_CAMPUS_IDS = [
    int(x) for x in os.getenv("FRIEND_POLLER_CAMPUS_IDS", "26").split(",") if x.strip()
]

# Unauthenticated debug endpoints (/api/test-push, /api/test-notification,
# /api/poll-now, /api/cookie) return 404 unless explicitly enabled. Keep OFF in
# production; turn on locally when exercising the push pipeline by hand.
DEBUG_ENDPOINTS_ENABLED = os.getenv("DEBUG_ENDPOINTS_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)

# The client is a mobile app (no browser origin), so CORS is closed by default.
# Set CORS_ALLOW_ORIGINS="https://example.com,https://other" if a web client
# ever needs access.
CORS_ALLOW_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
]

# Location-based check-in: how long a check-in stays active without a heartbeat
# (default 3h), and how often the sweeper auto-checks-out expired ones (10min).
CHECKIN_TTL_SECONDS = int(os.getenv("CHECKIN_TTL_SECONDS", "10800"))
CHECKOUT_SWEEP_INTERVAL_SECONDS = int(
    os.getenv("CHECKOUT_SWEEP_INTERVAL_SECONDS", "600")
)
