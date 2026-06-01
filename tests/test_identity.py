"""IdentityVerifier — the single 42 /me anti-impersonation boundary (B2).

Demonstrates the seam: the 42 API is mocked at one point (httpx in
services.identity) instead of being copy-pasted across routes."""
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.identity as identity_mod  # noqa: E402
from services.identity import IdentityVerifier  # noqa: E402


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient; returns a preconfigured response."""
    resp: _FakeResp = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        return type(self).resp


def _patch_http(monkeypatch, status, payload):
    _FakeAsyncClient.resp = _FakeResp(status, payload)
    monkeypatch.setattr(identity_mod.httpx, "AsyncClient", _FakeAsyncClient)


def test_verify_returns_user_on_200(monkeypatch):
    _patch_http(monkeypatch, 200, {"id": 42, "login": "ssekikaw"})

    import asyncio
    user = asyncio.run(IdentityVerifier().verify("good-token"))

    assert user == {"id": 42, "login": "ssekikaw"}


def test_verify_raises_401_on_bad_token(monkeypatch):
    _patch_http(monkeypatch, 401, {})

    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.run(IdentityVerifier().verify("bad-token"))

    assert exc.value.status_code == 401
