"""Poller bookkeeping (last_run/last_success + arbitrary state fields), plus a
generic collection counter used by the health endpoint."""
import logging
from datetime import datetime, timezone

from google.cloud import firestore

from repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class PollerStateRepository(BaseRepository):
    async def update(self, name: str, success: bool = True):
        now = datetime.now(timezone.utc)
        update = {"last_run": now}
        if success:
            update["last_success"] = now
        await self._db.collection("poller_state").document(name).set(update, merge=True)
        logger.debug("poller_state.update name=%s success=%s", name, success)

    async def get(self, name: str) -> dict | None:
        snap = await self._db.collection("poller_state").document(name).get()
        logger.debug("poller_state.get name=%s found=%s", name, snap.exists)
        return snap.to_dict() if snap.exists else None

    async def save_fields(self, name: str, **fields):
        """Merge arbitrary fields into a poller_state doc (e.g. an active set)."""
        await self._db.collection("poller_state").document(name).set(fields, merge=True)
        logger.debug("poller_state.save_fields name=%s fields=%s", name, list(fields.keys()))

    async def count_collection(self, name: str, **filters) -> int:
        """Returns count of documents in a collection with optional filters.
        Used by the health endpoint to report device/checkin totals."""
        query = self._db.collection(name)
        for field, value in filters.items():
            query = query.where(filter=firestore.FieldFilter(field, "==", value))
        agg = await query.count().get()
        result = int(agg[0][0].value) if agg else 0
        logger.debug("poller_state.count_collection name=%s filters=%s → %d",
                     name, filters, result)
        return result
