"""intra.42 session cookie persistence."""
import logging
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

from repositories.base import BaseRepository
from services.cookie_cipher import decrypt_cookie, encrypt_cookie

logger = logging.getLogger(__name__)


class CookieRepository(BaseRepository):
    async def store(self, user_id, login, cookie):
        logger.info("cookie.store user_id=%s login=%s (cookie redacted)", user_id, login)
        now = datetime.now(timezone.utc)
        await self._db.collection("cookies").add({
            "user_id": user_id,
            "login": login,
            "cookie": encrypt_cookie(cookie),
            "is_valid": True,
            "provided_at": now,
            "expires_at": now + timedelta(days=14),
        })

    async def _valid_docs(self) -> list[dict]:
        """All non-expired valid cookie docs, newest first. The inequality +
        order_by combination needs a composite index Firestore doesn't have
        (the prod poller died on FailedPrecondition every run), so we query the
        single indexed field and filter/sort in memory — the collection holds a
        handful of docs at most."""
        now = datetime.now(timezone.utc)
        query = self._db.collection("cookies").where(
            filter=firestore.FieldFilter("is_valid", "==", True))
        docs = [d.to_dict() async for d in query.stream()]
        docs = [d for d in docs if d.get("expires_at") and d["expires_at"] > now]
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        docs.sort(key=lambda d: d.get("provided_at") or epoch, reverse=True)
        return docs

    async def get_valid(self) -> str | None:
        for data in await self._valid_docs():
            logger.debug("cookie.get_valid: found valid cookie for login=%s",
                         data.get("login"))
            return decrypt_cookie(data.get("cookie"))
        logger.debug("cookie.get_valid: no valid cookie available")
        return None

    async def get_valid_list(self) -> list[dict]:
        """All currently-valid cookies (one most-recent per user) for per-user
        scraping. Returns dicts with user_id, login, cookie."""
        seen: set = set()
        out: list[dict] = []
        for data in await self._valid_docs():
            uid = data.get("user_id")
            if uid in seen:
                continue
            seen.add(uid)
            out.append({
                "user_id": uid,
                "login": data.get("login"),
                "cookie": decrypt_cookie(data.get("cookie")),
            })
        logger.debug("cookie.get_valid_list: %d distinct-user valid cookies", len(out))
        return out

    async def invalidate(self, cookie):
        """Mark every doc holding this (plaintext) cookie invalid. Ciphertext
        is nondeterministic, so we compare after decryption instead of an
        equality query."""
        query = self._db.collection("cookies").where(
            filter=firestore.FieldFilter("is_valid", "==", True))
        count = 0
        async for doc in query.stream():
            if decrypt_cookie(doc.to_dict().get("cookie")) != cookie:
                continue
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
