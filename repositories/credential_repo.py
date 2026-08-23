"""42 OAuth credential storage.

Why Firestore and not env: 42 expires the app's client_secret on a fixed date
(and pre-generates the replacement ~7 days earlier). With the secret baked into
an env file, every rotation meant ssh + edit + restart, and a missed rotation
took the whole app down with no warning — which is exactly what happened on
2026-06-30 and again on 2026-08-22.

Holding it here lets the running process pick up a new secret without a restart,
and lets the *next* secret be staged in advance so the switchover needs no human
at the moment of expiry. Secrets are encrypted at rest (see secret_cipher).
"""
import logging
from datetime import datetime, timezone

from repositories.base import BaseRepository
from services.secret_cipher import decrypt, encrypt

logger = logging.getLogger(__name__)

_COLLECTION = "credentials"
_DOC = "ft_oauth"


class CredentialRepository(BaseRepository):
    def __init__(self, client, enc_key: str | None = None):
        super().__init__(client)
        self._enc_key = enc_key

    def _doc(self):
        return self._db.collection(_COLLECTION).document(_DOC)

    async def get(self) -> dict | None:
        """Returns the stored credential with secrets decrypted, or None."""
        snap = await self._doc().get()
        if not snap.exists:
            logger.debug("credential_repo.get: no stored credential")
            return None
        data = snap.to_dict() or {}
        for field in ("secret", "next_secret"):
            if data.get(field):
                data[field] = decrypt(data[field], self._enc_key)
        return data

    async def save(
        self,
        client_id: str,
        secret: str,
        expires_at: datetime | None = None,
        next_secret: str | None = None,
    ):
        doc = {
            "client_id": client_id,
            "secret": encrypt(secret, self._enc_key),
            "updated_at": datetime.now(timezone.utc),
        }
        # Only overwrite these when supplied, so saving a secret doesn't silently
        # wipe a staged next_secret or a known expiry.
        if expires_at is not None:
            doc["secret_expires_at"] = expires_at
        if next_secret is not None:
            doc["next_secret"] = encrypt(next_secret, self._enc_key)
        await self._doc().set(doc, merge=True)
        logger.info(
            "credential_repo.save: stored secret (expires_at=%s, next_secret=%s)",
            expires_at, "yes" if next_secret else "unchanged",
        )

    async def stage_next(self, next_secret: str, expires_at: datetime | None = None):
        """Stage the replacement secret ahead of the switchover."""
        doc = {
            "next_secret": encrypt(next_secret, self._enc_key),
            "updated_at": datetime.now(timezone.utc),
        }
        if expires_at is not None:
            doc["secret_expires_at"] = expires_at
        await self._doc().set(doc, merge=True)
        logger.info("credential_repo.stage_next: staged replacement secret")

    async def promote_next(self, new_expires_at: datetime | None = None):
        """Make the staged secret current and clear the staging slot."""
        data = await self.get()
        if not data or not data.get("next_secret"):
            return None
        promoted = data["next_secret"]
        doc = {
            "secret": encrypt(promoted, self._enc_key),
            "next_secret": None,
            "rotated_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        if new_expires_at is not None:
            doc["secret_expires_at"] = new_expires_at
        await self._doc().set(doc, merge=True)
        logger.warning("credential_repo.promote_next: promoted staged secret to current")
        return promoted

    async def record_auth(self, ok: bool, error: str | None = None):
        """Track the outcome of the most recent 42 token attempt so /health can
        surface a broken credential instead of reporting a bare 200."""
        await self._doc().set(
            {
                "last_auth_ok": ok,
                "last_auth_at": datetime.now(timezone.utc),
                "last_auth_error": None if ok else (error or "")[:300],
            },
            merge=True,
        )
