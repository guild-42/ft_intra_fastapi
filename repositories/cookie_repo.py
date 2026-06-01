"""intra.42 session cookie persistence."""
import logging
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

from repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class CookieRepository(BaseRepository):
    async def store(self, user_id, login, cookie):
        logger.info("cookie.store user_id=%s login=%s (cookie redacted)", user_id, login)
        now = datetime.now(timezone.utc)
        await self._db.collection("cookies").add({
            "user_id": user_id,
            "login": login,
            "cookie": cookie,
            "is_valid": True,
            "provided_at": now,
            "expires_at": now + timedelta(days=14),
        })

    async def get_valid(self) -> str | None:
        now = datetime.now(timezone.utc)
        query = (
            self._db.collection("cookies")
            .where(filter=firestore.FieldFilter("is_valid", "==", True))
            .where(filter=firestore.FieldFilter("expires_at", ">", now))
            .order_by("provided_at", direction=firestore.Query.DESCENDING)
            .limit(1)
        )
        async for doc in query.stream():
            data = doc.to_dict()
            logger.debug("cookie.get_valid: found valid cookie for login=%s",
                         data.get("login"))
            return data.get("cookie")
        logger.debug("cookie.get_valid: no valid cookie available")
        return None

    async def get_valid_list(self) -> list[dict]:
        """All currently-valid cookies (one most-recent per user) for per-user
        scraping. Returns dicts with user_id, login, cookie."""
        now = datetime.now(timezone.utc)
        query = (
            self._db.collection("cookies")
            .where(filter=firestore.FieldFilter("is_valid", "==", True))
            .where(filter=firestore.FieldFilter("expires_at", ">", now))
            .order_by("provided_at", direction=firestore.Query.DESCENDING)
        )
        seen: set = set()
        out: list[dict] = []
        async for doc in query.stream():
            data = doc.to_dict()
            uid = data.get("user_id")
            if uid in seen:
                continue
            seen.add(uid)
            out.append({
                "user_id": uid,
                "login": data.get("login"),
                "cookie": data.get("cookie"),
            })
        logger.debug("cookie.get_valid_list: %d distinct-user valid cookies", len(out))
        return out

    async def invalidate(self, cookie):
        query = self._db.collection("cookies").where(
            filter=firestore.FieldFilter("cookie", "==", cookie))
        count = 0
        async for doc in query.stream():
            await doc.reference.update({"is_valid": False})
            count += 1
        logger.info("cookie.invalidate: invalidated %d cookie doc(s)", count)

    async def delete_user(self, user_id) -> int:
        """Hard-delete all stored cookies for a user (cookie opt-out / delete).
        Returns the number of cookie documents removed."""
        query = self._db.collection("cookies").where(
            filter=firestore.FieldFilter("user_id", "==", user_id)
        )
        count = 0
        async for doc in query.stream():
            await doc.reference.delete()
            count += 1
        logger.info("cookie.delete_user user_id=%s removed=%d", user_id, count)
        return count
