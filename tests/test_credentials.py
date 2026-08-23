"""Covers the 42 client_secret rotation path.

The secret expired twice in production (2026-06-30, 2026-08-22) and took login
and every poller down with it. These tests pin the behaviour that makes the
switchover automatic: a staged replacement is promoted when 42 starts rejecting
the current secret, and a bad staged value can never replace a working one.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import FakeClient  # noqa: E402
from repositories.credential_repo import CredentialRepository  # noqa: E402
from services.ft_credentials import FtCredentials  # noqa: E402
from services import secret_cipher  # noqa: E402

KEY = "test-encryption-key"
CUR = "s-s4t2ud-" + "a" * 64
NXT = "s-s4t2ud-" + "b" * 64


def _repo(client=None, key=KEY):
    return CredentialRepository(client or FakeClient(), enc_key=key)


# ───── cipher ─────

def test_cipher_roundtrip():
    enc = secret_cipher.encrypt(CUR, KEY)
    assert enc != CUR, "must not be stored in plaintext when a key is set"
    assert secret_cipher.decrypt(enc, KEY) == CUR


def test_cipher_without_key_is_passthrough():
    assert secret_cipher.encrypt(CUR, None) == CUR
    # Plaintext written before a key existed must still read back.
    assert secret_cipher.decrypt(CUR, KEY) == CUR


def test_cipher_wrong_key_raises():
    enc = secret_cipher.encrypt(CUR, KEY)
    with pytest.raises(RuntimeError):
        secret_cipher.decrypt(enc, "a-different-key")


# ───── repository ─────

@pytest.mark.asyncio
async def test_save_and_get_roundtrip():
    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR)
    got = await repo.get()
    assert got["secret"] == CUR
    assert got["client_id"] == "u-1"


@pytest.mark.asyncio
async def test_secret_is_encrypted_at_rest():
    client = FakeClient()
    await _repo(client).save(client_id="u-1", secret=CUR)
    raw = client.store["credentials"]["ft_oauth"]["secret"]
    assert CUR not in raw


@pytest.mark.asyncio
async def test_save_does_not_clobber_staged_next():
    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR)
    await repo.stage_next(NXT)
    await repo.save(client_id="u-1", secret=CUR)  # e.g. re-seed from env
    assert (await repo.get())["next_secret"] == NXT


@pytest.mark.asyncio
async def test_promote_next_moves_and_clears():
    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR)
    await repo.stage_next(NXT)

    assert await repo.promote_next() == NXT
    got = await repo.get()
    assert got["secret"] == NXT
    assert not got.get("next_secret")
    assert got.get("rotated_at") is not None


@pytest.mark.asyncio
async def test_promote_without_staged_is_noop():
    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR)
    assert await repo.promote_next() is None
    assert (await repo.get())["secret"] == CUR


# ───── credential service ─────

def _creds(repo, accepts=(), env_secret=CUR):
    """FtCredentials whose 42 validation accepts only `accepts`."""
    c = FtCredentials(repo_factory=lambda: repo, client_id="u-1",
                      env_secret=env_secret)

    async def fake_validate(secret):
        return secret in accepts
    c.validate = fake_validate
    return c


@pytest.mark.asyncio
async def test_current_falls_back_to_env_and_seeds_store():
    repo = _repo()
    creds = _creds(repo, accepts=(CUR,))
    assert await creds.current() == CUR
    # Seeded so it becomes rotatable from now on.
    assert (await repo.get())["secret"] == CUR


@pytest.mark.asyncio
async def test_current_prefers_store_over_env():
    repo = _repo()
    await repo.save(client_id="u-1", secret=NXT)
    creds = _creds(repo, accepts=(NXT,), env_secret=CUR)
    assert await creds.current() == NXT


@pytest.mark.asyncio
async def test_rotate_promotes_staged_secret_that_42_accepts():
    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR)
    await repo.stage_next(NXT)
    creds = _creds(repo, accepts=(NXT,))          # 42 now rejects CUR, accepts NXT
    await creds.current()

    assert await creds.rotate_if_possible() == NXT
    assert (await repo.get())["secret"] == NXT
    assert await creds.current() == NXT           # cache updated, no restart needed


@pytest.mark.asyncio
async def test_rotate_refuses_staged_secret_that_42_rejects():
    """A typo'd or stale staged value must never replace a working secret."""
    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR)
    await repo.stage_next("s-s4t2ud-" + "c" * 64)
    creds = _creds(repo, accepts=(CUR,))          # only the current one works

    assert await creds.rotate_if_possible() is None
    assert (await repo.get())["secret"] == CUR


@pytest.mark.asyncio
async def test_rotate_without_staged_secret_returns_none():
    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR)
    creds = _creds(repo, accepts=())
    assert await creds.rotate_if_possible() is None


@pytest.mark.asyncio
async def test_status_reports_expiry_and_staging():
    from datetime import datetime, timedelta, timezone
    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=5))
    await repo.record_auth(True)
    creds = _creds(repo, accepts=(CUR,))

    st = await creds.status()
    assert st["auth_ok"] is True
    assert st["days_until_expiry"] in (4, 5)
    assert st["next_secret_staged"] is False

    await repo.stage_next(NXT)
    assert (await creds.status())["next_secret_staged"] is True


# ───── FtClient: a rejected secret must trigger rotation + retry ─────

class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_ft_client_rotates_and_retries_on_401():
    """The whole point: a poll that hits an expired secret recovers by itself
    instead of returning None until a human intervenes."""
    from services.ft_client import FtClient

    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR)
    await repo.stage_next(NXT)
    creds = _creds(repo, accepts=(NXT,))

    calls = []

    async def fake_request(secret):
        calls.append(secret)
        if secret == NXT:
            return _Resp(200, {"access_token": "tok", "expires_in": 7200})
        return _Resp(401, {"error": "invalid_client"})

    client = FtClient(creds)
    client._request_token = fake_request

    assert await client.get_app_token() == "tok"
    assert calls == [CUR, NXT], "should retry once with the promoted secret"
    assert (await repo.get())["secret"] == NXT


@pytest.mark.asyncio
async def test_ft_client_gives_up_when_nothing_staged():
    from services.ft_client import FtClient

    repo = _repo()
    await repo.save(client_id="u-1", secret=CUR)
    creds = _creds(repo, accepts=())

    async def fake_request(secret):
        return _Resp(401, {"error": "invalid_client"})

    client = FtClient(creds)
    client._request_token = fake_request

    assert await client.get_app_token() is None
    assert (await repo.get())["last_auth_ok"] is False
