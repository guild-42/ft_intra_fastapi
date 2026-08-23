#!/usr/bin/env bash
# Deploy the backend straight to the host, bypassing Coolify's API.
#
# Why this exists: as of 2026-08-23 `deploy.sh` cannot work — the Coolify
# dashboard domain (coolify.guild42.net) no longer resolves and its API token is
# rejected ("Unauthenticated"). Coolify still *runs* the container, so this
# script rebuilds it in place while preserving the identity Coolify generated
# (container name, Traefik routing labels, both networks). Those live in
# /opt/ft-intra-deploy/docker-compose.deploy.yaml on the host, which was
# generated from the running container — losing it means losing the routing
# labels, so do not delete it.
#
# Prefer the Coolify UI/API again once the dashboard is reachable.
set -euo pipefail
cd "$(dirname "$0")"

HOST="${FT_INTRA_SSH_HOST:-kakun@ssh.cocoyo.org}"
REMOTE_DIR=/opt/ft-intra-deploy
PROJECT=lg4cww4ggoksc0kscog4cccg
APP_URL="${APP_HEALTH_URL:-https://ft-intra.guild42.net}"

ssh -o ConnectTimeout=10 "$HOST" "test -f $REMOTE_DIR/docker-compose.deploy.yaml" \
  || { echo "ABORT: $REMOTE_DIR/docker-compose.deploy.yaml missing on $HOST."
       echo "It carries Coolify's Traefik labels; regenerate it from the running"
       echo "container before deploying (see CLAUDE.md)."; exit 1; }

echo "==> Shipping working tree to $HOST:$REMOTE_DIR"
tar czf - --exclude=.venv --exclude=.venv-push --exclude=secrets \
    --exclude=__pycache__ --exclude=.git --exclude='*.pyc' . \
  | ssh -o ConnectTimeout=20 "$HOST" "tar xzf - -C $REMOTE_DIR"

echo "==> Building + restarting"
ssh -o ConnectTimeout=60 "$HOST" \
  "cd $REMOTE_DIR && sudo -n docker compose -p $PROJECT -f docker-compose.deploy.yaml up -d --build" \
  2>&1 | tail -6

echo "==> Verifying (edge cutover can lag a few seconds)"
for i in $(seq 1 18); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 "$APP_URL/health" || true)
  printf '    [%02d] GET /health -> %s\n' "$i" "$code"
  [ "$code" = "200" ] && break
  sleep 5
done
[ "${code:-}" = "200" ] || { echo "health check failed"; exit 1; }

echo "==> 42 credential state"
curl -sS --max-time 15 "$APP_URL/health/deps" || true
echo
echo "==> Done."
