#!/usr/bin/env bash
# Deploy the backend by triggering a Coolify rebuild of guild-42/ft_intra_fastapi
# @main, waiting for it to finish, then verifying the live API.
#
# Assumes you have already committed + pushed to `main` (Coolify pulls latest).
#
# Secret (Coolify API token) lives in backend/secrets/coolify-deploy.conf, which
# is gitignored (/secrets/ in .gitignore) — NEVER committed. See CLAUDE.md.
#   usage: ./deploy.sh          # trigger deploy, wait, verify
#          ./deploy.sh status   # read-only: token + current app status, no deploy
set -euo pipefail
cd "$(dirname "$0")"

CONF="secrets/coolify-deploy.conf"
[ -f "$CONF" ] || { echo "missing $CONF (COOLIFY_TOKEN/COOLIFY_APP_UUID/COOLIFY_BASE)"; exit 1; }
set -a; . "$CONF"; set +a
: "${COOLIFY_BASE:?set COOLIFY_BASE in $CONF}"
: "${COOLIFY_APP_UUID:?set COOLIFY_APP_UUID in $CONF}"
: "${COOLIFY_TOKEN:?set COOLIFY_TOKEN in $CONF}"
APP_URL="${APP_HEALTH_URL:-https://ft-intra.guild42.net}"

auth=(-H "Authorization: Bearer $COOLIFY_TOKEN")
api() { curl -fsS "${auth[@]}" "$@"; }
jq_py() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

if [ "${1:-}" = "status" ]; then
  api "$COOLIFY_BASE/api/v1/applications/$COOLIFY_APP_UUID" \
    | jq_py "f\"name={d.get('name')} repo={d.get('git_repository')}@{d.get('git_branch')} status={d.get('status')}\""
  exit 0
fi

echo "==> Triggering deploy of $COOLIFY_APP_UUID"
duuid=$(api "$COOLIFY_BASE/api/v1/deploy?uuid=$COOLIFY_APP_UUID" \
  | jq_py "d['deployments'][0]['deployment_uuid']")
echo "    deployment_uuid=$duuid"

echo "==> Waiting for deployment to finish"
for i in $(seq 1 60); do
  st=$(api "$COOLIFY_BASE/api/v1/deployments/$duuid" | jq_py "d.get('status','?')")
  printf '    [%02d] %s\n' "$i" "$st"
  case "$st" in
    finished) break;;
    failed|error|cancelled-by-user) echo "deploy $st"; exit 1;;
  esac
  sleep 10
done

echo "==> Verifying live app"
code=$(curl -s -o /dev/null -w '%{http_code}' "$APP_URL/health")
echo "    GET /health -> $code"
[ "$code" = "200" ] || { echo "health check failed"; exit 1; }
echo "==> Done."
