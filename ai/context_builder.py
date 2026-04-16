import json
from pathlib import Path
from typing import Any, Dict, Optional

from database.models import get_db, init_db
from ai.workspace_manager import ensure_within_workspace
from downloaders.plugin_downloader import PluginDownloader
from downloaders.theme_downloader import ThemeDownloader
from runtime_paths import resolve_runtime_paths


def _empty_semgrep_payload() -> Dict[str, Any]:
    return {"scan": None, "summary": {}, "findings": []}



def _get_plugin_snapshot(cursor, plugin_slug: str, is_theme: bool, last_scan_session_id: int):
    cursor.execute(
        """
        SELECT
            pc.slug,
            pc.is_theme,
            pcs.session_id AS last_scan_session_id,
            pcs.score_snapshot AS score,
            pcs.version_snapshot AS latest_version,
            pcs.installations_snapshot AS installations,
            pcs.days_since_update_snapshot AS days_since_update,
            pcs.semgrep_findings_snapshot AS semgrep_findings
        FROM plugin_catalog pc
        INNER JOIN plugin_catalog_sessions pcs ON pcs.catalog_id = pc.id
        WHERE pc.slug = ? AND pc.is_theme = ? AND pcs.session_id = ?
        ORDER BY pcs.seen_at DESC, pcs.id DESC, pc.id DESC
        LIMIT 1
        """,
        (plugin_slug, int(is_theme), last_scan_session_id),
    )
    return cursor.fetchone()



def _get_completed_semgrep_scan(cursor, plugin_slug: str, plugin_version: Optional[str]):
    if not plugin_version:
        return None

    cursor.execute(
        """
        SELECT * FROM semgrep_scans
        WHERE slug = ? AND version = ? AND status = 'completed'
        ORDER BY completed_at DESC, created_at DESC, id DESC
        LIMIT 1
        """,
        (plugin_slug, plugin_version),
    )
    return cursor.fetchone()



def _build_runtime_source_path(plugin_slug: str, is_theme: bool) -> Path:
    runtime_plugins_dir = resolve_runtime_paths().plugins_dir
    root_dir = "Themes" if is_theme else "Plugins"
    return runtime_plugins_dir / root_dir / plugin_slug / "source"



def _build_relative_source_path(plugin_slug: str, is_theme: bool) -> str:
    return str(_build_runtime_source_path(plugin_slug, is_theme))



def _build_wp_download_url(plugin_slug: str, is_theme: bool, version: Optional[str]) -> str:
    artifact_type = "theme" if is_theme else "plugin"
    artifact_version = str(version or "latest").strip() or "latest"
    return f"https://downloads.wordpress.org/{artifact_type}/{plugin_slug}.{artifact_version}.zip"



def _get_catalog_download_metadata(cursor, plugin_slug: str, is_theme: bool, last_scan_session_id: Optional[int]) -> Dict[str, Optional[str]]:
    if last_scan_session_id is not None:
        cursor.execute(
            """
            SELECT sr.download_link, sr.version
            FROM scan_results sr
            WHERE sr.session_id = ? AND sr.slug = ? AND sr.is_theme = ?
            ORDER BY sr.id DESC
            LIMIT 1
            """,
            (last_scan_session_id, plugin_slug, int(is_theme)),
        )
        row = cursor.fetchone()
        if row:
            return {
                "download_link": row["download_link"] or None,
                "version": row["version"] or None,
            }

    cursor.execute(
        """
        SELECT sr.download_link, sr.version
        FROM scan_results sr
        WHERE sr.slug = ? AND sr.is_theme = ?
        ORDER BY sr.session_id DESC, sr.id DESC
        LIMIT 1
        """,
        (plugin_slug, int(is_theme)),
    )
    row = cursor.fetchone()
    if row:
        return {
            "download_link": row["download_link"] or None,
            "version": row["version"] or None,
        }

    cursor.execute(
        """
        SELECT pc.latest_version
        FROM plugin_catalog pc
        WHERE pc.slug = ? AND pc.is_theme = ?
        ORDER BY pc.id DESC
        LIMIT 1
        """,
        (plugin_slug, int(is_theme)),
    )
    row = cursor.fetchone()
    if row:
        return {
            "download_link": None,
            "version": row["latest_version"] or None,
        }

    return {"download_link": None, "version": None}



def resolve_source_download_info(
    db_path: Optional[Path],
    plugin_slug: str,
    is_theme: bool,
    last_scan_session_id: Optional[int],
) -> Dict[str, Optional[str]]:
    init_db(db_path)
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        info = _get_catalog_download_metadata(cursor, plugin_slug, is_theme, last_scan_session_id)
    download_url = info.get("download_link") or _build_wp_download_url(plugin_slug, is_theme, info.get("version"))
    return {
        "download_url": download_url,
        "version": info.get("version"),
    }



def ensure_thread_source_dir(
    db_path: Optional[Path],
    plugin_slug: str,
    is_theme: bool,
    last_scan_session_id: Optional[int],
    root_path: Path,
) -> Optional[Path]:
    existing = resolve_existing_thread_source_path(
        db_path=db_path,
        plugin_slug=plugin_slug,
        is_theme=is_theme,
        last_scan_session_id=last_scan_session_id,
        root_path=root_path,
    )
    if existing is not None:
        return existing.resolve()

    download_info = resolve_source_download_info(
        db_path=db_path,
        plugin_slug=plugin_slug,
        is_theme=is_theme,
        last_scan_session_id=last_scan_session_id,
    )
    download_url = str(download_info.get("download_url") or "").strip()
    if not download_url:
        return None

    runtime_plugins_dir = resolve_runtime_paths().plugins_dir
    downloader = (
        ThemeDownloader(base_dir=runtime_plugins_dir)
        if is_theme
        else PluginDownloader(base_dir=runtime_plugins_dir)
    )
    extracted = downloader.download_and_extract(download_url, plugin_slug, verbose=False)
    if extracted is None or not extracted.exists() or not extracted.is_dir():
        return None
    return extracted.resolve()



def resolve_thread_source_path(
    db_path: Optional[Path],
    plugin_slug: str,
    is_theme: bool,
    last_scan_session_id: int,
) -> str:
    init_db(db_path)

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT is_theme
            FROM scan_results
            WHERE session_id = ? AND slug = ? AND is_theme = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (last_scan_session_id, plugin_slug, int(is_theme)),
        )
        row = cursor.fetchone()

    if not row:
        raise LookupError(
            "Trusted source path requires a matching scan result for the selected thread scope."
        )

    return _build_relative_source_path(plugin_slug, bool(row["is_theme"]))



def resolve_local_source_path(plugin_slug: str, is_theme: bool) -> str:
    return _build_relative_source_path(plugin_slug, is_theme)



def resolve_thread_source_path_with_fallback(
    db_path: Optional[Path],
    plugin_slug: str,
    is_theme: bool,
    last_scan_session_id: Optional[int],
) -> str:
    if last_scan_session_id is not None:
        try:
            return resolve_thread_source_path(
                db_path=db_path,
                plugin_slug=plugin_slug,
                is_theme=is_theme,
                last_scan_session_id=last_scan_session_id,
            )
        except LookupError:
            pass

    return resolve_local_source_path(plugin_slug, is_theme)



def resolve_existing_thread_source_path(
    db_path: Optional[Path],
    plugin_slug: str,
    is_theme: bool,
    last_scan_session_id: Optional[int],
    root_path: Path,
) -> Optional[Path]:
    relative_path = resolve_thread_source_path_with_fallback(
        db_path=db_path,
        plugin_slug=plugin_slug,
        is_theme=is_theme,
        last_scan_session_id=last_scan_session_id,
    )
    candidate_path = Path(relative_path)
    if candidate_path.is_absolute():
        candidate = candidate_path.resolve(strict=False)
    else:
        try:
            candidate = ensure_within_workspace(root_path, candidate_path)
        except ValueError as exc:
            raise LookupError("Trusted source path must stay within the workspace roots.") from exc

    if not candidate.exists() or not candidate.is_dir():
        return None

    return candidate



def build_context_source_path(source_dir: Optional[Path]) -> str:
    return str(source_dir.resolve()) if source_dir is not None else ""



def build_context_last_scan_session_id(last_scan_session_id: Optional[int]) -> int:
    return int(last_scan_session_id or 0)



def build_context_source_state(source_dir: Optional[Path]) -> Dict[str, Any]:
    return {
        "available": source_dir is not None,
        "mode": "source" if source_dir is not None else "metadata_only",
    }



def build_context_semgrep_payload(
    semgrep_payload: Dict[str, Any],
    source_dir: Optional[Path],
) -> Dict[str, Any]:
    return {
        **semgrep_payload,
        "source": build_context_source_state(source_dir),
    }



def build_plugin_context_for_source(
    db_path: Optional[Path],
    plugin_slug: str,
    is_theme: bool,
    source_dir: Optional[Path],
    last_scan_session_id: Optional[int],
) -> Dict[str, Any]:
    context = build_plugin_context(
        db_path=db_path,
        plugin_slug=plugin_slug,
        is_theme=is_theme,
        source_path=build_context_source_path(source_dir),
        last_scan_session_id=build_context_last_scan_session_id(last_scan_session_id),
    )
    context["source"] = build_context_source_state(source_dir)
    context["semgrep"] = build_context_semgrep_payload(context.get("semgrep") or _empty_semgrep_payload(), source_dir)
    return context




def build_plugin_context(
    db_path: Optional[Path],
    plugin_slug: str,
    is_theme: bool,
    source_path: str,
    last_scan_session_id: int,
) -> Dict[str, Any]:
    init_db(db_path)

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        plugin_row = _get_plugin_snapshot(cursor, plugin_slug, is_theme, last_scan_session_id)

        if not plugin_row:
            return {
                "source_path": source_path,
                "plugin": None,
                "semgrep": _empty_semgrep_payload(),
            }

        plugin = dict(plugin_row)
        scan_row = _get_completed_semgrep_scan(
            cursor, plugin_slug, plugin.get("latest_version")
        )

        summary = {}
        findings = []
        scan_payload = None

        if scan_row:
            scan = dict(scan_row)
            summary = json.loads(scan["summary_json"]) if scan.get("summary_json") else {}
            scan_payload = {
                "id": scan["id"],
                "slug": scan["slug"],
                "version": scan["version"],
                "status": scan["status"],
                "created_at": scan["created_at"],
                "completed_at": scan["completed_at"],
            }
            cursor.execute(
                """
                SELECT * FROM semgrep_findings
                WHERE scan_id = ?
                ORDER BY id ASC
                """,
                (scan["id"],),
            )
            findings = [dict(row) for row in cursor.fetchall()]

    semgrep_snapshot = {
        "findings_count": int(plugin.get("semgrep_findings") or 0),
        "latest_version": plugin.get("latest_version"),
        "has_completed_scan": scan_payload is not None,
        "summary_total_findings": int(summary.get("total_findings") or 0),
    }

    plugin["metrics"] = {
        "risk_score": int(plugin.get("score") or 0),
        "installations": int(plugin.get("installations") or 0),
        "days_since_update": int(plugin.get("days_since_update") or 0),
        "latest_version": plugin.get("latest_version"),
        "semgrep_findings": int(plugin.get("semgrep_findings") or 0),
    }

    return {
        "source_path": source_path,
        "plugin": plugin,
        "semgrep": {
            "scan": scan_payload,
            "summary": summary,
            "findings": findings,
            "snapshot": semgrep_snapshot,
        },
    }


