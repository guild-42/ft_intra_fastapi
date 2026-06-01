"""Location-based campus check-in persistence.

One document per user, keyed by str(user_id). Identity is always the
access_token-verified 42 user (see routes_checkin)."""
import logging
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

from repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class CheckinRepository(BaseRepository):
    async def upsert(self, user_id, login, campus_id, source="geo",
                     ttl_seconds=10800) -> dict:
        """Mark a user as checked in. Idempotent: re-checking in while already
        active only refreshes the heartbeat/expiry and keeps the original
        checked_in_at. Returns the written document."""
        now = datetime.now(timezone.utc)
        ref = self._db.collection("checkins").document(str(user_id))
        snap = await ref.get()
        already_active = snap.exists and snap.to_dict().get("is_active")

        doc = {
            "user_id": user_id,
            "login": login,
            "campus_id": campus_id,
            "source": source,
            "last_heartbeat": now,
            "expires_at": now + timedelta(seconds=ttl_seconds),
            "is_active": True,
        }
        if not already_active:
            doc["checked_in_at"] = now
        await ref.set(doc, merge=True)
        logger.info("checkin.upsert user_id=%s login=%s campus=%s source=%s "
                    "(already_active=%s ttl=%ds)",
                    user_id, login, campus_id, source, already_active, ttl_seconds)
        return doc

    async def heartbeat(self, user_id, ttl_seconds=10800) -> bool:
        """Extend an active check-in's expiry. No-op (False) if not checked in."""
        now = datetime.now(timezone.utc)
        ref = self._db.collection("checkins").document(str(user_id))
        snap = await ref.get()
        if not snap.exists or not snap.to_dict().get("is_active"):
            logger.debug("checkin.heartbeat user_id=%s: not checked in (no-op)", user_id)
            return False
        await ref.set(
            {"last_heartbeat": now, "expires_at": now + timedelta(seconds=ttl_seconds)},
            merge=True,
        )
        logger.debug("checkin.heartbeat user_id=%s: extended +%ds", user_id, ttl_seconds)
        return True

    async def set_checkout(self, user_id, reason="manual") -> bool:
        """Mark a user as checked out. False if no check-in doc exists."""
        ref = self._db.collection("checkins").document(str(user_id))
        snap = await ref.get()
        if not snap.exists:
            logger.debug("checkin.set_checkout user_id=%s: no doc (no-op)", user_id)
            return False
        await ref.set(
            {
                "is_active": False,
                "checked_out_at": datetime.now(timezone.utc),
                "checkout_reason": reason,
            },
            merge=True,
        )
        logger.info("checkin.set_checkout user_id=%s reason=%s", user_id, reason)
        return True

    async def list_active(self, campus_id=None) -> list[dict]:
        """Currently checked-in users (optionally for one campus). Stale docs whose
        expiry has passed but the sweeper hasn't closed yet are filtered out, so the
        Campus tab never shows phantom presence. Uses equality-only Firestore
        filters (no composite index needed); expiry is checked in memory."""
        now = datetime.now(timezone.utc)
        query = self._db.collection("checkins").where(
            filter=firestore.FieldFilter("is_active", "==", True)
        )
        if campus_id is not None:
            query = query.where(filter=firestore.FieldFilter("campus_id", "==", campus_id))
        out: list[dict] = []
        stale = 0
        async for doc in query.stream():
            d = doc.to_dict()
            exp = d.get("expires_at")
            if exp is not None and exp < now:
                stale += 1
                continue
            out.append(d)
        logger.debug("checkin.list_active campus=%s → %d active (%d stale filtered)",
                     campus_id, len(out), stale)
        return out

    async def expire_stale(self) -> int:
        """Auto-checkout: close active check-ins whose expires_at has passed.
        Equality-only query + in-memory expiry check (no composite index). Returns
        the number of check-ins expired."""
        now = datetime.now(timezone.utc)
        query = self._db.collection("checkins").where(
            filter=firestore.FieldFilter("is_active", "==", True)
        )
        count = 0
        async for doc in query.stream():
            exp = doc.to_dict().get("expires_at")
            if exp is None or exp >= now:
                continue
            await doc.reference.set(
                {"is_active": False, "checked_out_at": now, "checkout_reason": "expired"},
                merge=True,
            )
            count += 1
        if count:
            logger.info("checkin.expire_stale: expired %d stale check-in(s)", count)
        else:
            logger.debug("checkin.expire_stale: none expired")
        return count
