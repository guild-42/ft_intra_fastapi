"""Mutual friendship persistence (doc_v2/10 Phase D).

A friendship is an UNDIRECTED edge between two 42 users, requiring BOTH parties'
consent (request → accept) so the server can defensibly watch their presence
(API GTU Art 4.1). Stored keyed by the sorted id pair so the edge is unique
regardless of who requested.

doc id   = "{min_id}_{max_id}"
fields   = user_a(min), user_b(max), login_a, login_b, requester_id,
           status: pending|accepted, created_at, accepted_at
"""
import logging
from datetime import datetime, timezone

from google.cloud import firestore

from repositories.base import BaseRepository

logger = logging.getLogger(__name__)

_COLL = "friendships"


class FriendshipRepository(BaseRepository):
    @staticmethod
    def _pair_id(a, b) -> str:
        lo, hi = sorted((int(a), int(b)))
        return f"{lo}_{hi}"

    async def request(self, requester_id, requester_login,
                      target_id, target_login) -> str:
        """Create a pending request. If the target had already requested the
        requester (reverse pending), this accepts it. Returns the resulting
        status: 'accepted' | 'pending' | 'already_friends'."""
        requester_id, target_id = int(requester_id), int(target_id)
        if requester_id == target_id:
            return "self"
        ref = self._db.collection(_COLL).document(
            self._pair_id(requester_id, target_id))
        snap = await ref.get()
        now = datetime.now(timezone.utc)
        if snap.exists:
            data = snap.to_dict() or {}
            if data.get("status") == "accepted":
                return "already_friends"
            # A pending edge exists. If the OTHER party opened it, this is a
            # mutual confirmation → accept.
            if data.get("requester_id") != requester_id:
                await ref.set({"status": "accepted", "accepted_at": now}, merge=True)
                logger.info("friendship.request: mutual → accepted %s↔%s",
                            requester_id, target_id)
                return "accepted"
            return "pending"
        lo, hi = sorted((requester_id, target_id))
        login_lo, login_hi = ((requester_login, target_login)
                              if requester_id == lo
                              else (target_login, requester_login))
        await ref.set({
            "user_a": lo, "user_b": hi,
            "login_a": login_lo, "login_b": login_hi,
            "requester_id": requester_id,
            "status": "pending",
            "created_at": now,
        })
        logger.info("friendship.request: pending %s→%s", requester_id, target_id)
        return "pending"

    async def respond(self, user_id, other_id, accept: bool) -> str:
        """The recipient accepts/declines a pending request. The original
        requester may call with accept=False to cancel. Returns
        'accepted'|'declined'|'cancelled'|'forbidden'|'not_found'."""
        user_id, other_id = int(user_id), int(other_id)
        ref = self._db.collection(_COLL).document(self._pair_id(user_id, other_id))
        snap = await ref.get()
        if not snap.exists:
            return "not_found"
        data = snap.to_dict() or {}
        is_requester = data.get("requester_id") == user_id
        if is_requester:
            # Requester can only cancel their own outstanding request.
            if accept:
                return "forbidden"
            await ref.delete()
            return "cancelled"
        if accept:
            await ref.set(
                {"status": "accepted",
                 "accepted_at": datetime.now(timezone.utc)},
                merge=True)
            logger.info("friendship.respond: accepted %s↔%s", user_id, other_id)
            return "accepted"
        await ref.delete()
        return "declined"

    async def delete(self, user_id, other_id) -> bool:
        ref = self._db.collection(_COLL).document(self._pair_id(user_id, other_id))
        snap = await ref.get()
        if not snap.exists:
            return False
        await ref.delete()
        logger.info("friendship.delete: %s↔%s", int(user_id), int(other_id))
        return True

    async def get_for_user(self, user_id) -> list[dict]:
        """All friendship docs involving [user_id] (pending + accepted), each
        annotated with `id` (doc id). Firestore has no OR, so query both id
        positions and merge."""
        uid = int(user_id)
        out: dict[str, dict] = {}
        for field in ("user_a", "user_b"):
            query = self._db.collection(_COLL).where(
                filter=firestore.FieldFilter(field, "==", uid))
            async for snap in query.stream():
                d = snap.to_dict() or {}
                d["id"] = snap.id
                out[snap.id] = d
        return list(out.values())

    async def get_accepted_friend_ids(self, user_id) -> list[int]:
        """The 42 user ids that [user_id] is accepted-friends with (for
        presence/push fan-out)."""
        uid = int(user_id)
        ids: list[int] = []
        for row in await self.get_for_user(uid):
            if row.get("status") != "accepted":
                continue
            ids.append(row["user_b"] if row["user_a"] == uid else row["user_a"])
        return ids
