from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from database.repository import ScanRepository
from downloaders.plugin_downloader import PluginDownloader
from runtime_paths import resolve_runtime_paths
from scanners.semgrep_scanner import SemgrepScanner
from server.routers.semgrep_helpers import (
    CUSTOM_RULES_PATH,
    _extract_bulk_plugin_meta,
    _validate_slug_or_raise,
    get_active_rulesets,
    get_disabled_config,
)

RUNTIME_PATHS = resolve_runtime_paths()
SEMGREP_OUTPUTS_DIR = RUNTIME_PATHS.semgrep_outputs_dir

logger = logging.getLogger("temodar_agent")
BULK_SCAN_PAUSE_ITERATIONS = 5
BULK_SCAN_PAUSE_SECONDS = 0.1


def stop_requested(stop_event: Optional[asyncio.Event]) -> bool:
    """Return whether a cooperative stop has been requested."""
    return bool(stop_event and stop_event.is_set())


def mark_semgrep_scan_stopped(*, repo: ScanRepository, scan_id: int) -> None:
    """Persist a stopped scan state."""
    repo.update_semgrep_scan(scan_id, "failed", error="Stopped by user")


async def download_plugin_for_semgrep(
    *,
    slug: str,
    download_url: str,
) -> str | None:
    """Download and extract a plugin for Semgrep scanning."""
    downloader = PluginDownloader()
    loop = asyncio.get_running_loop()
    plugin_path = await loop.run_in_executor(
        None,
        downloader.download_and_extract,
        str(download_url),
        slug,
        False,
    )
    return str(plugin_path) if plugin_path is not None else None


def prepare_semgrep_output_dir(*, slug: str, scan_id: int) -> Path:
    """Create the per-scan Semgrep output directory."""
    output_dir = SEMGREP_OUTPUTS_DIR / f"{slug}_{scan_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def copy_custom_rules_if_available(output_dir: Path) -> None:
    """Copy shared custom rules into the per-scan directory when present."""
    if not CUSTOM_RULES_PATH.exists():
        return
    try:
        shutil.copy2(CUSTOM_RULES_PATH, output_dir / "custom_rules.yaml")
    except Exception:
        logger.warning("Failed to copy custom Semgrep rules into scan directory.")



def write_disabled_rules_snapshot(output_dir: Path) -> None:
    """Persist disabled rule IDs for scan-local filtering."""
    disabled_rules = get_disabled_config().get("rules", [])
    if not disabled_rules:
        return
    try:
        with open(output_dir / "disabled_rules.json", "w") as file_handle:
            json.dump(disabled_rules, file_handle)
    except Exception:
        logger.warning("Failed to write disabled rules for Semgrep scan.")


async def execute_semgrep_scan(*, output_dir: Path, plugin_path: str, slug: str):
    """Execute Semgrep against a prepared plugin path."""
    scanner = SemgrepScanner(
        output_dir=str(output_dir),
        use_registry_rules=True,
        registry_rulesets=get_active_rulesets(),
    )
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, scanner.scan_plugin, str(plugin_path), slug)



def build_semgrep_summary(findings: List[Dict[str, Any]], errors: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build the persisted summary payload for Semgrep findings."""
    summary = {
        "total_findings": len(findings),
        "breakdown": {"ERROR": 0, "WARNING": 0, "INFO": 0},
    }
    if errors:
        summary["errors"] = list(errors)
    for finding in findings:
        severity = finding.get("extra", {}).get("severity", "INFO")
        summary["breakdown"][severity] = summary["breakdown"].get(severity, 0) + 1
    return summary



def persist_semgrep_findings(
    *,
    repo: ScanRepository,
    scan_id: int,
    findings: List[Dict[str, Any]],
    stop_event: Optional[asyncio.Event],
    errors: Optional[List[str]] = None,
) -> Dict[str, Any] | None:
    """Persist findings unless a stop was requested during save."""
    for finding in findings:
        if stop_requested(stop_event):
            return None
        repo.save_semgrep_finding(scan_id, finding)
    return build_semgrep_summary(findings, errors=errors)



def validate_bulk_plugin(plugin: Dict[str, Any]) -> Dict[str, Any] | None:
    """Extract and validate the plugin metadata required for bulk scanning."""
    raw_slug = plugin.get("slug")
    try:
        plugin_meta = _extract_bulk_plugin_meta(plugin)
    except ValueError:
        logger.warning("Skipping plugin with invalid slug: %s", raw_slug)
        return None
    return plugin_meta


async def pause_between_bulk_items(stop_event: asyncio.Event) -> None:
    """Yield briefly between sequential bulk scans to reduce load spikes."""
    for _ in range(BULK_SCAN_PAUSE_ITERATIONS):
        if stop_event.is_set():
            break
        await asyncio.sleep(BULK_SCAN_PAUSE_SECONDS)



def validate_single_scan_slug(slug: str) -> str:
    """Validate a single-scan plugin slug."""
    return _validate_slug_or_raise(slug)
