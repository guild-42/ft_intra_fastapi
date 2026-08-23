"""Device (FCM endpoint + notification preferences) persistence, keyed by
fcm_token. The server intentionally stores NO 42 OAuth token (doc_v2/10): the
user token lives only on the device, so this repo holds fcm_token + prefs +
consent record."""
import logging
from datetime import datetime, timezone

from google.cloud import firestore

from repositories.base import BaseRepository, fcm_short

logger = logging.getLogger(__name__)

# Maps a notification type to the device preference field that gates it.
PREF_FIELD_BY_TYPE = {
    "evalpo_sale": "pref_evalpo",
    "new_event": "pref_event",
    "review": "pref_review",
    "friend_online": "pref_friend",
}


class DeviceRepository(BaseRepository):
    async def upsert(self, user_id, login, fcm_token, platform="ios", language="en",
                     pref_evalpo=True, pref_event=True,
                     pref_review=True, pref_friend=True,
                     friend_watch_ids=None,
                     consent_version=None, consented_at=None):
        logger.info(
            "device.upsert user_id=%s login=%s fcm=%s platform=%s prefs="
            "(evalpo=%s,event=%s,review=%s,friend=%s) watch_ids=%d",
            user_id, login, fcm_short(fcm_token), platform,
            pref_evalpo, pref_event, pref_review, pref_friend,
            len(friend_watch_ids or []),
        )
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user_id,
            "login": login,
            "fcm_token": fcm_token,
            "platform": platform,
            "language": language,
            "pref_evalpo": pref_evalpo,
            "pref_event": pref_event,
            "pref_review": pref_review,
            "pref_friend": pref_friend,
            "friend_watch_ids": friend_watch_ids or [],
            "updated_at": now,
        }
        if consent_version is not None:
            doc["consent_version"] = consent_version
            doc["consented_at"] = consented_at
        ref = self._db.collection("devices").document(fcm_token)
        snap = await ref.get()
        if not snap.exists:
            doc["created_at"] = now
            logger.info("device.upsert: creating new device fcm=%s", fcm_short(fcm_token))
        else:
            logger.debug("device.upsert: updating existing device fcm=%s", fcm_short(fcm_token))
        await ref.set(doc, merge=True)

    async def get_by_fcm(self, fcm_token) -> dict | None:
        snap = await self._db.collection("devices").document(fcm_token).get()
        logger.debug("device.get_by_fcm fcm=%s found=%s", fcm_short(fcm_token), snap.exists)
        return snap.to_dict() if snap.exists else None

    async def delete_by_fcm(self, fcm_token):
        """Remove a device document entirely (FCM reported the token as
        unregistered — app uninstalled or token rotated)."""
        logger.info("device.delete_by_fcm fcm=%s", fcm_short(fcm_token))
        await self._db.collection("devices").document(fcm_token).delete()

    async def update_prefs(self, fcm_token, **fields) -> bool:
        """Partial update of a device's preference fields, keyed by fcm_token.
        Only the provided fields are written. Returns False if the device is
        unknown. Used by the lightweight ``POST /api/preferences`` endpoint."""
        allowed = {"pref_evalpo", "pref_event", "pref_review",
                   "pref_friend", "friend_watch_ids"}
        update = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not update:
            logger.warning("device.update_prefs: no valid fields for fcm=%s", fcm_short(fcm_token))
            return False
        ref = self._db.collection("devices").document(fcm_token)
        snap = await ref.get()
        if not snap.exists:
            logger.warning("device.update_prefs: unknown device fcm=%s", fcm_short(fcm_token))
            return False
        update["updated_at"] = datetime.now(timezone.utc)
        await ref.set(update, merge=True)
        logger.info("device.update_prefs fcm=%s fields=%s",
                    fcm_short(fcm_token), list(update.keys()))
        return True

    async def get_for_notification(self, notification_type) -> list[dict]:
        """Devices subscribed to a GLOBAL notification type (evalpo / event)."""
        field = PREF_FIELD_BY_TYPE.get(notification_type, "pref_event")
        query = self._db.collection("devices").where(
            filter=firestore.FieldFilter(field, "==", True))
        out = [d.to_dict() async for d in query.stream()]
        logger.debug("device.get_for_notification type=%s (%s) → %d devices",
                     notification_type, field, len(out))
        return out

    async def get_all_for_user(self, user_id) -> list[dict]:
        """Every device for a user, regardless of notification prefs. Used for
        operational alerts (credential expiry) that aren't user-facing prefs."""
        query = self._db.collection("devices").where(
            filter=firestore.FieldFilter("user_id", "==", user_id)
        )
        out = [d.to_dict() async for d in query.stream()]
        logger.debug("device.get_all_for_user user_id=%s → %d devices", user_id, len(out))
        return out

    async def get_for_user(self, user_id, pref_field="pref_review") -> list[dict]:
        """Devices belonging to a specific 42 user that opted into [pref_field]."""
        query = (
            self._db.collection("devices")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .where(filter=firestore.FieldFilter(pref_field, "==", True))
        )
        out = [d.to_dict() async for d in query.stream()]
        logger.debug("device.get_for_user user_id=%s pref=%s → %d devices",
                     user_id, pref_field, len(out))
        return out
