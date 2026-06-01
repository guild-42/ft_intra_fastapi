import logging

from fastapi import APIRouter, Depends, Query

from deps import get_notification_repo
from repositories.notification_repo import NotificationRepository

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/notifications")
async def list_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: NotificationRepository = Depends(get_notification_repo),
):
    logger.info("list_notifications: page=%d per_page=%d", page, per_page)
    items = await repo.get_page(page=page, per_page=per_page)
    logger.info("list_notifications: returning %d items", len(items))
    return {"page": page, "per_page": per_page, "items": items}
