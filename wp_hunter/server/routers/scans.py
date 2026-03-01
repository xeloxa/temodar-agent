"""
Scans Router
"""

import asyncio
from typing import Dict, Any, List
from fastapi import (
    APIRouter,
    HTTPException,
    BackgroundTasks,
    Request,
)

from wp_hunter.models import ScanConfig, ScanStatus, PluginResult
from wp_hunter.database.repository import ScanRepository
from wp_hunter.scanners.plugin_scanner import PluginScanner
from wp_hunter.scanners.theme_scanner import ThemeScanner
from wp_hunter.analyzers.risk_labeler import apply_relative_risk_labels
from wp_hunter.server.schemas import ScanRequest
from wp_hunter.server.websockets import manager
from wp_hunter.server.limiter import limiter

router = APIRouter(prefix="/api/scans", tags=["scans"])
repo = ScanRepository()

# Track active scans
active_scans: Dict[int, Any] = {}


def _apply_relative_risk_labels_to_dict_results(results: List[Dict[str, Any]]) -> None:
    """Apply percentile-based relative risk labels to API result dictionaries."""
    apply_relative_risk_labels(
        results,
        get_score=lambda item: int(item.get("score", 0) or 0),
        set_label=lambda item, label: item.__setitem__("relative_risk", label),
    )


async def run_scan_task(session_id: int, config: ScanConfig, repo: ScanRepository):
    """Background task to run a scan (Plugin or Theme)."""
    try:
        repo.update_session_status(session_id, ScanStatus.RUNNING)

        # Send start message
        await manager.send_to_session(
            session_id, {"type": "start", "session_id": session_id}
        )

        found_count = 0
        high_risk_count = 0
        loop = asyncio.get_running_loop()

        if config.themes:
            # Theme Scanning Mode
            def sync_on_theme_result(result: Dict[str, Any]):
                nonlocal found_count, high_risk_count
                found_count += 1
                if result.get("risk_level") == "HIGH":
                    high_risk_count += 1

                # Convert theme result to PluginResult for storage consistency
                plugin_result = PluginResult(
                    slug=result.get("slug", ""),
                    name=result.get("name", "Unknown"),
                    version=result.get("version", "?"),
                    score=result.get("risk_score", 0),
                    relative_risk=result.get("risk_level", ""),
                    installations=result.get("downloads", 0),
                    days_since_update=result.get("days_since_update", 0),
                    is_theme=True,
                    wp_org_link=result.get("wp_org_link", ""),
                    trac_link=result.get("trac_link", ""),
                    wpscan_link=result.get("wpscan_link", ""),
                    patchstack_link=result.get("patchstack_link", ""),
                    wordfence_link=result.get("wordfence_link", ""),
                    cve_search_link=result.get("cve_search_link", ""),
                    google_dork_link=result.get("google_dork_link", ""),
                    download_link=result.get("download_link", ""),
                )
                repo.save_result(session_id, plugin_result)

                asyncio.run_coroutine_threadsafe(
                    manager.send_to_session(
                        session_id,
                        {
                            "type": "result",
                            "data": plugin_result.to_dict(),
                            "found_count": found_count,
                        },
                    ),
                    loop,
                )

            scanner = ThemeScanner(
                pages=config.pages,
                limit=config.limit,
                sort=config.sort,
                on_result=sync_on_theme_result,
            )
            active_scans[session_id] = scanner
            await loop.run_in_executor(None, scanner.scan)
        else:
            # Plugin Scanning Mode (Default)
            scanner = PluginScanner(config)
            active_scans[session_id] = scanner

            def sync_on_result(result: PluginResult):
                nonlocal found_count, high_risk_count
                found_count += 1
                if (
                    getattr(result, "relative_risk", "") in {"HIGH", "CRITICAL"}
                ) or result.score >= 65:
                    high_risk_count += 1
                repo.save_result(session_id, result)
                # Schedule WebSocket send
                asyncio.run_coroutine_threadsafe(
                    manager.send_to_session(
                        session_id,
                        {
                            "type": "result",
                            "data": result.to_dict(),
                            "found_count": found_count,
                        },
                    ),
                    loop,
                )

            def sync_on_progress(current: int, total: int):
                asyncio.run_coroutine_threadsafe(
                    manager.send_to_session(
                        session_id,
                        {
                            "type": "progress",
                            "current": current,
                            "total": total,
                            "percent": int((current / total) * 100),
                        },
                    ),
                    loop,
                )

            scanner.on_result = sync_on_result
            scanner.on_progress = sync_on_progress

            # Run in thread
            await loop.run_in_executor(None, scanner.scan)

            # Final risk count based on calibrated relative labels.
            high_risk_count = sum(
                1
                for r in scanner.results
                if getattr(r, "relative_risk", "") in {"HIGH", "CRITICAL"}
            )

        # Update final status
        repo.update_session_status(
            session_id,
            ScanStatus.COMPLETED,
            total_found=found_count,
            high_risk_count=high_risk_count,
        )

        # Check for identical previous scan
        prev_session_id = repo.get_latest_session_by_config(
            config.to_dict(), session_id
        )
        if prev_session_id:
            current_slugs = set(repo.get_result_slugs(session_id))
            prev_slugs = set(repo.get_result_slugs(prev_session_id))

            if current_slugs == prev_slugs:
                # Identical results and config. Merge.
                repo.delete_session(session_id)
                repo.touch_session(prev_session_id)

                await manager.send_to_session(
                    session_id,
                    {
                        "type": "deduplicated",
                        "original_session_id": prev_session_id,
                        "message": "Results identical to previous scan. Merged.",
                    },
                )
                return

        # Send completion message
        await manager.send_to_session(
            session_id,
            {
                "type": "complete",
                "session_id": session_id,
                "total_found": found_count,
                "high_risk_count": high_risk_count,
            },
        )

    except Exception as e:
        repo.update_session_status(session_id, ScanStatus.FAILED, error_message=str(e))
        await manager.send_to_session(session_id, {"type": "error", "message": str(e)})
    finally:
        if session_id in active_scans:
            del active_scans[session_id]


@router.get("")
@limiter.limit("20/minute")
async def list_scans(request: Request, limit: int = 50):
    """List all scan sessions."""
    sessions = repo.get_all_sessions(limit)
    return {"sessions": sessions}


@router.post("")
@limiter.limit("5/minute")
async def create_scan(
    request: Request, scan_request: ScanRequest, background_tasks: BackgroundTasks
):
    """Create and start a new scan."""
    # Abandoned mode: override sort to "popular" for effective scanning
    sort = scan_request.sort
    pages = scan_request.pages
    if scan_request.abandoned and sort == "updated":
        sort = "popular"
    if scan_request.abandoned and pages == 5:
        pages = 100

    # Convert request to ScanConfig
    config = ScanConfig(
        pages=pages,
        limit=scan_request.limit,
        min_installs=scan_request.min_installs,
        max_installs=scan_request.max_installs,
        sort=sort,
        smart=scan_request.smart,
        abandoned=scan_request.abandoned,
        user_facing=scan_request.user_facing,
        themes=scan_request.themes,
        min_days=scan_request.min_days,
        max_days=scan_request.max_days,
        download=scan_request.download,
        auto_download_risky=scan_request.auto_download_risky,
        output=scan_request.output,
        format=scan_request.format,
        ajax_scan=scan_request.ajax_scan,
        dangerous_functions=scan_request.dangerous_functions,
        aggressive=scan_request.aggressive,
    )

    # Create session in database
    session_id = repo.create_session(config)

    # Start scan in background
    background_tasks.add_task(run_scan_task, session_id, config, repo)

    return {
        "session_id": session_id,
        "status": "started",
        "websocket_url": f"/ws/scans/{session_id}",
    }


@router.get("/{session_id}")
async def get_scan(session_id: int):
    """Get scan session details."""
    session = repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return session


@router.get("/{session_id}/results")
async def get_scan_results(
    session_id: int, sort_by: str = "score", sort_order: str = "desc", limit: int = 100
):
    """Get results for a scan session."""
    session = repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    results = repo.get_session_results(session_id, sort_by, sort_order, limit)

    # Add relative risk labels (percentile-based + absolute critical).
    _apply_relative_risk_labels_to_dict_results(results)

    # Add Semgrep status
    slugs = [r["slug"] for r in results]
    semgrep_statuses = repo.get_semgrep_statuses_for_slugs(slugs)

    for result in results:
        result["semgrep"] = semgrep_statuses.get(result["slug"])

    return {"session_id": session_id, "total": len(results), "results": results}


@router.delete("/{session_id}")
async def delete_scan(session_id: int):
    """Delete a scan session."""
    # Stop if running
    if session_id in active_scans:
        active_scans[session_id].stop()
        del active_scans[session_id]

    success = repo.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Scan session not found")

    return {"status": "deleted"}


@router.post("/{session_id}/stop")
async def stop_scan(session_id: int):
    """Stop a running scan."""
    if session_id not in active_scans:
        raise HTTPException(status_code=404, detail="No active scan found")

    active_scans[session_id].stop()
    repo.update_session_status(session_id, ScanStatus.CANCELLED)
    del active_scans[session_id]

    return {"status": "stopped"}
