"""
WP-Hunter FastAPI Application

REST API and WebSocket endpoints for the web dashboard.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.responses import PlainTextResponse

from wp_hunter.server.websockets import manager
from wp_hunter.server import update_manager
from wp_hunter.server.routers import scans, semgrep, plugins, favorites, config, system
from wp_hunter.server.limiter import limiter
from wp_hunter import __version__


def rate_limit_exceeded_handler(request: Request, exc: Exception):
    """Custom rate limit exceeded handler."""
    return PlainTextResponse(
        "Rate limit exceeded. Please try again later.", status_code=429
    )


def setup_logging():
    """Configure application logging."""
    log_file = Path("wp_hunter.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5),
            logging.StreamHandler(),
        ],
    )
    # Set levels for third-party libs
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    setup_logging()
    logger = logging.getLogger("wp_hunter")
    logger.info("Starting WP-Hunter Server...")

    app = FastAPI(
        title="WP-Hunter Dashboard",
        description="WordPress Plugin & Theme Security Scanner",
        version=__version__,
    )
    app.state.update_manager = update_manager.manager

    # Security: Add rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    # Security: Add trusted host middleware (localhost only)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    try:
        update_manager.manager.get_status(force=False)
    except Exception:
        logger.warning("Startup release warmup failed.", exc_info=True)

    # Include Routers
    app.include_router(scans.router)
    app.include_router(semgrep.router)
    app.include_router(plugins.router)
    app.include_router(favorites.router)
    app.include_router(config.router)
    app.include_router(system.router)

    # Static files directory
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", response_class=HTMLResponse)
    @limiter.limit("10/minute")  # Security: Rate limit homepage
    async def root(request: Request):
        """Serve the main dashboard."""
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return HTMLResponse(
            "<h1>WP-Hunter Dashboard</h1><p>Static files not found.</p>"
        )

    @app.websocket("/ws/scans/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: int):
        """WebSocket endpoint for real-time scan updates."""
        origin = websocket.headers.get("origin")
        if origin:
            try:
                origin_host = (urlparse(origin).hostname or "").lower()
            except Exception:
                origin_host = ""
            if origin_host not in {"localhost", "127.0.0.1"}:
                await websocket.close(code=1008)
                return

        await manager.connect(websocket, session_id)
        try:
            while True:
                # Keep connection alive, receive any client messages
                await websocket.receive_text()
                # Could handle client commands here if needed
        except WebSocketDisconnect:
            await manager.disconnect(websocket, session_id)

    return app
