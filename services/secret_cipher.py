"""Symmetric encryption for 42 credentials held in Firestore.

The client_secret used to live in a 0600 root-owned file on the host; moving it
into Firestore (so it can be rotated without a redeploy) would otherwise weaken
it to plaintext-at-rest. Encrypting with a key that stays in the host file keeps
the two halves separate: Firestore access alone no longer yields the secret.

If no key is configured the value is stored as-is and a warning is logged —
that keeps local dev and tests working without ceremony, and lets the key be
introduced later without a migration (``decrypt`` detects the prefix).
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Marks a value as ciphertext so plaintext rows written before a key existed
# still decrypt (as themselves) instead of raising.
_PREFIX = "enc:v1:"


def _fernet(key: str) -> Fernet:
    """Accept any passphrase: Fernet needs a 32-byte urlsafe-b64 key, so derive
    one deterministically rather than forcing the operator to generate the exact
    format by hand."""
    digest = hashlib.sha256(key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str, key: str | None) -> str:
    if not value:
        return value
    if not key:
        logger.warning(
            "secret_cipher: no FT_SECRET_ENC_KEY set — storing credential in "
            "plaintext. Set the key to encrypt credentials at rest."
        )
        return value
    return _PREFIX + _fernet(key).encrypt(value.encode()).decode()


def decrypt(value: str, key: str | None) -> str:
    if not value or not value.startswith(_PREFIX):
        return value
    if not key:
        raise RuntimeError(
            "credential is encrypted but FT_SECRET_ENC_KEY is not set"
        )
    try:
        return _fernet(key).decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken as e:
        raise RuntimeError(
            "credential could not be decrypted — FT_SECRET_ENC_KEY may have changed"
        ) from e
