"""Dependency wiring — the single place that constructs repositories and
services. Routes pull these via FastAPI ``Depends``; pollers/main import the
same factories. Services that hold caches/connections (push, ft_client) are
process singletons; repositories are cheap wrappers created per call."""
from firestore_client import get_client
from config import FT_SECRET_ENC_KEY
from repositories.checkin_repo import CheckinRepository
from repositories.credential_repo import CredentialRepository
from repositories.device_repo import DeviceRepository
from repositories.friendship_repo import FriendshipRepository
from repositories.notification_repo import NotificationRepository
from repositories.poller_state_repo import PollerStateRepository
from services.ft_client import FtClient
from services.ft_credentials import FtCredentials
from services.identity import IdentityVerifier
from services.push import PushService

# ───── repositories (cheap wrappers over the shared Firestore client) ─────

def get_device_repo() -> DeviceRepository:
    return DeviceRepository(get_client())


def get_notification_repo() -> NotificationRepository:
    return NotificationRepository(get_client())


def get_checkin_repo() -> CheckinRepository:
    return CheckinRepository(get_client())


def get_friendship_repo() -> FriendshipRepository:
    return FriendshipRepository(get_client())


def get_poller_state_repo() -> PollerStateRepository:
    return PollerStateRepository(get_client())


def get_credential_repo() -> CredentialRepository:
    return CredentialRepository(get_client(), enc_key=FT_SECRET_ENC_KEY)


# ───── services (process singletons: hold caches / global init) ─────

_identity = IdentityVerifier()
_push = PushService(device_repo_factory=get_device_repo)
# Holds the in-process secret cache + rotation lock, so it must be a singleton.
_ft_credentials = FtCredentials(repo_factory=get_credential_repo)
_ft_client = FtClient(_ft_credentials)


def get_identity() -> IdentityVerifier:
    return _identity


def get_push() -> PushService:
    return _push


def get_ft_client() -> FtClient:
    return _ft_client


def get_ft_credentials() -> FtCredentials:
    return _ft_credentials
