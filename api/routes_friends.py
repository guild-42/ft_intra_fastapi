"""Mutual friendship API (doc_v2/10 Phase D).

Every endpoint verifies the caller via their 42 access_token (IdentityVerifier,
GET /v2/me) — the access_token is NOT stored; it only proves who is calling, so
a user can only act on their own friendships. The friend graph is the consent
record that lets the friend poller watch presence.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import get_friendship_repo, get_ft_client, get_identity
from repositories.friendship_repo import FriendshipRepository
from services.ft_client import FtClient
from services.identity import IdentityVerifier

logger = logging.getLogger(__name__)
router = APIRouter()


class FriendRequestBody(BaseModel):
    access_token: str
    target_login: str


class FriendRespondBody(BaseModel):
    access_token: str
    other_user_id: int
    accept: bool


class FriendListBody(BaseModel):
    access_token: str


class FriendDeleteBody(BaseModel):
    access_token: str
    other_user_id: int


def _shape(rows: list[dict], me: int) -> dict:
    """Split the caller's friendship docs into incoming/outgoing/accepted, each
    item exposing the OTHER user's id + login."""
    incoming, outgoing, accepted = [], [], []
    for r in rows:
        other_id = r["user_b"] if r["user_a"] == me else r["user_a"]
        other_login = r["login_b"] if r["user_a"] == me else r["login_a"]
        item = {"user_id": other_id, "login": other_login,
                "status": r.get("status")}
        if r.get("status") == "accepted":
            accepted.append(item)
        elif r.get("requester_id") == me:
            outgoing.append(item)
        else:
            incoming.append(item)
    return {"incoming": incoming, "outgoing": outgoing, "accepted": accepted}


@router.post("/api/friends/request")
async def friend_request(
    req: FriendRequestBody,
    identity: IdentityVerifier = Depends(get_identity),
    ft: FtClient = Depends(get_ft_client),
    friends: FriendshipRepository = Depends(get_friendship_repo),
):
    me = await identity.verify(req.access_token)
    target = await ft.get_user(req.target_login)
    if not target or "id" not in target:
        raise HTTPException(status_code=404, detail="Unknown 42 login")
    status = await friends.request(
        requester_id=me["id"], requester_login=me["login"],
        target_id=target["id"], target_login=target.get("login", req.target_login))
    if status == "self":
        raise HTTPException(status_code=400, detail="Cannot friend yourself")
    return {"status": status, "target": {"user_id": target["id"],
                                         "login": target.get("login")}}


@router.post("/api/friends/respond")
async def friend_respond(
    req: FriendRespondBody,
    identity: IdentityVerifier = Depends(get_identity),
    friends: FriendshipRepository = Depends(get_friendship_repo),
):
    me = await identity.verify(req.access_token)
    status = await friends.respond(me["id"], req.other_user_id, req.accept)
    if status == "not_found":
        raise HTTPException(status_code=404, detail="No such request")
    if status == "forbidden":
        raise HTTPException(status_code=403, detail="Cannot accept own request")
    return {"status": status}


@router.post("/api/friends/list")
async def friend_list(
    req: FriendListBody,
    identity: IdentityVerifier = Depends(get_identity),
    friends: FriendshipRepository = Depends(get_friendship_repo),
):
    me = await identity.verify(req.access_token)
    rows = await friends.get_for_user(me["id"])
    return _shape(rows, me["id"])


@router.delete("/api/friends")
async def friend_delete(
    req: FriendDeleteBody,
    identity: IdentityVerifier = Depends(get_identity),
    friends: FriendshipRepository = Depends(get_friendship_repo),
):
    me = await identity.verify(req.access_token)
    removed = await friends.delete(me["id"], req.other_user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="No such friendship")
    return {"status": "deleted"}
