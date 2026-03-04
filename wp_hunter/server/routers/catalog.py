"""
Plugin Catalog Router
"""

from typing import Optional

from fastapi import APIRouter, Request

from wp_hunter.database.repository import ScanRepository
from wp_hunter.server.limiter import limiter

router = APIRouter(prefix="/api/catalog", tags=["catalog"])
repo = ScanRepository()


@router.get("/plugins")
@limiter.limit("200/minute")
async def list_catalog_plugins(
    request: Request,
    q: str = "",
    sort_by: str = "last_seen",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
):
    return repo.get_catalog_plugins(
        q=q,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/plugins/{slug}/sessions")
@limiter.limit("200/minute")
async def get_catalog_plugin_sessions(
    request: Request,
    slug: str,
    is_theme: Optional[bool] = None,
    limit: int = 50,
):
    return {
        "slug": slug,
        "sessions": repo.get_catalog_plugin_sessions(
            slug=slug,
            is_theme=is_theme,
            limit=limit,
        ),
    }


@router.post("/rebuild")
@limiter.limit("1000/minute")
async def rebuild_catalog(request: Request):
    return repo.rebuild_plugin_catalog(reset=True)
