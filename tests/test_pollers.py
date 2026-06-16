"""Poller logic without network/Firestore: the events poller's diff+push of
public campus events, and the eval "alarm clock" wake push. No cookie scraping
and no server-held 42 token (doc_v2/10)."""
import asyncio

from pollers.events_poller import EventsPoller
from pollers.eval_wake_poller import EvalWakePoller


# ───── fakes ─────


class FakeNotificationRepo:
    def __init__(self):
        self.seen = set()
        self.pushed_sigs = []

    async def insert(self, signature, title, body, source_date):
        if signature in self.seen:
            return False
        self.seen.add(signature)
        return True

    async def mark_pushed(self, signature):
        self.pushed_sigs.append(signature)


class FakeDeviceRepo:
    def __init__(self, devices=None):
        self.devices = devices or []

    async def get_for_notification(self, ntype):
        return self.devices


class FakeState:
    def __init__(self):
        self.updates = []

    async def update(self, name, success):
        self.updates.append((name, success))


class FakeFtClient:
    def __init__(self, events=None):
        self._events = events or []

    async def get_campus_events(self, campus_id):
        return self._events


class FakePush:
    def __init__(self):
        self.sent = []
        self.silent = []

    async def send(self, tokens, title, body, data=None):
        self.sent.append({"tokens": tokens, "title": title, "data": data or {}})
        return len(tokens)

    async def send_silent(self, tokens, data):
        self.silent.append({"tokens": tokens, "data": data})
        return len(tokens)


def _event(eid, name="AI workshop"):
    return {"id": eid, "name": name, "kind": "workshop",
            "location": "cluster 1", "begin_at": "2026-06-11T09:00:00Z"}


# ───── events poller ─────


def test_events_poller_pushes_new_event_once():
    notif = FakeNotificationRepo()
    devices = FakeDeviceRepo([{"fcm_token": "tok1"}])
    push = FakePush()
    poller = EventsPoller(
        notification_repo=notif, device_repo=devices,
        state_repo=FakeState(), ft_client=FakeFtClient([_event(10)]), push=push,
    )
    asyncio.run(poller.run())
    assert len(push.sent) == 1
    assert push.sent[0]["data"] == {"type": "new_event", "event_id": "10"}
    assert notif.pushed_sigs == ["event:26:10"]

    # Same event next cycle → dedup, no second push.
    asyncio.run(poller.run())
    assert len(push.sent) == 1


def test_events_poller_no_devices_skips_push():
    notif = FakeNotificationRepo()
    push = FakePush()
    poller = EventsPoller(
        notification_repo=notif, device_repo=FakeDeviceRepo([]),
        state_repo=FakeState(), ft_client=FakeFtClient([_event(11)]), push=push,
    )
    asyncio.run(poller.run())
    assert push.sent == []
    # Signature is still recorded so it won't re-announce once a device appears.
    assert "event:26:11" in notif.seen


# ───── eval wake poller ─────


def test_eval_wake_sends_contentless_silent_push_to_pref_review():
    devices = FakeDeviceRepo([{"fcm_token": "a"}, {"fcm_token": "b"}])
    push = FakePush()
    poller = EvalWakePoller(
        device_repo=devices, state_repo=FakeState(), push=push,
    )
    asyncio.run(poller.run())
    assert len(push.silent) == 1
    assert push.silent[0]["tokens"] == ["a", "b"]
    assert push.silent[0]["data"] == {"type": "eval_wake"}
    # never sends a content-bearing push (no 42 data leaves the server)
    assert push.sent == []


def test_eval_wake_no_devices_no_push():
    push = FakePush()
    poller = EvalWakePoller(
        device_repo=FakeDeviceRepo([]), state_repo=FakeState(), push=push,
    )
    asyncio.run(poller.run())
    assert push.silent == []
