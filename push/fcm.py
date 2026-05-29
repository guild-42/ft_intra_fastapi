import logging
import os

logger = logging.getLogger(__name__)

_firebase_initialized = False


def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path:
        logger.warning("GOOGLE_APPLICATION_CREDENTIALS not set, FCM disabled")
        return
    try:
        import firebase_admin
        from firebase_admin import credentials
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        logger.info("Firebase initialized")
    except Exception:
        logger.exception("Failed to initialize Firebase")


async def send_push(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> int:
    _init_firebase()
    if not _firebase_initialized:
        logger.warning("Firebase not initialized, skipping push")
        return 0

    from firebase_admin import messaging

    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
    )

    try:
        response = messaging.send_each_for_multicast(message)
        logger.info(
            "FCM: %d success, %d failure",
            response.success_count,
            response.failure_count,
        )
        return response.success_count
    except Exception:
        logger.exception("FCM send failed")
        return 0
