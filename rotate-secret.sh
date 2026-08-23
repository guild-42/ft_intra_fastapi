#!/usr/bin/env bash
# Set or stage the 42 client_secret on the running backend — no ssh-editing
# files, no restart, no redeploy.
#
# 42 expires the app's client_secret on a fixed date and pre-generates the
# replacement ~7 days earlier, but exposes neither over its API, so the value
# must be copied from https://profile.intra.42.fr/oauth/applications by hand.
# Everything after that is automatic: once staged, the backend promotes the
# replacement itself the moment 42 rejects the current secret.
#
#   ./rotate-secret.sh status
#   ./rotate-secret.sh next --expires 2026-10-22   # stage the NEXT SECRET  <- do this
#   ./rotate-secret.sh set  --expires 2026-10-22   # replace the ACTIVE secret (emergency)
#
# The secret is prompted for and piped over stdin, so it never appears in argv,
# `ps`, or shell history on either machine.
set -euo pipefail
cd "$(dirname "$0")"

HOST="${FT_INTRA_SSH_HOST:-kakun@ssh.cocoyo.org}"
CMD="${1:-status}"; shift || true

container() {
  ssh -o ConnectTimeout=10 "$HOST" \
    "sudo -n docker ps --filter 'name=ft-intra-backend' --format '{{.Names}}' | head -1"
}

C="$(container)"
[ -n "$C" ] || { echo "ABORT: no running ft-intra-backend container on $HOST"; exit 1; }

case "$CMD" in
  status)
    ssh -o ConnectTimeout=10 "$HOST" \
      "sudo -n docker exec $C python /app/manage_credential.py status < /dev/null"
    ;;
  set|next)
    printf 'Paste the 42 secret (input hidden): ' >&2
    read -rs SECRET; echo >&2
    [ -n "$SECRET" ] || { echo "ABORT: empty secret"; exit 1; }
    printf '%s' "$SECRET" | ssh -o ConnectTimeout=10 "$HOST" \
      "sudo -n docker exec -i $C python /app/manage_credential.py $CMD $*"
    unset SECRET
    echo
    echo "==> verifying live app"
    curl -sS --max-time 15 https://ft-intra.guild42.net/health/deps || true
    echo
    ;;
  *)
    echo "usage: $0 {status|set|next} [--expires YYYY-MM-DD]"; exit 1;;
esac
