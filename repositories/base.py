"""Shared repository helpers."""
from google.cloud.firestore_v1.async_client import AsyncClient


def fcm_short(token) -> str:
    """Short, non-secret prefix of an fcm_token for log correlation. The full
    token is a device credential, so only the head is ever logged."""
    if not token:
        return "<none>"
    return f"{str(token)[:12]}…"


class BaseRepository:
    """Holds the injected Firestore client. Subclasses access it via self._db."""

    def __init__(self, client: AsyncClient):
        self._db = client
