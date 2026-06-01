"""Firestore client lifecycle — the single place that constructs/holds the
AsyncClient. Repositories receive this client (injected) rather than reaching
for a module global, so they can be unit-tested against an in-memory fake."""
import logging

from google.cloud import firestore
from google.cloud.firestore_v1.async_client import AsyncClient

logger = logging.getLogger(__name__)

_client: AsyncClient | None = None


def get_client() -> AsyncClient:
    global _client
    if _client is None:
        logger.info("Initializing Firestore AsyncClient")
        _client = firestore.AsyncClient()
    return _client


async def init_db():
    """Firestore is schemaless, nothing to init."""
    get_client()
