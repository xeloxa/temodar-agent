"""
WP-Hunter Database Repository

CRUD operations for scan sessions and results.
"""

import json
from typing import List, Dict, Any, Optional, Set, Tuple
from pathlib import Path

from wp_hunter.database.models import get_db, init_db
from wp_hunter.models import ScanConfig, PluginResult, ScanStatus


class ScanRepository:
    """Repository for scan session and result operations."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        init_db(db_path)

        # Migration: Add is_duplicate column if missing
        try:
            with get_db(self.db_path) as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT is_duplicate FROM scan_results LIMIT 1")
                except Exception:
                    cursor.execute(
                        "ALTER TABLE scan_results ADD COLUMN is_duplicate INTEGER DEFAULT 0"
                    )
                    conn.commit()

            # Migration: Add link columns and theme flags if missing
            with get_db(self.db_path) as conn:
                cursor = conn.cursor()
                results_cols = {
                    "is_theme": "INTEGER DEFAULT 0",
                    "wp_org_link": "TEXT",
                    "cve_search_link": "TEXT",
                    "wpscan_link": "TEXT",
                    "patchstack_link": "TEXT",
                    "wordfence_link": "TEXT",
                    "google_dork_link": "TEXT",
                    "trac_link": "TEXT",
                }
                for col, type_def in results_cols.items():
                    try:
                        cursor.execute(f"SELECT {col} FROM scan_results LIMIT 1")
                    except Exception:
                        try:
                            cursor.execute(
                                f"ALTER TABLE scan_results ADD COLUMN {col} {type_def}"
                            )
                            conn.commit()
                        except Exception:
                            pass

            # Migration: Add missing columns to favorite_plugins
            with get_db(self.db_path) as conn:
                cursor = conn.cursor()
                fav_cols = {
                    "author_trusted": "INTEGER DEFAULT 0",
                    "is_risky_category": "INTEGER DEFAULT 0",
                    "is_user_facing": "INTEGER DEFAULT 0",
                    "is_theme": "INTEGER DEFAULT 0",
                    "wp_org_link": "TEXT",
                    "risk_tags": "TEXT",
                    "security_flags": "TEXT",
                    "feature_flags": "TEXT",
                    "code_analysis_json": "TEXT",
                }
                for col, type_def in fav_cols.items():
                    try:
                        cursor.execute(f"SELECT {col} FROM favorite_plugins LIMIT 1")
                    except Exception:
                        try:
                            cursor.execute(
                                f"ALTER TABLE favorite_plugins ADD COLUMN {col} {type_def}"
                            )
                            conn.commit()
                        except Exception:
                            pass

        except Exception as e:
            print(f"Database migration warning: {e}")

    def create_session(self, config: ScanConfig) -> int:
        """Create a new scan session and return its ID."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scan_sessions (config_json, status)
                VALUES (?, ?)
            """,
                (json.dumps(config.to_dict()), ScanStatus.PENDING.value),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def update_session_status(
        self,
        session_id: int,
        status: ScanStatus,
        total_found: Optional[int] = None,
        high_risk_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update session status and statistics."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            updates = ["status = ?"]
            params: List[Any] = [status.value]

            if total_found is not None:
                updates.append("total_found = ?")
                params.append(total_found)

            if high_risk_count is not None:
                updates.append("high_risk_count = ?")
                params.append(high_risk_count)

            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)

            params.append(session_id)

            cursor.execute(
                f"""
                UPDATE scan_sessions 
                SET {", ".join(updates)}
                WHERE id = ?
            """,
                params,
            )
            conn.commit()

    def save_result(self, session_id: int, result: PluginResult) -> int:
        """Save a scan result for a session."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            # Check for duplicates in OTHER sessions
            cursor.execute(
                """
                SELECT 1 FROM scan_results 
                WHERE slug = ? AND session_id != ? 
                LIMIT 1
            """,
                (result.slug, session_id),
            )

            if cursor.fetchone():
                result.is_duplicate = True

            code_analysis_json = None
            if result.code_analysis:
                code_analysis_json = json.dumps(
                    {
                        "dangerous_functions": result.code_analysis.dangerous_functions,
                        "ajax_endpoints": result.code_analysis.ajax_endpoints,
                        "file_operations": result.code_analysis.file_operations,
                        "sql_queries": result.code_analysis.sql_queries,
                        "nonce_usage": result.code_analysis.nonce_usage,
                        "sanitization_issues": result.code_analysis.sanitization_issues,
                    }
                )

            cursor.execute(
                """
                INSERT INTO scan_results (
                    session_id, slug, name, version, score, installations,
                    days_since_update, tested_wp_version, author_trusted,
                    is_risky_category, is_user_facing, is_duplicate, is_theme, risk_tags, security_flags,
                    feature_flags, download_link, wp_org_link, cve_search_link, wpscan_link, patchstack_link, 
                    wordfence_link, google_dork_link, trac_link, code_analysis_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    session_id,
                    result.slug,
                    result.name,
                    result.version,
                    result.score,
                    result.installations,
                    result.days_since_update,
                    result.tested_wp_version,
                    1 if result.author_trusted else 0,
                    1 if result.is_risky_category else 0,
                    1 if result.is_user_facing else 0,
                    1 if result.is_duplicate else 0,
                    1 if result.is_theme else 0,
                    ",".join(result.risk_tags),
                    ",".join(result.security_flags),
                    ",".join(result.feature_flags),
                    result.download_link,
                    result.wp_org_link,
                    result.cve_search_link,
                    result.wpscan_link,
                    result.patchstack_link,
                    result.wordfence_link,
                    result.google_dork_link,
                    result.trac_link,
                    code_analysis_json,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Get a scan session by ID."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM scan_sessions WHERE id = ?
            """,
                (session_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return {
                "id": row["id"],
                "created_at": row["created_at"],
                "status": row["status"],
                "config": json.loads(row["config_json"])
                if row["config_json"]
                else None,
                "total_found": row["total_found"],
                "high_risk_count": row["high_risk_count"],
                "error_message": row["error_message"],
            }

    def get_all_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get scan sessions, deduplicated by identical result slug-set, most recent first."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            # Over-fetch, then deduplicate in memory so we can still return up to `limit` unique sessions.
            cursor.execute(
                """
                SELECT * FROM scan_sessions
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (max(limit * 4, 200),),
            )

            rows = cursor.fetchall()
            if not rows:
                return []

            # Build slug sets for sessions in one query.
            session_ids = [row["id"] for row in rows]
            placeholders = ",".join(["?"] * len(session_ids))
            cursor.execute(
                f"""
                SELECT session_id, slug
                FROM scan_results
                WHERE session_id IN ({placeholders})
            """,
                session_ids,
            )

            slugs_by_session: Dict[int, Set[str]] = {}
            for rr in cursor.fetchall():
                sid = rr["session_id"]
                slugs_by_session.setdefault(sid, set()).add(rr["slug"])

            sessions: List[Dict[str, Any]] = []
            seen_signatures: Set[Tuple[bool, Tuple[str, ...]]] = set()

            for row in rows:
                sid = row["id"]
                slug_signature = tuple(sorted(slugs_by_session.get(sid, set())))
                has_results = len(slug_signature) > 0
                signature = (has_results, slug_signature)

                # Only deduplicate completed sessions with actual results.
                # Keep all failed/running/empty-result sessions visible.
                if row["status"] == ScanStatus.COMPLETED.value and has_results:
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)

                sessions.append(
                    {
                        "id": sid,
                        "created_at": row["created_at"],
                        "status": row["status"],
                        "config": json.loads(row["config_json"])
                        if row["config_json"]
                        else None,
                        "total_found": row["total_found"],
                        "high_risk_count": row["high_risk_count"],
                        "error_message": row["error_message"],
                    }
                )

                if len(sessions) >= limit:
                    break

            return sessions

    # SQL Injection Prevention: Whitelisted column mappings
    _VALID_SORT_COLUMNS = {
        "score": "score",
        "installations": "installations",
        "days_since_update": "days_since_update",
        "name": "name",
        "slug": "slug",
    }
    _VALID_SORT_ORDERS = {"ASC", "DESC"}

    def get_session_results(
        self,
        session_id: int,
        sort_by: str = "score",
        sort_order: str = "desc",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get results for a scan session."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            # SQL Injection Prevention: Use whitelisted column mapping
            safe_sort_column = self._VALID_SORT_COLUMNS.get(sort_by, "score")
            safe_sort_order = (
                "DESC"
                if sort_order.upper() in self._VALID_SORT_ORDERS
                and sort_order.upper() == "DESC"
                else "ASC"
            )

            # Build query using safe, validated values only
            query = f"""
                SELECT * FROM scan_results
                WHERE session_id = ?
                ORDER BY {safe_sort_column} {safe_sort_order}
                LIMIT ?
            """
            cursor.execute(query, (session_id, limit))

            results = []
            for row in cursor.fetchall():
                result = {
                    "id": row["id"],
                    "slug": row["slug"],
                    "name": row["name"],
                    "version": row["version"],
                    "score": row["score"],
                    "installations": row["installations"],
                    "days_since_update": row["days_since_update"],
                    "tested_wp_version": row["tested_wp_version"],
                    "author_trusted": bool(row["author_trusted"]),
                    "is_risky_category": bool(row["is_risky_category"]),
                    "is_user_facing": bool(row["is_user_facing"]),
                    "is_duplicate": bool(row["is_duplicate"])
                    if "is_duplicate" in row.keys()
                    else False,
                    "is_theme": bool(row["is_theme"])
                    if "is_theme" in row.keys()
                    else False,
                    "risk_tags": row["risk_tags"].split(",")
                    if row["risk_tags"]
                    else [],
                    "security_flags": row["security_flags"].split(",")
                    if row["security_flags"]
                    else [],
                    "feature_flags": row["feature_flags"].split(",")
                    if row["feature_flags"]
                    else [],
                    "download_link": row["download_link"],
                    "wp_org_link": row["wp_org_link"]
                    if "wp_org_link" in row.keys()
                    else None,
                    "cve_search_link": row["cve_search_link"],
                    "wpscan_link": row["wpscan_link"],
                    "patchstack_link": row["patchstack_link"],
                    "wordfence_link": row["wordfence_link"],
                    "google_dork_link": row["google_dork_link"],
                    "trac_link": row["trac_link"],
                }

                if row["code_analysis_json"]:
                    result["code_analysis"] = json.loads(row["code_analysis_json"])

                results.append(result)

            return results

    def delete_session(self, session_id: int) -> bool:
        """Delete a scan session and its results."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            # Delete results first (foreign key)
            cursor.execute(
                "DELETE FROM scan_results WHERE session_id = ?", (session_id,)
            )

            # Delete session
            cursor.execute("DELETE FROM scan_sessions WHERE id = ?", (session_id,))

            conn.commit()
            return cursor.rowcount > 0

    def get_latest_session_by_config(
        self, config_dict: Dict[str, Any], exclude_id: int
    ) -> Optional[int]:
        """Find the most recent completed session with identical configuration."""
        config_str = json.dumps(config_dict, sort_keys=True)

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, config_json FROM scan_sessions 
                WHERE status = 'completed' AND id != ?
                ORDER BY id DESC LIMIT 20
            """,
                (exclude_id,),
            )

            for row in cursor.fetchall():
                try:
                    row_config = json.loads(row["config_json"])
                    if json.dumps(row_config, sort_keys=True) == config_str:
                        return row["id"]
                except Exception:
                    continue
        return None

    def get_result_slugs(self, session_id: int) -> List[str]:
        """Get list of slugs for a session."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT slug FROM scan_results WHERE session_id = ?", (session_id,)
            )
            return [row["slug"] for row in cursor.fetchall()]

    def touch_session(self, session_id: int) -> None:
        """Update session timestamp to now."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE scan_sessions SET created_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
            conn.commit()

    def add_favorite(self, result_dict: Dict[str, Any]) -> bool:
        """Add a plugin to favorites."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            # Handle list fields for storage
            r_tags = (
                ",".join(result_dict.get("risk_tags", []))
                if isinstance(result_dict.get("risk_tags"), list)
                else result_dict.get("risk_tags", "")
            )
            s_flags = (
                ",".join(result_dict.get("security_flags", []))
                if isinstance(result_dict.get("security_flags"), list)
                else result_dict.get("security_flags", "")
            )
            f_flags = (
                ",".join(result_dict.get("feature_flags", []))
                if isinstance(result_dict.get("feature_flags"), list)
                else result_dict.get("feature_flags", "")
            )

            # Handle code analysis
            ca_json = None
            if result_dict.get("code_analysis"):
                ca_json = json.dumps(result_dict.get("code_analysis"))

            try:
                cursor.execute(
                    """
                    INSERT INTO favorite_plugins (
                        slug, name, version, score, installations, days_since_update,
                        tested_wp_version, is_theme, download_link, wp_org_link, cve_search_link, wpscan_link,
                        patchstack_link, wordfence_link, google_dork_link, trac_link,
                        author_trusted, is_risky_category, is_user_facing,
                        risk_tags, security_flags, feature_flags, code_analysis_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        result_dict.get("slug"),
                        result_dict.get("name"),
                        result_dict.get("version"),
                        result_dict.get("score"),
                        result_dict.get("installations"),
                        result_dict.get("days_since_update"),
                        result_dict.get("tested_wp_version"),
                        1 if result_dict.get("is_theme") else 0,
                        result_dict.get("download_link"),
                        result_dict.get("wp_org_link"),
                        result_dict.get("cve_search_link"),
                        result_dict.get("wpscan_link"),
                        result_dict.get("patchstack_link"),
                        result_dict.get("wordfence_link"),
                        result_dict.get("google_dork_link"),
                        result_dict.get("trac_link"),
                        1 if result_dict.get("author_trusted") else 0,
                        1 if result_dict.get("is_risky_category") else 0,
                        1 if result_dict.get("is_user_facing") else 0,
                        r_tags,
                        s_flags,
                        f_flags,
                        ca_json,
                    ),
                )
                conn.commit()
                return True
            except Exception as e:
                print(f"Error adding favorite: {e}")
                return False

    def remove_favorite(self, slug: str) -> bool:
        """Remove a plugin from favorites."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM favorite_plugins WHERE slug = ?", (slug,))
            conn.commit()
            return cursor.rowcount > 0

    def get_favorites(self) -> List[Dict[str, Any]]:
        """Get all favorite plugins."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM favorite_plugins ORDER BY created_at DESC")
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                # Parse bools
                d["author_trusted"] = bool(d.get("author_trusted", 0))
                d["is_risky_category"] = bool(d.get("is_risky_category", 0))
                d["is_user_facing"] = bool(d.get("is_user_facing", 0))
                d["is_theme"] = bool(d.get("is_theme", 0))

                # Parse lists
                d["risk_tags"] = d["risk_tags"].split(",") if d.get("risk_tags") else []
                d["security_flags"] = (
                    d["security_flags"].split(",") if d.get("security_flags") else []
                )
                d["feature_flags"] = (
                    d["feature_flags"].split(",") if d.get("feature_flags") else []
                )

                # Parse JSON
                if d.get("code_analysis_json"):
                    d["code_analysis"] = json.loads(d["code_analysis_json"])

                results.append(d)
            return results

    def create_semgrep_scan(self, slug: str, version: Optional[str] = None) -> int:
        """Create a new Semgrep scan record."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO semgrep_scans (slug, version, status)
                VALUES (?, ?, 'pending')
            """,
                (slug, version),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def update_semgrep_scan(
        self,
        scan_id: int,
        status: str,
        summary: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        """Update Semgrep scan status and summary."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            updates = ["status = ?"]
            params: List[Any] = [status]

            if summary:
                updates.append("summary_json = ?")
                params.append(json.dumps(summary))

            if error:
                updates.append("error_message = ?")
                params.append(error)

            if status in ["completed", "failed"]:
                updates.append("completed_at = CURRENT_TIMESTAMP")

            params: List[Any] = params + [scan_id]

            cursor.execute(
                f"""
                UPDATE semgrep_scans
                SET {", ".join(updates)}
                WHERE id = ?
            """,
                params,
            )
            conn.commit()

    def save_semgrep_finding(self, scan_id: int, finding: Dict[str, Any]):
        """Save a single Semgrep finding."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO semgrep_findings (
                    scan_id, rule_id, message, severity, file_path,
                    line_number, code_snippet, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    scan_id,
                    finding.get("check_id"),
                    finding.get("extra", {}).get("message"),
                    finding.get("extra", {}).get("severity"),
                    finding.get("path"),
                    finding.get("start", {}).get("line"),
                    finding.get("extra", {}).get("lines"),
                    json.dumps(finding.get("extra", {}).get("metadata", {})),
                ),
            )
            conn.commit()

    def get_semgrep_scan(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get the latest Semgrep scan for a plugin."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM semgrep_scans
                WHERE slug = ?
                ORDER BY created_at DESC LIMIT 1
            """,
                (slug,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            scan = dict(row)
            if scan["summary_json"]:
                scan["summary"] = json.loads(scan["summary_json"])

            # Get findings
            cursor.execute(
                """
                SELECT * FROM semgrep_findings WHERE scan_id = ?
            """,
                (scan["id"],),
            )

            scan["findings"] = [dict(r) for r in cursor.fetchall()]
            return scan

    def get_semgrep_stats_for_slugs(self, slugs: List[str]) -> Dict[str, Any]:
        """Aggregate Semgrep statistics for a list of plugin slugs."""
        if not slugs:
            return {"total_findings": 0, "breakdown": {}, "scanned_count": 0}

        placeholders = ",".join(["?"] * len(slugs))
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            # Get latest scan ID for each slug
            cursor.execute(
                f"""
                SELECT slug, MAX(id) as max_id
                FROM semgrep_scans
                WHERE slug IN ({placeholders}) AND status = 'completed'
                GROUP BY slug
            """,
                slugs,
            )

            latest_scan_ids = [row["max_id"] for row in cursor.fetchall()]

            if not latest_scan_ids:
                return {"total_findings": 0, "breakdown": {}, "scanned_count": 0}

            placeholders_ids = ",".join(["?"] * len(latest_scan_ids))

            # Aggregate findings
            cursor.execute(
                f"""
                SELECT severity, COUNT(*) as count
                FROM semgrep_findings
                WHERE scan_id IN ({placeholders_ids})
                GROUP BY severity
            """,
                latest_scan_ids,
            )

            breakdown = {row["severity"]: row["count"] for row in cursor.fetchall()}
            total_findings = sum(breakdown.values())

            return {
                "total_findings": total_findings,
                "breakdown": breakdown,
                "scanned_count": len(latest_scan_ids),
            }

    def get_semgrep_statuses_for_slugs(
        self, slugs: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Get the latest scan status and findings count for a list of slugs."""
        if not slugs:
            return {}

        placeholders = ",".join(["?"] * len(slugs))
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            # Get latest scan for each slug
            cursor.execute(
                f"""
                SELECT s.slug, s.status, s.summary_json
                FROM semgrep_scans s
                INNER JOIN (
                    SELECT slug, MAX(id) as max_id
                    FROM semgrep_scans
                    WHERE slug IN ({placeholders})
                    GROUP BY slug
                ) latest ON s.id = latest.max_id
            """,
                slugs,
            )

            results = {}
            for row in cursor.fetchall():
                slug = row["slug"]
                summary = json.loads(row["summary_json"]) if row["summary_json"] else {}
                results[slug] = {
                    "status": row["status"],
                    "findings_count": summary.get("total_findings", 0),
                    "breakdown": summary.get("breakdown", {}),
                }
            return results
