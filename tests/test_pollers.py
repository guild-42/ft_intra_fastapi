"""Poller logic without network/Firestore: HTML parsing + classification for
the global notification poller, and the seed-then-push lifecycle of the review
poller (B-RP01–04)."""
import asyncio

from pollers.notification_poller import (
    NotificationPoller,
    classify_notification,
    parse_notifications_html,
)
from pollers.review_poller import ReviewPoller


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
        self.seeded = []
        self.cleared = []

    async def get_for_notification(self, ntype):
        return self.devices

    async def mark_review_seeded(self, fcm_token):
        self.seeded.append(fcm_token)
        for d in self.devices:
            if d["fcm_token"] == fcm_token:
                d["review_seeded"] = True

    async def clear_token(self, fcm_token):
        self.cleared.append(fcm_token)
        return True


class FakePush:
    def __init__(self):
        self.sent = []

    async def send(self, tokens, title, body, data=None):
        self.sent.append({"tokens": tokens, "title": title, "data": data or {}})
        return len(tokens)


# ───── notification poller ─────


SAMPLE_HTML = """
<ul>
  <li class="notification-item">
    <h4 class="notification--title">Evaluation points sale</h4>
    <span data-long-date="2026-06-10T10:00:00Z"></span>
    <div class="notification-item--body">Evaluation points sale 50% off today!</div>
  </li>
  <li class="notification-item">
    <h4 class="notification--title">New event: AI workshop</h4>
    <span data-long-date="2026-06-11T09:00:00Z"></span>
    <div class="notification-item--body">Join us in cluster 1</div>
  </li>
</ul>
"""


def test_parse_notifications_html_extracts_items():
    items = parse_notifications_html(SAMPLE_HTML)
    assert len(items) == 2
    assert items[0]["title"] == "Evaluation points sale"
    # title prefix is stripped from the body
    assert items[0]["body"] == "50% off today!"
    assert items[0]["source_date"] == "2026-06-10T10:00:00Z"
    assert items[0]["signature"] != items[1]["signature"]


def test_classify_notification_types():
    assert classify_notification("Evaluation points sale") == "evalpo_sale"
    assert classify_notification("Someone booked a slot") == "review"
    assert classify_notification("You have an evaluation tomorrow") == "review"
    assert classify_notification("New event: AI workshop") == "new_event"


def test_notify_pushes_global_types_and_marks_pushed():
    notif_repo = FakeNotificationRepo()
    devices = FakeDeviceRepo([{"fcm_token": "tok1"}])
    push = FakePush()
    poller = NotificationPoller(
        cookie_repo=None, notification_repo=notif_repo,
        device_repo=devices, state_repo=None, push=push,
    )
    changes = [
        {"signature": "s1", "title": "Evaluation points sale",
         "body": "", "source_date": "d"},
        # review items belong to ReviewPoller — must NOT be pushed here
        {"signature": "s2", "title": "Someone booked a slot",
         "body": "", "source_date": "d"},
    ]
    asyncio.run(poller.notify(changes))
    assert len(push.sent) == 1
    assert push.sent[0]["data"]["type"] == "evalpo_sale"
    assert notif_repo.pushed_sigs == ["s1"]


# ───── review poller ─────


def _scale_team(tid, filled=False):
    return {
        "id": tid,
        "filled_at": "2026-06-10T12:00:00Z" if filled else None,
        "final_mark": 100 if filled else None,
        "begin_at": "2026-06-10T11:00:00Z",
        "team": {"name": "libft"},
        "correcteds": [{"login": "peer"}],
        "corrector": {"login": "peer"},
    }


def _make_review_poller(devices, fetch_results):
    """fetch_results: dict path -> list (or None for 401)."""
    notif_repo = FakeNotificationRepo()
    device_repo = FakeDeviceRepo(devices)
    push = FakePush()
    poller = ReviewPoller(
        device_repo=device_repo, notification_repo=notif_repo,
        state_repo=None, push=push,
    )

    async def fake_fetch(access_token, path):
        return fetch_results[path]

    poller._fetch = fake_fetch
    return poller, notif_repo, device_repo, push


def _device(seeded):
    return {
        "user_id": 1, "login": "me", "fcm_token": "tokA",
        "access_token": "acc", "review_seeded": seeded,
    }


def test_first_poll_seeds_baseline_without_pushing():
    """B-RP01: opt-in must not dump a backlog of existing scale_teams."""
    poller, _, device_repo, push = _make_review_poller(
        [_device(seeded=False)],
        {"as_corrector": [_scale_team(10)], "as_corrected": []},
    )
    asyncio.run(poller._run_for_device(device_repo.devices[0]))
    assert push.sent == []
    assert device_repo.seeded == ["tokA"]


def test_new_scale_team_pushes_after_seeding():
    """B-RP02: a scale_team appearing after the baseline pushes exactly once."""
    poller, _, device_repo, push = _make_review_poller(
        [_device(seeded=True)],
        {"as_corrector": [], "as_corrected": [_scale_team(11)]},
    )
    asyncio.run(poller._run_for_device(device_repo.devices[0]))
    assert len(push.sent) == 1
    assert push.sent[0]["title"] == "Evaluation scheduled"
    assert push.sent[0]["data"] == {"type": "review", "scale_team_id": "11"}

    # Same state on the next poll → dedup, no second push.
    asyncio.run(poller._run_for_device(device_repo.devices[0]))
    assert len(push.sent) == 1


def test_filled_result_notifies_again_as_new_state():
    """B-RP03: scheduled→filled is a state change, so it notifies once more."""
    fetch_results = {"as_corrector": [_scale_team(12)], "as_corrected": []}
    poller, _, device_repo, push = _make_review_poller(
        [_device(seeded=True)], fetch_results,
    )
    asyncio.run(poller._run_for_device(device_repo.devices[0]))
    fetch_results["as_corrector"] = [_scale_team(12, filled=True)]
    asyncio.run(poller._run_for_device(device_repo.devices[0]))
    assert [p["title"] for p in push.sent] == [
        "Evaluation scheduled", "Evaluation result",
    ]


def test_revoked_token_clears_credentials():
    """B-RP04: persistent 401 + failed refresh clears the stored token."""
    poller, _, device_repo, push = _make_review_poller(
        [_device(seeded=True)],
        {"as_corrector": None, "as_corrected": None},
    )

    async def failed_refresh(device):
        return None

    poller._refresh_token = failed_refresh
    asyncio.run(poller._run_for_device(device_repo.devices[0]))
    assert device_repo.cleared == ["tokA"]
    assert push.sent == []
