"""Firestore-based persistence."""
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.async_client import AsyncClient

_client: AsyncClient | None = None


def get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = firestore.AsyncClient()
    return _client


async def init_db():
    """Firestore is schemaless, nothing to init."""
    get_client()


# ───── devices ─────

# Maps a notification type to the device preference field that gates it.
PREF_FIELD_BY_TYPE = {
    "evalpo_sale": "pref_evalpo",
    "new_event": "pref_event",
    "review": "pref_review",
    "friend_online": "pref_friend",
}


async def upsert_device(user_id, login, fcm_token, platform="ios", language="en",
                        pref_evalpo=True, pref_event=True,
                        pref_review=True, pref_friend=True,
                        friend_watch_ids=None):
    db = get_client()
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
    ref = db.collection("devices").document(fcm_token)
    snap = await ref.get()
    if not snap.exists:
        doc["created_at"] = now
    await ref.set(doc, merge=True)


async def update_device_prefs(fcm_token, **fields) -> bool:
    """Partial update of a device's preference fields, keyed by fcm_token.
    Only the provided fields are written. Returns False if the device is
    unknown. Used by the lightweight ``POST /api/preferences`` endpoint."""
    db = get_client()
    allowed = {"pref_evalpo", "pref_event", "pref_review",
               "pref_friend", "friend_watch_ids"}
    update = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not update:
        return False
    ref = db.collection("devices").document(fcm_token)
    snap = await ref.get()
    if not snap.exists:
        return False
    update["updated_at"] = datetime.now(timezone.utc)
    await ref.set(update, merge=True)
    return True


async def get_devices_for_notification(notification_type) -> list[dict]:
    """Devices subscribed to a GLOBAL notification type (evalpo / event)."""
    db = get_client()
    field = PREF_FIELD_BY_TYPE.get(notification_type, "pref_event")
    query = db.collection("devices").where(filter=firestore.FieldFilter(field, "==", True))
    docs = query.stream()
    return [d.to_dict() async for d in docs]


async def get_devices_for_user(user_id, pref_field="pref_review") -> list[dict]:
    """Devices belonging to a specific 42 user that opted into [pref_field].
    Used for per-user review notifications."""
    db = get_client()
    query = (
        db.collection("devices")
        .where(filter=firestore.FieldFilter("user_id", "==", user_id))
        .where(filter=firestore.FieldFilter(pref_field, "==", True))
    )
    return [d.to_dict() async for d in query.stream()]


async def get_devices_watching(watched_user_id) -> list[dict]:
    """Devices whose friend watch list contains [watched_user_id] and which
    opted into friend notifications. Used for friend-login fan-out."""
    db = get_client()
    query = (
        db.collection("devices")
        .where(filter=firestore.FieldFilter(
            "friend_watch_ids", "array_contains", watched_user_id))
        .where(filter=firestore.FieldFilter("pref_friend", "==", True))
    )
    return [d.to_dict() async for d in query.stream()]


# ───── cookies ─────

async def store_cookie(user_id, login, cookie):
    db = get_client()
    now = datetime.now(timezone.utc)
    await db.collection("cookies").add({
        "user_id": user_id,
        "login": login,
        "cookie": cookie,
        "is_valid": True,
        "provided_at": now,
        "expires_at": now + timedelta(days=14),
    })


async def get_valid_cookie() -> str | None:
    db = get_client()
    now = datetime.now(timezone.utc)
    query = (
        db.collection("cookies")
        .where(filter=firestore.FieldFilter("is_valid", "==", True))
        .where(filter=firestore.FieldFilter("expires_at", ">", now))
        .order_by("provided_at", direction=firestore.Query.DESCENDING)
        .limit(1)
    )
    async for doc in query.stream():
        data = doc.to_dict()
        return data.get("cookie")
    return None


async def get_valid_cookies() -> list[dict]:
    """All currently-valid cookies (one most-recent per user) for per-user
    scraping. Returns dicts with user_id, login, cookie."""
    db = get_client()
    now = datetime.now(timezone.utc)
    query = (
        db.collection("cookies")
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
    return out


async def invalidate_cookie(cookie):
    db = get_client()
    query = db.collection("cookies").where(filter=firestore.FieldFilter("cookie", "==", cookie))
    async for doc in query.stream():
        await doc.reference.update({"is_valid": False})


# ───── notifications ─────

async def insert_notification(signature, title, body, source_date) -> bool:
    """Returns True if new, False if duplicate."""
    db = get_client()
    ref = db.collection("notifications").document(signature)
    snap = await ref.get()
    if snap.exists:
        return False
    await ref.set({
        "signature": signature,
        "title": title,
        "body": body,
        "source_date": source_date,
        "detected_at": datetime.now(timezone.utc),
        "push_sent_at": None,
    })
    return True


async def get_notifications(page=1, per_page=20) -> list[dict]:
    db = get_client()
    query = (
        db.collection("notifications")
        .order_by("detected_at", direction=firestore.Query.DESCENDING)
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    return [d.to_dict() async for d in query.stream()]


# ───── checkins ─────
#
# Location-based campus check-in (independent of the ubuntu-session locations
# returned by the 42 API). One document per user, keyed by str(user_id).
# Identity is always the access_token-verified 42 user (see routes_checkin).

async def upsert_checkin(user_id, login, campus_id, source="geo",
                         ttl_seconds=10800) -> dict:
    """Mark a user as checked in. Idempotent: re-checking in while already
    active only refreshes the heartbeat/expiry and keeps the original
    checked_in_at. Returns the written document."""
    db = get_client()
    now = datetime.now(timezone.utc)
    ref = db.collection("checkins").document(str(user_id))
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
    return doc


async def heartbeat_checkin(user_id, ttl_seconds=10800) -> bool:
    """Extend an active check-in's expiry. No-op (False) if not checked in."""
    db = get_client()
    now = datetime.now(timezone.utc)
    ref = db.collection("checkins").document(str(user_id))
    snap = await ref.get()
    if not snap.exists or not snap.to_dict().get("is_active"):
        return False
    await ref.set(
        {"last_heartbeat": now, "expires_at": now + timedelta(seconds=ttl_seconds)},
        merge=True,
    )
    return True


async def set_checkout(user_id, reason="manual") -> bool:
    """Mark a user as checked out. False if no check-in doc exists."""
    db = get_client()
    ref = db.collection("checkins").document(str(user_id))
    snap = await ref.get()
    if not snap.exists:
        return False
    await ref.set(
        {
            "is_active": False,
            "checked_out_at": datetime.now(timezone.utc),
            "checkout_reason": reason,
        },
        merge=True,
    )
    return True


async def list_active_checkins(campus_id=None) -> list[dict]:
    """Currently checked-in users (optionally for one campus). Stale docs whose
    expiry has passed but the sweeper hasn't closed yet are filtered out, so the
    Campus tab never shows phantom presence. Uses equality-only Firestore
    filters (no composite index needed); expiry is checked in memory."""
    db = get_client()
    now = datetime.now(timezone.utc)
    query = db.collection("checkins").where(
        filter=firestore.FieldFilter("is_active", "==", True)
    )
    if campus_id is not None:
        query = query.where(filter=firestore.FieldFilter("campus_id", "==", campus_id))
    out: list[dict] = []
    async for doc in query.stream():
        d = doc.to_dict()
        exp = d.get("expires_at")
        if exp is not None and exp < now:
            continue
        out.append(d)
    return out


async def expire_stale_checkins() -> int:
    """Auto-checkout: close active check-ins whose expires_at has passed.
    Equality-only query + in-memory expiry check (no composite index). Returns
    the number of check-ins expired."""
    db = get_client()
    now = datetime.now(timezone.utc)
    query = db.collection("checkins").where(
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
    return count


# ───── poller_state ─────

async def update_poller_state(name: str, success: bool = True):
    db = get_client()
    now = datetime.now(timezone.utc)
    update = {"last_run": now}
    if success:
        update["last_success"] = now
    await db.collection("poller_state").document(name).set(update, merge=True)


async def get_poller_state(name: str) -> dict | None:
    db = get_client()
    snap = await db.collection("poller_state").document(name).get()
    return snap.to_dict() if snap.exists else None


async def save_poller_state_fields(name: str, **fields):
    """Merge arbitrary fields into a poller_state doc (e.g. an active set)."""
    db = get_client()
    await db.collection("poller_state").document(name).set(fields, merge=True)


async def count_collection(name: str, **filters) -> int:
    """Returns count of documents in a collection with optional filters."""
    db = get_client()
    query = db.collection(name)
    for field, value in filters.items():
        query = query.where(filter=firestore.FieldFilter(field, "==", value))
    agg = await query.count().get()
    return int(agg[0][0].value) if agg else 0
