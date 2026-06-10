#!/usr/bin/env bash
# Send test pushes through the backend → FCM → device, mimicking each poller's
# real payload so notification arrival AND tap deep-linking can be verified
# without waiting for real intra events (P1-6 / app routing check).
#
# Prereq: the backend must run with DEBUG_ENDPOINTS_ENABLED=true
#   - local:      DEBUG_ENDPOINTS_ENABLED=true uvicorn main:app --reload
#   - production: add DEBUG_ENDPOINTS_ENABLED=true to /opt/ft-intra-secrets/ft.env,
#                 redeploy, and REMOVE IT again after testing (the endpoints are
#                 unauthenticated).
#
# Usage:
#   ./scripts/send_test_push.sh                          # all 4 types, local
#   ./scripts/send_test_push.sh review                   # one type
#   BASE_URL=https://ft-intra.guild42.net ./scripts/send_test_push.sh review
#
# Expected on the device (per type):
#   review        → push arrives; tap opens the Evaluations screen
#   evalpo_sale   → push arrives; tap opens the Notifications screen
#   new_event     → push arrives; tap opens the Notifications screen
#   friend_online → push arrives; tap opens the Campus screen
# A {"status":"no_devices"} response means no registered device has that
# preference toggled on in Settings.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
TYPES=("${@:-evalpo_sale new_event review friend_online}")
[ $# -gt 0 ] && TYPES=("$@") || TYPES=(evalpo_sale new_event review friend_online)

for type in "${TYPES[@]}"; do
  echo "==> ${type}"
  curl -sS -X POST "${BASE_URL}/api/test-push?type=${type}" | sed 's/^/    /'
  echo
done

echo "Done. 404 responses mean DEBUG_ENDPOINTS_ENABLED is not set on the backend."
