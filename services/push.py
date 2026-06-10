"""FCM push delivery wrapped as an injectable service.

Firebase init is a global, irreversible side effect; keeping it behind a service
lets pollers/routes receive it and tests substitute a no-op implementation."""
import asyncio
import logging
import os

from repositories.base import fcm_short

logger = logging.getLogger(__name__)


class PushService:
    def __init__(self, device_repo_factory=None):
        # Factory (not instance): the Firestore client doesn't exist yet when
        # the singleton is constructed at import time.
        self._initialized = False
        self._device_repo_factory = device_repo_factory

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
            # The admin SDK call is synchronous HTTP — run it off the event
            # loop so pollers/routes aren't blocked for the round-trip.
            response = await asyncio.to_thread(
                messaging.send_each_for_multicast, message
            )
            logger.info(
                "FCM: %d success, %d failure",
                response.success_count,
                response.failure_count,
            )
            if response.failure_count:
                await self._cleanup_invalid(messaging, tokens, response)
            return response.success_count
        except Exception:
            logger.exception("FCM send failed")
            return 0

    async def _cleanup_invalid(self, messaging, tokens, response):
        """Delete devices whose FCM token FCM reports as unregistered
        (app uninstalled / token rotated) so we stop pushing to them."""
        if self._device_repo_factory is None:
            return
        dead = [
            token
            for token, resp in zip(tokens, response.responses)
            if resp.exception is not None
            and isinstance(resp.exception, messaging.UnregisteredError)
        ]
        if not dead:
            return
        repo = self._device_repo_factory()
        for token in dead:
            logger.info("push: removing unregistered device fcm=%s", fcm_short(token))
            await repo.delete_by_fcm(token)
