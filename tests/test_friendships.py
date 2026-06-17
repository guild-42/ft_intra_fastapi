"""Mutual friendship repo + routes (doc_v2/10 Phase D): request→accept consent,
reverse-request auto-accept, IDOR (you can only act as yourself), and the friend
poller pushing only to accepted mutual friends."""
import asyncio
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deps import get_friendship_repo, get_ft_client, get_identity
from repositories.friendship_repo import FriendshipRepository
from pollers.friend_poller import FriendPoller
from tests.conftest import FakeClient


# ───── repository ─────


def _repo():
    return FriendshipRepository(FakeClient())


def test_request_then_accept_makes_accepted_edge():
    repo = _repo()
    s1 = asyncio.run(repo.request(1, "a", 2, "b"))
    assert s1 == "pending"
    # The recipient (2) accepts.
    s2 = asyncio.run(repo.respond(2, 1, accept=True))
    assert s2 == "accepted"
    assert asyncio.run(repo.get_accepted_friend_ids(1)) == [2]
    assert asyncio.run(repo.get_accepted_friend_ids(2)) == [1]


def test_reverse_request_auto_accepts():
    repo = _repo()
    asyncio.run(repo.request(1, "a", 2, "b"))
    # 2 independently requests 1 → mutual → accepted without a separate respond.
    s = asyncio.run(repo.request(2, "b", 1, "a"))
    assert s == "accepted"
    assert asyncio.run(repo.get_accepted_friend_ids(2)) == [1]


def test_requester_cannot_accept_own_request():
    repo = _repo()
    asyncio.run(repo.request(1, "a", 2, "b"))
    assert asyncio.run(repo.respond(1, 2, accept=True)) == "forbidden"
    # still pending, not accepted
    assert asyncio.run(repo.get_accepted_friend_ids(1)) == []


def test_decline_and_delete_remove_edge():
    repo = _repo()
    asyncio.run(repo.request(1, "a", 2, "b"))
    assert asyncio.run(repo.respond(2, 1, accept=False)) == "declined"
    assert asyncio.run(repo.get_for_user(1)) == []

    asyncio.run(repo.request(1, "a", 2, "b"))
    asyncio.run(repo.respond(2, 1, accept=True))
    assert asyncio.run(repo.delete(1, 2)) is True
    assert asyncio.run(repo.get_accepted_friend_ids(1)) == []


def test_pair_id_is_order_independent():
    repo = _repo()
    asyncio.run(repo.request(2, "b", 1, "a"))
    # requesting the other direction hits the SAME doc (pending already)
    assert asyncio.run(repo.request(1, "a", 2, "b")) == "accepted"


# ───── routes ─────


def _identity(user_id, login="me"):
    idn = AsyncMock()
    idn.verify = AsyncMock(return_value={"id": user_id, "login": login})
    return idn


def _client(identity, fake, ft=None):
    import api.routes_friends as rf

    app = FastAPI()
    app.include_router(rf.router)
    app.dependency_overrides[get_identity] = lambda: identity
    app.dependency_overrides[get_friendship_repo] = \
        lambda: FriendshipRepository(fake)
    app.dependency_overrides[get_ft_client] = lambda: (ft or AsyncMock())
    return TestClient(app)


def test_request_route_resolves_login_and_creates_pending():
    fake = FakeClient()
    ft = AsyncMock()
    ft.get_user = AsyncMock(return_value={"id": 2, "login": "bob"})
    client = _client(_identity(1, "alice"), fake, ft)
    resp = client.post("/api/friends/request",
                       json={"access_token": "x", "target_login": "bob"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    rows = list(fake.store["friendships"].values())
    assert rows[0]["requester_id"] == 1


def test_request_unknown_login_is_404():
    ft = AsyncMock()
    ft.get_user = AsyncMock(return_value=None)
    client = _client(_identity(1), FakeClient(), ft)
    resp = client.post("/api/friends/request",
                       json={"access_token": "x", "target_login": "ghost"})
    assert resp.status_code == 404


def test_list_route_shapes_incoming_outgoing_accepted():
    fake = FakeClient()
    repo = FriendshipRepository(fake)
    asyncio.run(repo.request(1, "alice", 2, "bob"))     # alice → bob (outgoing for alice)
    asyncio.run(repo.request(3, "carol", 1, "alice"))   # carol → alice (incoming for alice)
    client = _client(_identity(1, "alice"), fake)
    body = client.post("/api/friends/list", json={"access_token": "x"}).json()
    assert [o["login"] for o in body["outgoing"]] == ["bob"]
    assert [i["login"] for i in body["incoming"]] == ["carol"]
    assert body["accepted"] == []


def test_respond_invalid_token_is_401():
    idn = AsyncMock()
    idn.verify = AsyncMock(side_effect=HTTPException(status_code=401))
    client = _client(idn, FakeClient())
    resp = client.post("/api/friends/respond",
                       json={"access_token": "bad", "other_user_id": 2,
                             "accept": True})
    assert resp.status_code == 401


# ───── friend poller ─────


class _FakeState:
    def __init__(self, prev=None):
        self._prev = prev or {}
        self.saved = None
        self.updated = None

    async def get(self, name):
        return {"active_by_campus": self._prev}

    async def save_fields(self, name, **fields):
        self.saved = fields

    async def update(self, name, success):
        self.updated = success


class _FakeFt:
    def __init__(self, locations):
        self._locations = locations

    async def get_campus_active_locations(self, campus_id):
        return self._locations


class _FakePush:
    def __init__(self):
        self.sent = []

    async def send(self, tokens, title, body, data=None):
        self.sent.append({"tokens": tokens, "data": data or {}})
        return len(tokens)


def test_friend_poller_pushes_only_to_accepted_mutual_friends():
    # user 2 logs in; user 1 is 2's accepted friend with a pref_friend device.
    fake = FakeClient()
    repo = FriendshipRepository(fake)
    asyncio.run(repo.request(1, "alice", 2, "bob"))
    asyncio.run(repo.respond(2, 1, accept=True))

    fake.store["devices"] = {
        "tok1": {"user_id": 1, "fcm_token": "tok1", "pref_friend": True},
        "tok3": {"user_id": 3, "fcm_token": "tok3", "pref_friend": True},
    }
    from repositories.device_repo import DeviceRepository

    push = _FakePush()
    poller = FriendPoller(
        device_repo=DeviceRepository(fake),
        friendship_repo=repo,
        state_repo=_FakeState(prev={"26": []}),
        ft_client=_FakeFt([{"user": {"id": 2, "login": "bob"}}]),
        push=push,
    )
    asyncio.run(poller.run())
    assert len(push.sent) == 1
    assert push.sent[0]["tokens"] == ["tok1"]   # only alice, not unrelated user 3
    assert push.sent[0]["data"] == {"type": "friend_online", "user_id": "2"}
