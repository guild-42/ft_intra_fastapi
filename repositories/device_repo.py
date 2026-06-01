"""Device (FCM endpoint + preferences + optional OAuth token) persistence.
Keyed by fcm_token."""
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
                     access_token=None, refresh_token=None,
                     token_expires_at=None,
                     consent_version=None, consented_at=None):
        logger.info(
            "device.upsert user_id=%s login=%s fcm=%s platform=%s prefs="
            "(evalpo=%s,event=%s,review=%s,friend=%s) watch_ids=%d has_token=%s",
            user_id, login, fcm_short(fcm_token), platform,
            pref_evalpo, pref_event, pref_review, pref_friend,
            len(friend_watch_ids or []), refresh_token is not None,
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
        # Token is only stored on the review opt-in path (refresh_token present), so
        # a cookie-only register never persists a review credential.
        if refresh_token is not None:
            doc["access_token"] = access_token
            doc["refresh_token"] = refresh_token
            doc["token_expires_at"] = token_expires_at
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

    async def update_token(self, fcm_token, access_token, token_expires_at,
                           refresh_token=None):
        """Persist a refreshed access token (called by the review poller). The 42
        refresh_token can rotate on use, so update it too when provided."""
        logger.info("device.update_token fcm=%s rotate_refresh=%s",
                    fcm_short(fcm_token), refresh_token is not None)
        update = {
            "access_token": access_token,
            "token_expires_at": token_expires_at,
            "updated_at": datetime.now(timezone.utc),
        }
        if refresh_token is not None:
            update["refresh_token"] = refresh_token
        await self._db.collection("devices").document(fcm_token).set(update, merge=True)

    async def mark_review_seeded(self, fcm_token):
        """Mark a device's review baseline as captured so the first poll after
        opt-in records existing scale_teams without pushing a backlog of alerts."""
        logger.info("device.mark_review_seeded fcm=%s", fcm_short(fcm_token))
        await self._db.collection("devices").document(fcm_token).set(
            {"review_seeded": True}, merge=True,
        )

    async def clear_token(self, fcm_token) -> bool:
        """Remove the stored OAuth token from a device (review opt-out / delete).
        Returns False if the device is unknown."""
        ref = self._db.collection("devices").document(fcm_token)
        snap = await ref.get()
        if not snap.exists:
            logger.warning("device.clear_token: unknown device fcm=%s", fcm_short(fcm_token))
            return False
        await ref.set(
            {
                "access_token": firestore.DELETE_FIELD,
                "refresh_token": firestore.DELETE_FIELD,
                "token_expires_at": firestore.DELETE_FIELD,
                "pref_review": False,
                "updated_at": datetime.now(timezone.utc),
            },
            merge=True,
        )
        logger.info("device.clear_token: cleared token fcm=%s", fcm_short(fcm_token))
        return True

    async def get_with_token(self) -> list[dict]:
        """Devices that opted into review notifications AND have a stored token.
        Firestore can't filter on field existence, so presence is checked in
        memory after the equality filter."""
        query = self._db.collection("devices").where(
            filter=firestore.FieldFilter("pref_review", "==", True)
        )
        out: list[dict] = []
        scanned = 0
        async for doc in query.stream():
            scanned += 1
            d = doc.to_dict()
            if d.get("access_token") and d.get("refresh_token"):
                out.append(d)
        logger.debug("device.get_with_token: %d/%d pref_review devices have tokens",
                     len(out), scanned)
        return out

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

    async def get_watching(self, watched_user_id) -> list[dict]:
        """Devices whose friend watch list contains [watched_user_id] and which
        opted into friend notifications. Used for friend-login fan-out."""
        query = (
            self._db.collection("devices")
            .where(filter=firestore.FieldFilter(
                "friend_watch_ids", "array_contains", watched_user_id))
            .where(filter=firestore.FieldFilter("pref_friend", "==", True))
        )
        out = [d.to_dict() async for d in query.stream()]
        logger.debug("device.get_watching watched_user_id=%s → %d watchers",
                     watched_user_id, len(out))
        return out
