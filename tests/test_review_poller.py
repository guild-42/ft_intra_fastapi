"""Covers the server-side review detector.

The point of this poller is that it wakes a device only when that user's
evaluations actually changed — blind 30-minute wakes both delayed notifications
and burned the iOS silent-push budget. These tests pin the behaviour that makes
it safe to rely on: seed-then-notify, per-user targeting, and no notification
when a lookup fails.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pollers.review_poller import ReviewPoller, _signature  # noqa: E402


def _team(tid, filled=False):
    return {"id": tid, "filled_at": "2026-08-26T10:00:00.000Z" if filled else None}


class _Devices:
    def __init__(self, devices):
        self._d = devices

    async def get_for_notification(self, kind):
        assert kind == "review"
        return self._d


class _State:
    def __init__(self):
        self.doc = {}
        self.updates = []

    async def get(self, name):
        return dict(self.doc)

    async def save_fields(self, name, **fields):
        self.doc.update(fields)

    async def update(self, name, success=True):
        self.updates.append(success)


class _Ft:
    def __init__(self, by_user):
        self.by_user = by_user
        self.calls = []

    async def get_user_scale_teams(self, uid):
        self.calls.append(uid)
        return self.by_user.get(uid)


class _Push:
    def __init__(self):
        self.silent = []

    async def send_silent(self, tokens, data):
        self.silent.append((tuple(tokens), data))
        return len(tokens)


def _poller(devices, ft, push, state=None):
    return ReviewPoller(device_repo=_Devices(devices), state_repo=state or _State(),
                        ft_client=ft, push=push)


DEV = [{"user_id": 1, "fcm_token": "tok-a"}]


@pytest.mark.asyncio
async def test_first_run_seeds_without_notifying():
    """Otherwise every pre-existing review would fire on first deploy."""
    push, ft, state = _Push(), _Ft({1: [_team(10), _team(11)]}), _State()
    await _poller(DEV, ft, push, state).run()
    assert push.silent == []
    assert state.doc["seen_1"] == ["10:scheduled", "11:scheduled"]


@pytest.mark.asyncio
async def test_a_new_booking_wakes_that_user():
    push, state = _Push(), _State()
    state.doc["seen_1"] = ["10:scheduled"]
    ft = _Ft({1: [_team(10), _team(12)]})
    await _poller(DEV, ft, push, state).run()
    assert push.silent == [(("tok-a",), {"type": "eval_wake"})]


@pytest.mark.asyncio
async def test_no_change_sends_nothing():
    """The whole reason this exists: don't spend silent pushes on nothing."""
    push, state = _Push(), _State()
    state.doc["seen_1"] = ["10:scheduled"]
    await _poller(DEV, _Ft({1: [_team(10)]}), push, state).run()
    assert push.silent == []


@pytest.mark.asyncio
async def test_grading_an_existing_review_counts_as_a_change():
    push, state = _Push(), _State()
    state.doc["seen_1"] = ["10:scheduled"]
    await _poller(DEV, _Ft({1: [_team(10, filled=True)]}), push, state).run()
    assert len(push.silent) == 1


@pytest.mark.asyncio
async def test_failed_lookup_does_not_notify_or_clobber_state():
    """None means 'couldn't look', not 'nothing there' — diffing against an
    empty list would wipe the baseline and fire on everything next tick."""
    push, state = _Push(), _State()
    state.doc["seen_1"] = ["10:scheduled"]
    await _poller(DEV, _Ft({1: None}), push, state).run()
    assert push.silent == []
    assert state.doc["seen_1"] == ["10:scheduled"]


@pytest.mark.asyncio
async def test_only_the_affected_user_is_woken():
    devices = [{"user_id": 1, "fcm_token": "tok-a"},
               {"user_id": 2, "fcm_token": "tok-b"}]
    push, state = _Push(), _State()
    state.doc.update({"seen_1": ["10:scheduled"], "seen_2": ["20:scheduled"]})
    ft = _Ft({1: [_team(10)], 2: [_team(20), _team(21)]})
    await _poller(devices, ft, push, state).run()
    assert push.silent == [(("tok-b",), {"type": "eval_wake"})]


@pytest.mark.asyncio
async def test_all_of_a_users_devices_are_woken_once():
    devices = [{"user_id": 1, "fcm_token": "tok-a"},
               {"user_id": 1, "fcm_token": "tok-b"}]
    push, state = _Push(), _State()
    state.doc["seen_1"] = ["10:scheduled"]
    await _poller(devices, _Ft({1: [_team(10), _team(11)]}), push, state).run()
    assert len(push.silent) == 1
    assert set(push.silent[0][0]) == {"tok-a", "tok-b"}


@pytest.mark.asyncio
async def test_devices_without_a_user_id_are_skipped():
    devices = [{"fcm_token": "orphan"}, {"user_id": 1, "fcm_token": "tok-a"}]
    ft = _Ft({1: [_team(10)]})
    await _poller(devices, ft, _Push()).run()
    assert ft.calls == [1]


def test_signature_distinguishes_scheduled_from_filled():
    assert _signature(_team(1)) == "1:scheduled"
    assert _signature(_team(1, filled=True)) == "1:filled"
    assert _signature({}) is None
