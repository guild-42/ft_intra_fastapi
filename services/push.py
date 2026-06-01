"""FCM push delivery wrapped as an injectable service.

Firebase init is a global, irreversible side effect; keeping it behind a service
lets pollers/routes receive it and tests substitute a no-op implementation."""
import logging
import os

logger = logging.getLogger(__name__)


class PushService:
    def __init__(self):
        self._initialized = False

    def _init_firebase(self):
        if self._initialized:
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
            self._initialized = True
            logger.info("Firebase initialized")
        except Exception:
            logger.exception("Failed to initialize Firebase")

    async def send(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> int:
        logger.info("push.send: %d token(s) title=%r", len(tokens), title)
        self._init_firebase()
        if not self._initialized:
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
