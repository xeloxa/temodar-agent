"""
System router exposes dashboard metadata and update controls.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, status

from wp_hunter.server import update_manager

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger("wp_hunter.update.router")


@router.get("/update")
async def get_update_status(force: bool = False):
    """Return the current version, the latest release, and update progress."""
    try:
        status_payload = await asyncio.to_thread(update_manager.manager.get_status, force)
        return status_payload
    except Exception as exc:  # pragma: no cover - fallback for API failures
        logger.exception("Failed to fetch update info")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to check for releases right now.",
        ) from exc


@router.post("/update")
async def trigger_update():
    """Start downloading and applying the latest GitHub release."""
    try:
        message = await asyncio.to_thread(update_manager.manager.start_update)
        return {"status": "started", "message": message}
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - unexpected error handling
        logger.exception("Update trigger failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Update could not be started.",
        ) from exc
