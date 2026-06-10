"""Cookie encryption-at-rest (P0-5): round-trip, legacy plaintext tolerance,
and invalidate matching on the decrypted value."""
import asyncio

from cryptography.fernet import Fernet

import services.cookie_cipher as cc
from repositories.cookie_repo import CookieRepository
from tests.conftest import FakeClient


def _with_key(monkeypatch):
    monkeypatch.setattr(cc, "COOKIE_ENC_KEY", Fernet.generate_key().decode())


def test_store_encrypts_and_get_valid_decrypts(monkeypatch):
    _with_key(monkeypatch)
    fake = FakeClient()
    repo = CookieRepository(fake)
    asyncio.run(repo.store(user_id=1, login="me", cookie="secret-session"))

    stored = next(iter(fake.store["cookies"].values()))["cookie"]
    assert stored != "secret-session"

    assert asyncio.run(repo.get_valid()) == "secret-session"
    lst = asyncio.run(repo.get_valid_list())
    assert lst[0]["cookie"] == "secret-session"


def test_legacy_plaintext_docs_still_readable(monkeypatch):
    """Docs written before the key existed must keep working."""
    _with_key(monkeypatch)
    fake = FakeClient()
    repo = CookieRepository(fake)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    fake.store["cookies"] = {"old": {
        "user_id": 1, "login": "me", "cookie": "plain-old-cookie",
        "is_valid": True, "provided_at": now,
        "expires_at": now + timedelta(days=1),
    }}
    assert asyncio.run(repo.get_valid()) == "plain-old-cookie"


def test_invalidate_matches_on_decrypted_value(monkeypatch):
    _with_key(monkeypatch)
    fake = FakeClient()
    repo = CookieRepository(fake)
    asyncio.run(repo.store(user_id=1, login="me", cookie="dead-cookie"))
    asyncio.run(repo.store(user_id=2, login="you", cookie="live-cookie"))

    asyncio.run(repo.invalidate("dead-cookie"))

    docs = list(fake.store["cookies"].values())
    by_user = {d["user_id"]: d for d in docs}
    assert by_user[1]["is_valid"] is False
    assert by_user[2]["is_valid"] is True


def test_no_key_falls_back_to_plaintext(monkeypatch):
    monkeypatch.setattr(cc, "COOKIE_ENC_KEY", "")
    fake = FakeClient()
    repo = CookieRepository(fake)
    asyncio.run(repo.store(user_id=1, login="me", cookie="c"))
    stored = next(iter(fake.store["cookies"].values()))["cookie"]
    assert stored == "c"
    assert asyncio.run(repo.get_valid()) == "c"
