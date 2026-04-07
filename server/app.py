"""
Temodar Agent FastAPI Application

REST API and WebSocket endpoints for the web dashboard.
"""

import logging
import os
import secrets
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response

from app_meta import __version__
from server import update_manager
from server.limiter import limiter
from server.routers import ai, catalog, favorites, scans, semgrep, system
from server.websockets import manager

logger = logging.getLogger("temodar_agent")
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
ALLOWED_HOST_SET = set(ALLOWED_HOSTS)
STATIC_DIR = Path(__file__).parent / "static"

_AUTH_TOKEN = os.environ.get("TEMODAR_AUTH_TOKEN", "").strip()
_PUBLIC_PATH_PREFIXES = ("/static", "/assets", "/docs", "/openapi.json", "/redoc")
_PUBLIC_EXACT_PATHS = {"/", "/health"}


def rate_limit_exceeded_handler(request: Request, exc: Exception):
    """Custom rate limit exceeded handler."""
    return PlainTextResponse(
        "Rate limit exceeded. Please try again later.",
        status_code=429,
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self' ws://localhost:* wss://localhost:*;"
        )
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer token authentication for API endpoints."""

    async def dispatch(self, request: Request, call_next):
        if not _AUTH_TOKEN:
            return await call_next(request)

        path = request.url.path
        if path in _PUBLIC_EXACT_PATHS:
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return PlainTextResponse("Unauthorized", status_code=401)

        provided_token = auth_header[7:]
        if not secrets.compare_digest(provided_token, _AUTH_TOKEN):
            return PlainTextResponse("Forbidden", status_code=403)

        return await call_next(request)



def websocket_has_valid_auth(websocket: WebSocket) -> bool:
    if not _AUTH_TOKEN:
        return True
    auth_header = websocket.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    return secrets.compare_digest(auth_header[7:], _AUTH_TOKEN)



def setup_logging():
    """Configure application logging."""
    log_file = Path("temodar_agent.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)



def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()
    logger.info("Starting Temodar Agent Server...")

    app = FastAPI(
        title="Temodar Agent Dashboard",
        description="WordPress Plugin & Theme Security Scanner",
        version=__version__,
    )
    configure_application(app)
    return app



def configure_application(app: FastAPI) -> None:
    """Apply middleware, routes, startup wiring, and static mounts."""
    app.state.update_manager = update_manager.manager
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )

    if _AUTH_TOKEN:
        logger.info("Authentication enabled (TEMODAR_AUTH_TOKEN is set)")
    else:
        logger.warning(
            "Authentication DISABLED. Set TEMODAR_AUTH_TOKEN env var to enable."
        )

    warmup_update_manager()
    register_routers(app)
    mount_static_directories(app, STATIC_DIR)
    register_root_route(app, STATIC_DIR)
    register_scan_websocket(app)



def warmup_update_manager() -> None:
    """Warm up release status cache without failing app startup."""
    try:
        update_manager.manager.get_status(force=False)
    except Exception:
        logger.warning("Startup release warmup failed.", exc_info=True)



def register_routers(app: FastAPI) -> None:
    """Register API routers."""
    for router in (
        scans.router,
        semgrep.router,
        favorites.router,
        catalog.router,
        system.router,
        ai.router,
    ):
        app.include_router(router)



def mount_static_directories(app: FastAPI, static_dir: Path) -> None:
    """Mount static and asset directories if present."""
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")



def register_root_route(app: FastAPI, static_dir: Path) -> None:
    """Register the dashboard root page route."""

    @app.get("/", response_class=HTMLResponse)
    @limiter.limit("10000/minute")
    async def root(request: Request):
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return HTMLResponse("<h1>Temodar Agent Dashboard</h1><p>Static files not found.</p>")



def register_scan_websocket(app: FastAPI) -> None:
    """Register scan progress WebSocket endpoint."""

    @app.websocket("/ws/scans/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: int):
        origin = websocket.headers.get("origin")
        if not is_allowed_websocket_origin(origin):
            await websocket.close(code=1008)
            return
        if not websocket_has_valid_auth(websocket):
            await websocket.close(code=1008)
            return

        await manager.connect(websocket, session_id)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await manager.disconnect(websocket, session_id)



def is_allowed_websocket_origin(origin: str | None) -> bool:
    """Validate WebSocket origin against local-only host policy.

    Rejects connections without an Origin header to prevent
    non-browser clients from bypassing origin checks.
    """
    if not origin:
        return False
    try:
        origin_host = (urlparse(origin).hostname or "").lower()
    except Exception:
        return False
    return origin_host in ALLOWED_HOST_SET
