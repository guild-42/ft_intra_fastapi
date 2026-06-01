"""Detected-notification persistence (dedup by signature + pagination)."""
import logging
from datetime import datetime, timezone

from google.cloud import firestore

from repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class NotificationRepository(BaseRepository):
    async def insert(self, signature, title, body, source_date) -> bool:
        """Returns True if new, False if duplicate."""
        ref = self._db.collection("notifications").document(signature)
        snap = await ref.get()
        if snap.exists:
            logger.debug("notification.insert: duplicate sig=%s title=%r", signature, title)
            return False
        await ref.set({
            "signature": signature,
            "title": title,
            "body": body,
            "source_date": source_date,
            "detected_at": datetime.now(timezone.utc),
            "push_sent_at": None,
        })
        logger.info("notification.insert: NEW sig=%s title=%r", signature, title)
        return True

    async def get_page(self, page=1, per_page=20) -> list[dict]:
        query = (
            self._db.collection("notifications")
            .order_by("detected_at", direction=firestore.Query.DESCENDING)
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        out = [d.to_dict() async for d in query.stream()]
        logger.debug("notification.get_page page=%d per_page=%d → %d items",
                     page, per_page, len(out))
        return out
