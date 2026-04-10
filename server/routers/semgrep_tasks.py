import asyncio
import logging
from typing import Any, Dict, List, Optional

from database.repository import ScanRepository
from server.routers.semgrep_task_service import (
    copy_custom_rules_if_available,
    download_plugin_for_semgrep,
    execute_semgrep_scan,
    mark_semgrep_scan_stopped,
    pause_between_bulk_items,
    persist_semgrep_findings,
    prepare_semgrep_output_dir,
    stop_requested,
    validate_bulk_plugin,
    validate_single_scan_slug,
    write_disabled_rules_snapshot,
)

logger = logging.getLogger("temodar_agent")

active_bulk_scans: Dict[int, asyncio.Event] = {}


async def run_plugin_semgrep_scan(
    scan_id: int,
    slug: str,
    download_url: str,
    repo: ScanRepository,
    stop_event: Optional[asyncio.Event] = None,
):
    """Background task to run Semgrep on a single plugin."""
    safe_slug = slug
    try:
        safe_slug = validate_single_scan_slug(slug)
        if stop_requested(stop_event):
            mark_semgrep_scan_stopped(repo=repo, scan_id=scan_id)
            return

        repo.update_semgrep_scan(scan_id, "running")
        plugin_path = await download_plugin_for_semgrep(
            slug=safe_slug,
            download_url=download_url,
        )
        if not plugin_path:
            raise Exception("Failed to download plugin")

        if stop_requested(stop_event):
            mark_semgrep_scan_stopped(repo=repo, scan_id=scan_id)
            return

        output_dir = prepare_semgrep_output_dir(slug=safe_slug, scan_id=scan_id)
        copy_custom_rules_if_available(output_dir)

        write_disabled_rules_snapshot(output_dir)

        result = await execute_semgrep_scan(
            output_dir=output_dir,
            plugin_path=str(plugin_path),
            slug=safe_slug,
        )
        summary = persist_semgrep_findings(
            repo=repo,
            scan_id=scan_id,
            findings=result.findings,
            stop_event=stop_event,
            errors=result.errors,
        )
        if summary is None:
            mark_semgrep_scan_stopped(repo=repo, scan_id=scan_id)
            return

        if stop_requested(stop_event):
            mark_semgrep_scan_stopped(repo=repo, scan_id=scan_id)
            return

        if not result.success and not result.findings:
            raise Exception(f"Semgrep failed: {', '.join(result.errors)}")

        error_message = ", ".join(result.errors) if result.errors else None
        status = "completed" if result.success else "failed"
        repo.update_semgrep_scan(
            scan_id,
            status,
            summary=summary,
            error=error_message,
        )
    except Exception as exc:
        if stop_requested(stop_event):
            mark_semgrep_scan_stopped(repo=repo, scan_id=scan_id)
            return
        repo.update_semgrep_scan(scan_id, "failed", error=str(exc))
        logger.error("Semgrep scan error for %s: %s", safe_slug, exc, exc_info=True)


async def run_bulk_semgrep_task(
    session_id: int,
    plugins: List[Dict[str, Any]],
    repo: ScanRepository,
    stop_event: asyncio.Event,
):
    """Run Semgrep on a list of plugins sequentially to prevent server crash."""
    try:
        for index, plugin in enumerate(plugins):
            if stop_event.is_set():
                logger.info("Bulk scan stopped by user at [%s/%s]", index, len(plugins))
                break

            plugin_meta = validate_bulk_plugin(plugin)
            if not plugin_meta:
                continue

            slug = plugin_meta["slug"]
            version = plugin_meta["version"]
            download_url = plugin_meta["download_url"]
            logger.info("Bulk scan [%s/%s]: %s", index + 1, len(plugins), slug)

            try:
                scan_id = repo.create_semgrep_scan(slug, version=version)
                await run_plugin_semgrep_scan(
                    scan_id,
                    slug,
                    download_url,
                    repo,
                    stop_event,
                )
                await pause_between_bulk_items(stop_event)
            except Exception as exc:
                logger.error("Bulk scan error for %s: %s", slug, exc)
    finally:
        active_bulk_scans.pop(session_id, None)
        logger.info("Bulk scan for session %s finished", session_id)
