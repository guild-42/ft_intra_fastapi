#!/usr/bin/env python3
"""Operator CLI for the 42 OAuth credential held in Firestore.

42 exposes no API for reading or regenerating an app's client_secret, so the
value itself has to be copied from the dashboard by hand. Everything after that
is automated: stage the replacement here and the backend promotes it on its own
when 42 starts rejecting the current one — no restart, no redeploy.

  status                 show current credential state
  set                    replace the ACTIVE secret (validated against 42 first)
  next                   stage the REPLACEMENT secret (not validated — 42 does
                         not accept it until the switchover)

The secret is read from stdin, never argv, so it stays out of `ps` and shell
history.

  ./manage_credential.py status
  printf %s "$SECRET" | ./manage_credential.py set  --expires 2026-10-22
  printf %s "$SECRET" | ./manage_credential.py next --expires 2026-10-22
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone


def _load_secrets_env(path="/secrets/ft.env"):
    """Load the mounted secrets file into os.environ.

    entrypoint.sh sources this for the server process, but `docker exec` starts
    a fresh process that skips the entrypoint — so without this the CLI runs
    with no FT_SECRET_ENC_KEY and cannot decrypt anything. Must happen before
    `config` is imported, since config reads os.getenv at import time.
    """
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_secrets_env()

from config import FT_API_CLIENT_ID, FT_SECRET_ENC_KEY  # noqa: E402
from deps import get_ft_credentials  # noqa: E402
from firestore_client import get_client  # noqa: E402
from repositories.credential_repo import CredentialRepository  # noqa: E402


def _repo():
    return CredentialRepository(get_client(), enc_key=FT_SECRET_ENC_KEY)


def _read_secret() -> str:
    if sys.stdin.isatty():
        sys.exit("error: pipe the secret via stdin, e.g. "
                 "printf %s \"$SECRET\" | ./manage_credential.py set")
    secret = sys.stdin.read().strip()
    if not secret:
        sys.exit("error: empty secret on stdin")
    if not secret.startswith("s-s4t2ud-"):
        sys.exit(f"error: does not look like a 42 secret (expected s-s4t2ud-…, "
                 f"got {len(secret)} chars starting {secret[:9]!r})")
    return secret


def _parse_expiry(value: str | None):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


async def cmd_status():
    data = await _repo().get()
    if not data:
        print("no stored credential (backend is still using the env value)")
        return
    def h(v):
        return f"<set, {len(v)} chars, sha256 {__import__('hashlib').sha256(v.encode()).hexdigest()[:12]}…>" if v else "<none>"
    print(f"client_id         : {data.get('client_id')}")
    print(f"secret            : {h(data.get('secret'))}")
    print(f"next_secret       : {h(data.get('next_secret'))}")
    print(f"secret_expires_at : {data.get('secret_expires_at')}")
    print(f"last_auth_ok      : {data.get('last_auth_ok')}")
    print(f"last_auth_at      : {data.get('last_auth_at')}")
    print(f"last_auth_error   : {data.get('last_auth_error')}")
    print(f"rotated_at        : {data.get('rotated_at')}")

    creds = get_ft_credentials()
    live = await creds.validate(data.get("secret") or "")
    print(f"\n42 accepts stored secret right now: {'YES' if live else 'NO'}")


async def cmd_set(expires):
    secret = _read_secret()
    creds = get_ft_credentials()
    print("validating against 42…")
    if not await creds.validate(secret):
        sys.exit("error: 42 REJECTED this secret — not storing it. "
                 "Check you copied the active SECRET (not the NEXT SECRET).")
    await _repo().save(client_id=FT_API_CLIENT_ID, secret=secret, expires_at=expires)
    creds.invalidate()
    print("stored + validated. The running backend picks it up within ~60s "
          "(no restart needed).")


async def cmd_next(expires):
    secret = _read_secret()
    # Deliberately NOT validated: 42 rejects the next secret until the current
    # one expires, so a validation here would always fail and block staging.
    await _repo().stage_next(secret, expires_at=expires)
    print("staged as next_secret. The backend promotes it automatically the "
          "moment 42 starts rejecting the current secret.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "set", "next"])
    ap.add_argument("--expires", help="secret expiry date, YYYY-MM-DD "
                                      "(from the 42 dashboard's 'Valid until')")
    args = ap.parse_args()
    expires = _parse_expiry(args.expires)
    if args.command == "status":
        asyncio.run(cmd_status())
    elif args.command == "set":
        asyncio.run(cmd_set(expires))
    else:
        asyncio.run(cmd_next(expires))


if __name__ == "__main__":
    main()
