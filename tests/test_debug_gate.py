"""Debug-endpoint gate (P0-3): /api/test-* and /api/poll-now must 404 unless
DEBUG_ENDPOINTS_ENABLED is set."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
import api.routes_test as rt
import api.routes_register as rr
from deps import get_device_repo


class _NoDevices:
    async def get_for_notification(self, _type):
        return []


def _client():
    app = FastAPI()
    app.include_router(rt.router)
    app.include_router(rr.router)
    app.dependency_overrides[get_device_repo] = lambda: _NoDevices()
    return TestClient(app)


def test_debug_endpoints_hidden_by_default(monkeypatch):
    monkeypatch.setattr(config, "DEBUG_ENDPOINTS_ENABLED", False)
    client = _client()
    assert client.post("/api/test-push").status_code == 404
    assert client.post("/api/test-notification").status_code == 404
    assert client.post("/api/poll-now").status_code == 404


def test_debug_endpoints_reachable_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "DEBUG_ENDPOINTS_ENABLED", True)
    client = _client()
    # Past the gate; fails later for lack of real deps — anything but 404 is
    # proof the gate opened. test-push with no devices returns 200.
    resp = client.post("/api/test-push")
    assert resp.status_code != 404


def test_test_push_rejects_unknown_type(monkeypatch):
    monkeypatch.setattr(config, "DEBUG_ENDPOINTS_ENABLED", True)
    client = _client()
    assert client.post("/api/test-push?type=bogus").status_code == 400


def test_test_push_review_payload_matches_poller(monkeypatch):
    monkeypatch.setattr(config, "DEBUG_ENDPOINTS_ENABLED", True)
    client = _client()
    resp = client.post("/api/test-push?type=review")
    assert resp.status_code == 200
    assert resp.json()["type"] == "review"
