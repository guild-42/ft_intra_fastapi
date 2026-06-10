"""Encryption-at-rest for intra session cookies (P0-5).

Fernet (AES128-CBC + HMAC) with the key from COOKIE_ENC_KEY. Decrypt tolerates
plaintext values so documents written before the key was provisioned keep
working; they are re-encrypted naturally on the next cookie refresh.
"""
import logging

from config import COOKIE_ENC_KEY

logger = logging.getLogger(__name__)

_warned = False


def _fernet():
    global _warned
    if not COOKIE_ENC_KEY:
        if not _warned:
            logger.warning(
                "COOKIE_ENC_KEY not set — cookies are stored in PLAINTEXT")
            _warned = True
        return None
    from cryptography.fernet import Fernet
    return Fernet(COOKIE_ENC_KEY.encode())


def encrypt_cookie(plaintext: str) -> str:
    f = _fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_cookie(stored: str | None) -> str | None:
    """Inverse of encrypt_cookie. Values that don't decrypt (legacy plaintext,
    or key unset) are returned as-is."""
    if stored is None:
        return None
    f = _fernet()
    if f is None:
        return stored
    from cryptography.fernet import InvalidToken
    try:
        return f.decrypt(stored.encode()).decode()
    except (InvalidToken, ValueError):
        return stored
