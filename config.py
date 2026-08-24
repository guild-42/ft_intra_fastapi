import os

# Root log level for the whole backend. Set LOG_LEVEL=DEBUG to see every
# Firestore read/write and request flow when debugging; INFO in normal ops.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Events poller: how often to fetch a campus's events via the official public
# API (app token) and diff for new ones.
EVENT_POLL_INTERVAL_SECONDS = int(os.getenv("EVENT_POLL_INTERVAL_SECONDS", "600"))
FRIEND_POLL_INTERVAL_SECONDS = int(os.getenv("FRIEND_POLL_INTERVAL_SECONDS", "120"))
# Eval "alarm clock": how often the server sends a content-less wake push to
# pref_review devices so they fetch their own /me/scale_teams (the server never
# holds the user token; see doc_v2/10). iOS throttles silent push, so this is a
# best-effort, non-realtime nudge.
EVAL_WAKE_INTERVAL_SECONDS = int(os.getenv("EVAL_WAKE_INTERVAL_SECONDS", "1800"))
FT_API_BASE = "https://api.intra.42.fr/v2"

# 42 OAuth app credentials — read ONCE here (single source of truth). Previously
# these were re-read via os.getenv in ft_client.py / routes_oauth.py /
# review_poller.py independently; now those import from config.
FT_API_CLIENT_ID = os.getenv("FT_API_CLIENT_ID", "")
FT_API_CLIENT_SECRET = os.getenv("FT_API_CLIENT_SECRET", "")
FT_TOKEN_URL = "https://api.intra.42.fr/oauth/token"

# 42 expires the client_secret on a fixed date and pre-generates its replacement
# about a week earlier, but exposes none of that over the API. The secret is
# therefore held in Firestore (rotatable without a redeploy) and encrypted with
# this key, which stays in the host secrets file so the two halves live apart.
# Unset = stored in plaintext with a warning (local dev / first boot).
FT_SECRET_ENC_KEY = os.getenv("FT_SECRET_ENC_KEY", "")

# How often to check how close the secret is to expiring, and how many days
# ahead to start warning. 42 stages the replacement ~7 days out, so warning at
# 10 gives a margin to notice and stage it before the switchover.
CREDENTIAL_CHECK_INTERVAL_SECONDS = int(
    os.getenv("CREDENTIAL_CHECK_INTERVAL_SECONDS", "3600")
)
# 42 publishes the replacement exactly 7 days before expiry (observed
# 2026-08-15 -> 2026-08-22), so warning earlier than that just nags about a
# secret that does not exist yet.
FT_SECRET_WARN_DAYS = int(os.getenv("FT_SECRET_WARN_DAYS", "7"))
# The monitor runs hourly; without this the same warning would push every run
# for the whole window.
FT_SECRET_ALERT_REPEAT_HOURS = int(os.getenv("FT_SECRET_ALERT_REPEAT_HOURS", "24"))

# 42 user ids that receive the "secret is about to expire" push. Without this
# the warning is log/-health only, which is how the last two outages went
# unnoticed. Comma-separated.
ADMIN_USER_IDS = [
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()
]

# Campuses the friend + events pollers scan (comma-separated env override).
# 26 = Tokyo. Kept under the old name for env compatibility.
FRIEND_POLLER_CAMPUS_IDS = [
    int(x) for x in os.getenv("FRIEND_POLLER_CAMPUS_IDS", "26").split(",") if x.strip()
]
EVENT_POLLER_CAMPUS_IDS = [
    int(x) for x in os.getenv("EVENT_POLLER_CAMPUS_IDS", "26").split(",") if x.strip()
]

# Unauthenticated debug endpoints (/api/test-push, /api/test-notification,
# /api/poll-now) return 404 unless explicitly enabled. Keep OFF in
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
