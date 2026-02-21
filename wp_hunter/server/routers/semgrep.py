"""
Semgrep Router
"""

import asyncio
import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request

from wp_hunter.server.schemas import (
    DownloadRequest,
    SemgrepRuleRequest,
    SemgrepRulesetRequest,
)
from wp_hunter.database.repository import ScanRepository
from wp_hunter.downloaders.plugin_downloader import PluginDownloader
from wp_hunter.scanners.semgrep_scanner import (
    DEFAULT_ENABLED_RULESETS,
    SemgrepScanner,
    SEMGREP_REGISTRY_RULESETS,
    SEMGREP_COMMUNITY_SOURCES,
)
from wp_hunter.server.limiter import limiter

router = APIRouter(prefix="/api/semgrep", tags=["semgrep"])
repo = ScanRepository()
logger = logging.getLogger("wp_hunter")

# Only these core packs are treated as built-in and non-deletable.
CORE_RULESET_KEYS = {"owasp-top-ten", "php-security", "security-audit"}
CORE_RULESET_CONFIGS = {"p/owasp-top-ten", "p/php", "p/security-audit"}
CORE_RULESET_CONFIG_TO_KEY = {
    "p/owasp-top-ten": "owasp-top-ten",
    "p/php": "php-security",
    "p/security-audit": "security-audit",
}
SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")

# Track active bulk scans (session_id -> stop_flag)
active_bulk_scans: Dict[int, asyncio.Event] = {}

# Paths
SEM_RESULTS_DIR = Path("./semgrep_results")
SEM_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
CUSTOM_RULES_PATH = SEM_RESULTS_DIR / "custom_rules.yaml"
DISABLED_CONFIG_PATH = SEM_RESULTS_DIR / "disabled_config.json"
PACKAGE_CUSTOM_RULES_PATH = (
    Path(__file__).resolve().parents[2] / "semgrep_results" / "custom_rules.yaml"
)

# Bootstrap default custom rules into runtime directory if missing.
if not CUSTOM_RULES_PATH.exists() and PACKAGE_CUSTOM_RULES_PATH.exists():
    try:
        shutil.copy2(PACKAGE_CUSTOM_RULES_PATH, CUSTOM_RULES_PATH)
    except Exception:
        logger.warning("Failed to bootstrap default Semgrep custom rules.")


def get_disabled_config() -> Dict[str, List[str]]:
    """Load disabled rules and rulesets configuration."""
    default_config = {"rules": [], "rulesets": [], "extra_rulesets": []}
    # Legacy default packs we no longer want to keep automatically.
    legacy_default_rulesets = {"p/cwe-top-25", "cwe-top-25"}
    if DISABLED_CONFIG_PATH.exists():
        try:
            with open(DISABLED_CONFIG_PATH, "r") as f:
                config = json.load(f)
                before_rulesets = set(config.get("rulesets", []))
                before_extras = set(config.get("extra_rulesets", []))
                normalized = {
                    "rules": config.get("rules", []),
                    "rulesets": config.get("rulesets", []),
                    "extra_rulesets": config.get("extra_rulesets", []),
                }
                # Canonicalize ruleset IDs and deduplicate while preserving order.
                normalized["rulesets"] = list(
                    dict.fromkeys(
                        _canonicalize_ruleset_value(r) for r in normalized["rulesets"]
                    )
                )
                normalized["extra_rulesets"] = list(
                    dict.fromkeys(
                        _canonicalize_ruleset_value(r)
                        for r in normalized["extra_rulesets"]
                    )
                )
                # Migration: remove legacy defaults from persisted state.
                normalized["rulesets"] = [
                    r for r in normalized["rulesets"] if r not in legacy_default_rulesets
                ]
                normalized["extra_rulesets"] = [
                    r for r in normalized["extra_rulesets"] if r not in legacy_default_rulesets
                ]
                if before_rulesets != set(normalized["rulesets"]) or before_extras != set(normalized["extra_rulesets"]):
                    save_disabled_config(normalized)
                return normalized
        except Exception:
            pass
    return default_config


def save_disabled_config(config: Dict[str, List[str]]):
    """Save disabled configuration."""
    DISABLED_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DISABLED_CONFIG_PATH, "w") as f:
        json.dump(config, f)


def get_active_rulesets() -> List[str]:
    """Return the registry rulesets that are not disabled globally."""
    config = get_disabled_config()
    disabled = set(config.get("rulesets", []))
    extra_rulesets = config.get("extra_rulesets", [])
    combined = DEFAULT_ENABLED_RULESETS + extra_rulesets
    # Preserve order, remove duplicates
    unique = list(dict.fromkeys(combined))
    return [rs for rs in unique if rs not in disabled]


def _normalize_ruleset_value(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return value
    if value.startswith(("p/", "r/")):
        return value
    if value.startswith("https://semgrep.dev/"):
        parsed = value.split("https://semgrep.dev/", 1)[1].strip("/")
        return parsed
    return value


def _canonicalize_ruleset_value(raw: str) -> str:
    """Normalize ruleset and map built-in config aliases to canonical built-in keys."""
    normalized = _normalize_ruleset_value(raw)
    return CORE_RULESET_CONFIG_TO_KEY.get(normalized, normalized)


def _validate_slug_or_raise(slug: str) -> str:
    value = (slug or "").strip()
    if not SLUG_PATTERN.fullmatch(value):
        raise ValueError("Invalid slug format")
    return value


def _validate_semgrep_rules_config(rules_config: Dict[str, Any]) -> Optional[str]:
    """
    Validate Semgrep config before persisting.
    Returns None if valid, otherwise returns a human-readable error message.
    """
    try:
        check = subprocess.run(
            ["semgrep", "--version"], capture_output=True, text=True, timeout=10
        )
        if check.returncode != 0:
            return "Semgrep is not available for rule validation."
    except Exception:
        return "Semgrep is not available for rule validation."

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            yaml.dump(rules_config, tmp, default_flow_style=False, sort_keys=False)
            temp_path = tmp.name

        result = subprocess.run(
            ["semgrep", "--validate", "--config", temp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return None

        error_text = (result.stderr or result.stdout or "Unknown Semgrep validation error").strip()
        # Keep UI errors readable.
        return error_text[:800]
    except subprocess.TimeoutExpired:
        return "Semgrep validation timed out."
    except Exception as e:
        return f"Semgrep validation failed: {str(e)}"
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


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
        safe_slug = _validate_slug_or_raise(slug)
        if stop_event and stop_event.is_set():
            return
        repo.update_semgrep_scan(scan_id, "running")

        # 1. Download Plugin
        downloader = PluginDownloader()
        if stop_event and stop_event.is_set():
            return

        # Run blocking download in thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        plugin_path = await loop.run_in_executor(
            None, downloader.download_and_extract, str(download_url), safe_slug, False
        )

        if not plugin_path:
            raise Exception("Failed to download plugin")

        if stop_event and stop_event.is_set():
            return

        # 2. Run Semgrep
        output_dir = SEM_RESULTS_DIR / f"{safe_slug}_{scan_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Deploy custom configuration per scan so Semgrep can pick it up
        if CUSTOM_RULES_PATH.exists():
            try:
                shutil.copy2(CUSTOM_RULES_PATH, output_dir / "custom_rules.yaml")
            except Exception:
                logger.warning("Failed to copy custom Semgrep rules into scan directory.")

        disabled_rules = get_disabled_config().get("rules", [])
        if disabled_rules:
            try:
                with open(output_dir / "disabled_rules.json", "w") as f:
                    json.dump(disabled_rules, f)
            except Exception:
                logger.warning("Failed to write disabled rules for Semgrep scan.")

        scanner = SemgrepScanner(
            output_dir=str(output_dir),
            use_registry_rules=True,
            registry_rulesets=get_active_rulesets(),
        )

        # Start scan in thread to avoid blocking the event loop
        result = await loop.run_in_executor(
            None, scanner.scan_plugin, str(plugin_path), safe_slug
        )

        if not result.success:
            if stop_event and stop_event.is_set():
                return
            raise Exception(f"Semgrep failed: {', '.join(result.errors)}")

        # 3. Process Findings
        findings = result.findings
        summary = {
            "total_findings": len(findings),
            "breakdown": {"ERROR": 0, "WARNING": 0, "INFO": 0},
        }

        for finding in findings:
            if stop_event and stop_event.is_set():
                return
            repo.save_semgrep_finding(scan_id, finding)
            severity = finding.get("extra", {}).get("severity", "INFO")
            summary["breakdown"][severity] = summary["breakdown"].get(severity, 0) + 1

        # 4. Complete
        repo.update_semgrep_scan(scan_id, "completed", summary=summary)

    except Exception as e:
        if stop_event and stop_event.is_set():
            return
        repo.update_semgrep_scan(scan_id, "failed", error=str(e))
        logger.error(f"Semgrep scan error for {safe_slug}: {e}", exc_info=True)


async def run_bulk_semgrep_task(
    session_id: int,
    plugins: List[Dict[str, Any]],
    repo: ScanRepository,
    stop_event: asyncio.Event,
):
    """Run Semgrep on a list of plugins sequentially to prevent server crash."""
    logger = logging.getLogger("wp_hunter")

    try:
        for i, plugin in enumerate(plugins):
            # IMMEDIATE Check if stop requested
            if stop_event.is_set():
                logger.info(f"Bulk scan stopped by user at [{i}/{len(plugins)}]")
                break

            slug = plugin.get("slug")
            if not slug:
                continue  # Skip plugins without slug
            try:
                slug = _validate_slug_or_raise(str(slug))
            except ValueError:
                logger.warning(f"Skipping plugin with invalid slug: {slug}")
                continue

            version = plugin.get("version") or "latest"
            download_url = (
                plugin.get("download_link")
                or f"https://downloads.wordpress.org/plugin/{slug}.{version}.zip"
            )

            logger.info(f"Bulk scan [{i + 1}/{len(plugins)}]: {slug}")

            # Check if already scanned
            existing = repo.get_semgrep_scan(slug)
            if existing and existing["status"] == "completed":
                continue

            try:
                # Create scan record if not exists
                if not existing:
                    scan_id = repo.create_semgrep_scan(slug, version=version)
                else:
                    scan_id = existing["id"]
                    if existing["status"] in ["failed", "pending"]:
                        repo.update_semgrep_scan(scan_id, "pending")
                    else:
                        continue  # Skip running/completed

                # Run scan with stop event support
                await run_plugin_semgrep_scan(
                    scan_id, slug, download_url, repo, stop_event
                )

                # Small delay between scans to prevent resource exhaustion, but break immediately if stopped
                for _ in range(5):  # 0.5s total but checked every 0.1s
                    if stop_event.is_set():
                        break
                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Bulk scan error for {slug}: {e}")
    finally:
        # Remove from active scans when done
        if session_id in active_bulk_scans:
            del active_bulk_scans[session_id]
        logger.info(f"Bulk scan for session {session_id} finished")


@router.post("/scan")
@limiter.limit("10/minute")
async def start_semgrep_scan(
    request: Request, scan_request: DownloadRequest, background_tasks: BackgroundTasks
):
    """Start a Semgrep scan for a specific plugin."""
    try:
        safe_slug = _validate_slug_or_raise(scan_request.slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug format")

    # Create scan record
    scan_id = repo.create_semgrep_scan(safe_slug, version="latest")

    # Start background task
    background_tasks.add_task(
        run_plugin_semgrep_scan,
        scan_id,
        safe_slug,
        str(scan_request.download_url),
        repo,
    )

    return {"success": True, "scan_id": scan_id, "status": "pending"}


@router.get("/scan/{slug}")
async def get_semgrep_scan(slug: str):
    """Get the latest Semgrep scan for a plugin."""
    try:
        safe_slug = _validate_slug_or_raise(slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug format")

    scan = repo.get_semgrep_scan(safe_slug)
    if not scan:
        return {"status": "none"}
    return scan


@router.get("/rules")
async def get_semgrep_rules():
    """Get Semgrep configuration (rulesets and custom rules)."""
    # Check if Semgrep is installed
    try:
        result = subprocess.run(
            ["semgrep", "--version"], capture_output=True, text=True, timeout=10
        )
        installed = result.returncode == 0
    except Exception:
        installed = False

    disabled_config = get_disabled_config()
    disabled_rules = set(disabled_config["rules"])
    disabled_rulesets = set(disabled_config["rulesets"])

    # 1. Prepare Rulesets List (default + user-added)
    rulesets = []
    for key, info in SEMGREP_REGISTRY_RULESETS.items():
        # Hard filter: expose only the 3 core built-in packs in UI.
        if key not in CORE_RULESET_KEYS:
            continue
        rulesets.append(
            {
                "id": key,
                "name": info.get("description", key),  # Use description as name
                "url": info.get("url", "#"),
                "enabled": key not in disabled_rulesets,
                "description": info.get("description", ""),
                "deletable": False,  # Core packs are always non-deletable.
            }
        )

    for extra in disabled_config.get("extra_rulesets", []):
        normalized = _normalize_ruleset_value(extra)
        if not normalized:
            continue
        if normalized in {r["id"] for r in rulesets}:
            continue
        # Build friendly URL when possible.
        url = (
            f"https://semgrep.dev/{normalized}"
            if normalized.startswith(("p/", "r/"))
            else "https://semgrep.dev/explore"
        )
        rulesets.append(
            {
                "id": normalized,
                "name": normalized,
                "url": url,
                "enabled": normalized not in disabled_rulesets,
                "description": "Custom Semgrep ruleset",
                "deletable": True,
            }
        )

    # 2. Load Custom Rules
    custom_rules = []
    if CUSTOM_RULES_PATH.exists():
        try:
            with open(CUSTOM_RULES_PATH, "r") as f:
                custom_yaml = yaml.safe_load(f)
                if custom_yaml and "rules" in custom_yaml:
                    for rule in custom_yaml["rules"]:
                        rule_id = rule.get("id", "unknown")
                        pattern = rule.get("pattern", "")
                        if not pattern and "patterns" in rule:
                            patterns = rule["patterns"]
                            if patterns:
                                pattern = (
                                    str(patterns[0])
                                    if isinstance(patterns[0], str)
                                    else patterns[0].get("pattern", "Complex")
                                )

                        custom_rules.append(
                            {
                                "id": rule_id,
                                "message": rule.get("message", ""),
                                "severity": rule.get("severity", "WARNING"),
                                "pattern": pattern,
                                "is_custom": True,
                                "enabled": rule_id not in disabled_rules,
                            }
                        )
        except Exception as e:
            print(f"Error loading custom rules: {e}")

    return {
        "installed": installed,
        "rulesets": rulesets,
        "custom_rules": custom_rules,
        "community_sources": SEMGREP_COMMUNITY_SOURCES,
    }


@router.post("/rules")
async def add_semgrep_rule(rule: SemgrepRuleRequest):
    """Add a custom Semgrep rule."""
    # Validate rule ID (alphanumeric, hyphens, underscores only)
    if not re.match(r"^[a-zA-Z0-9_-]+$", rule.id):
        raise HTTPException(status_code=400, detail="Invalid rule ID format")

    # Ensure directory exists
    CUSTOM_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing custom rules or create new
    existing_rules = {"rules": []}
    if CUSTOM_RULES_PATH.exists():
        try:
            with open(CUSTOM_RULES_PATH, "r") as f:
                existing_rules = yaml.safe_load(f) or {"rules": []}
        except Exception:
            existing_rules = {"rules": []}

    # Check for duplicate ID
    for existing in existing_rules.get("rules", []):
        if existing.get("id") == rule.id:
            raise HTTPException(
                status_code=400, detail=f"Rule with ID '{rule.id}' already exists"
            )

    # Add new rule
    new_rule = {
        "id": rule.id,
        "pattern": rule.pattern,
        "message": rule.message,
        "languages": rule.languages,
        "severity": rule.severity,
    }
    existing_rules["rules"].append(new_rule)

    # Security gate: validate full Semgrep config before writing.
    validation_error = _validate_semgrep_rules_config(existing_rules)
    if validation_error:
        raise HTTPException(
            status_code=400,
            detail=(
                "Rule validation failed. Please check your Semgrep pattern syntax. "
                f"Details: {validation_error}"
            ),
        )

    # Save to file
    try:
        with open(CUSTOM_RULES_PATH, "w") as f:
            yaml.dump(existing_rules, f, default_flow_style=False, sort_keys=False)
        return {"success": True, "rule_id": rule.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save rule: {str(e)}")


@router.delete("/rules/{rule_id}")
async def delete_semgrep_rule(rule_id: str):
    """Delete a custom Semgrep rule."""
    # Security: Validate rule_id format
    if not re.match(r'^[a-zA-Z0-9_-]+$', rule_id):
        raise HTTPException(status_code=400, detail="Invalid rule ID format")
    
    if not CUSTOM_RULES_PATH.exists():
        raise HTTPException(status_code=404, detail="No custom rules file found")

    try:
        with open(CUSTOM_RULES_PATH, "r") as f:
            rules_data = yaml.safe_load(f) or {"rules": []}

        # Find and remove the rule
        original_count = len(rules_data.get("rules", []))
        rules_data["rules"] = [
            r for r in rules_data.get("rules", []) if r.get("id") != rule_id
        ]

        if len(rules_data["rules"]) == original_count:
            raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")

        # Save updated rules
        with open(CUSTOM_RULES_PATH, "w") as f:
            yaml.dump(rules_data, f, default_flow_style=False, sort_keys=False)

        return {"success": True, "deleted": rule_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete rule: {str(e)}")


@router.post("/rules/{rule_id}/toggle")
async def toggle_custom_rule(rule_id: str):
    """Enable or disable a custom Semgrep rule."""
    # Security: Validate rule_id format
    if not re.match(r'^[a-zA-Z0-9_-]+$', rule_id):
        raise HTTPException(status_code=400, detail="Invalid rule ID format")
    
    config = get_disabled_config()

    if rule_id in config["rules"]:
        # Enable
        config["rules"].remove(rule_id)
        save_disabled_config(config)
        return {"success": True, "rule_id": rule_id, "enabled": True}
    else:
        # Disable
        config["rules"].append(rule_id)
        save_disabled_config(config)
        return {"success": True, "rule_id": rule_id, "enabled": False}


@router.post("/rulesets")
async def add_ruleset(ruleset_request: SemgrepRulesetRequest):
    """Add a Semgrep ruleset (e.g., p/cwe-top-25) and enable it."""
    ruleset = _canonicalize_ruleset_value(ruleset_request.ruleset)
    if not ruleset:
        raise HTTPException(status_code=400, detail="Ruleset cannot be empty")

    if not re.match(r'^[a-zA-Z0-9_./-]+$', ruleset):
        raise HTTPException(status_code=400, detail="Invalid ruleset format")

    config = get_disabled_config()
    if ruleset not in config["extra_rulesets"] and ruleset not in SEMGREP_REGISTRY_RULESETS:
        config["extra_rulesets"].append(ruleset)

    # Auto-enable after add.
    if ruleset in config["rulesets"]:
        config["rulesets"].remove(ruleset)

    save_disabled_config(config)
    return {"success": True, "ruleset_id": ruleset, "enabled": True}


@router.post("/rulesets/{ruleset_id:path}/toggle")
async def toggle_ruleset(ruleset_id: str):
    """Enable or disable a Semgrep ruleset."""
    ruleset_id = _canonicalize_ruleset_value(ruleset_id)
    # Security: Validate ruleset_id format
    if not re.match(r'^[a-zA-Z0-9_./-]+$', ruleset_id):
        raise HTTPException(status_code=400, detail="Invalid ruleset ID format")

    config = get_disabled_config()
    available_rulesets = set(CORE_RULESET_KEYS) | set(
        config.get("extra_rulesets", [])
    )

    if ruleset_id not in available_rulesets:
        raise HTTPException(status_code=404, detail=f"Ruleset '{ruleset_id}' not found")

    if ruleset_id in config["rulesets"]:
        # Enable
        config["rulesets"].remove(ruleset_id)
        save_disabled_config(config)
        return {"success": True, "ruleset_id": ruleset_id, "enabled": True}
    else:
        # Disable
        config["rulesets"].append(ruleset_id)
        save_disabled_config(config)
        return {"success": True, "ruleset_id": ruleset_id, "enabled": False}


@router.delete("/rulesets/{ruleset_id:path}")
async def delete_ruleset(ruleset_id: str):
    """Delete a user-added Semgrep ruleset."""
    ruleset_id = _canonicalize_ruleset_value(ruleset_id)
    if not re.match(r'^[a-zA-Z0-9_./-]+$', ruleset_id):
        raise HTTPException(status_code=400, detail="Invalid ruleset ID format")

    if ruleset_id in CORE_RULESET_KEYS or ruleset_id in CORE_RULESET_CONFIGS:
        raise HTTPException(status_code=400, detail="Built-in rulesets cannot be deleted")

    config = get_disabled_config()
    extras = config.get("extra_rulesets", [])
    if ruleset_id not in extras:
        raise HTTPException(status_code=404, detail=f"Ruleset '{ruleset_id}' not found")

    config["extra_rulesets"] = [r for r in extras if r != ruleset_id]
    config["rulesets"] = [r for r in config.get("rulesets", []) if r != ruleset_id]
    save_disabled_config(config)
    return {"success": True, "deleted": ruleset_id}


@router.post("/bulk/{session_id}")
async def run_bulk_semgrep(session_id: int, background_tasks: BackgroundTasks):
    """Start or resume a bulk Semgrep scan for all plugins in a session."""
    # Check if already running
    if session_id in active_bulk_scans:
        raise HTTPException(
            status_code=400, detail="Bulk scan already running for this session"
        )

    # Get all plugins from the session
    results = repo.get_session_results(session_id, limit=9999)
    if not results:
        raise HTTPException(status_code=404, detail="No plugins found in this session")

    # Create stop event for this scan
    stop_event = asyncio.Event()
    active_bulk_scans[session_id] = stop_event

    # Start background task
    background_tasks.add_task(
        run_bulk_semgrep_task, session_id, results, repo, stop_event
    )

    return {"success": True, "count": len(results), "status": "started"}


@router.post("/bulk/{session_id}/stop")
async def stop_bulk_semgrep(session_id: int):
    """Stop a running bulk Semgrep scan."""
    if session_id not in active_bulk_scans:
        raise HTTPException(
            status_code=404, detail="No active bulk scan found for this session"
        )

    # Signal stop
    active_bulk_scans[session_id].set()

    return {"success": True, "status": "stopping"}


@router.get("/bulk/{session_id}/stats")
async def get_bulk_semgrep_stats(session_id: int):
    """Get aggregated stats for a bulk scan."""
    # Get all plugins from session
    results = repo.get_session_results(session_id, limit=9999)
    slugs = [r["slug"] for r in results]

    # Get stats
    stats = repo.get_semgrep_stats_for_slugs(slugs)

    # Calculate progress
    total_plugins = len(slugs)
    scanned_count = stats.get("scanned_count", 0)
    progress = int((scanned_count / total_plugins) * 100) if total_plugins > 0 else 0

    # Check if scan is currently running
    is_running = session_id in active_bulk_scans

    return {
        "session_id": session_id,
        "total_plugins": total_plugins,
        "scanned_count": scanned_count,
        "progress": progress,
        "total_findings": stats.get("total_findings", 0),
        "breakdown": stats.get("breakdown", {}),
        "is_running": is_running,
    }
