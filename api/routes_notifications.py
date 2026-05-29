from fastapi import APIRouter, Query
import db

router = APIRouter()


@router.get("/api/notifications")
async def list_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    items = await db.get_notifications(page=page, per_page=per_page)
    return {"page": page, "per_page": per_page, "items": items}
