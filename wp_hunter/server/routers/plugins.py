"""
Plugins Router
"""

from fastapi import APIRouter, HTTPException
from wp_hunter.server.schemas import DownloadRequest
from wp_hunter.downloaders.plugin_downloader import PluginDownloader

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.post("/download")
async def download_plugin(request: DownloadRequest):
    """Download a plugin."""
    downloader = PluginDownloader()
    result = downloader.download_and_extract(
        str(request.download_url), request.slug, verbose=False
    )

    if result:
        return {"status": "success", "slug": request.slug, "path": str(result)}
    else:
        raise HTTPException(status_code=500, detail="Download failed")


@router.get("/downloaded")
async def list_downloaded_plugins():
    """List downloaded plugins."""
    downloader = PluginDownloader()
    plugins = downloader.get_downloaded_plugins()
    return {"plugins": plugins}
