"""
WP-Hunter Database Repository

CRUD operations for scan sessions and results.
"""

import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set, Tuple
from pathlib import Path

from wp_hunter.database.models import get_db, init_db
from wp_hunter.models import ScanConfig, PluginResult, ScanStatus


class ScanRepository:
    """Repository for scan session and result operations."""

    _catalog_backfill_attempted = False

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        self._session_created_at_cache: Dict[int, str] = {}
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

        if not ScanRepository._catalog_backfill_attempted:
            ScanRepository._catalog_backfill_attempted = True
            try:
                self._maybe_backfill_catalog()
            except Exception:
                pass

    def _get_session_created_at(self, cursor: Any, session_id: int) -> str:
        cached = self._session_created_at_cache.get(session_id)
        if cached:
            return cached

        cursor.execute("SELECT created_at FROM scan_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        created_at = row["created_at"] if row and row["created_at"] else ""
        self._session_created_at_cache[session_id] = created_at
        return created_at

    def _upsert_catalog_entry(
        self,
        cursor: Any,
        session_id: int,
        session_created_at: str,
        result: PluginResult,
    ) -> None:
        slug = result.slug
        is_theme = 1 if result.is_theme else 0

        cursor.execute(
            """
            SELECT id, seen_count, max_score_ever, first_seen_session_id, first_seen_at
            FROM plugin_catalog
            WHERE slug = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (slug,),
        )
        existing = cursor.fetchone()

        if existing:
            catalog_id = existing["id"]
            previous_seen_count = int(existing["seen_count"] or 0)
            max_score_ever = max(int(existing["max_score_ever"] or 0), int(result.score or 0))

            cursor.execute(
                """
                INSERT OR IGNORE INTO plugin_catalog_sessions (
                    catalog_id, session_id, seen_at, score_snapshot, version_snapshot,
                    installations_snapshot, days_since_update_snapshot, semgrep_findings_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    catalog_id,
                    session_id,
                    session_created_at,
                    int(result.score or 0),
                    result.version,
                    int(result.installations or 0),
                    int(result.days_since_update or 0),
                    None,
                ),
            )
            seen_increment = 1 if cursor.rowcount > 0 else 0

            cursor.execute(
                """
                UPDATE plugin_catalog
                SET last_seen_session_id = ?,
                    last_seen_at = ?,
                    seen_count = ?,
                    latest_version = ?,
                    latest_score = ?,
                    max_score_ever = ?,
                    latest_installations = ?,
                    latest_days_since_update = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    session_id,
                    session_created_at,
                    previous_seen_count + seen_increment,
                    result.version,
                    int(result.score or 0),
                    max_score_ever,
                    int(result.installations or 0),
                    int(result.days_since_update or 0),
                    catalog_id,
                ),
            )
            return

        cursor.execute(
            """
            INSERT INTO plugin_catalog (
                slug, is_theme,
                first_seen_session_id, last_seen_session_id,
                first_seen_at, last_seen_at,
                seen_count,
                latest_version, latest_score, max_score_ever,
                latest_installations, latest_days_since_update,
                latest_semgrep_findings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                is_theme,
                session_id,
                session_id,
                session_created_at,
                session_created_at,
                1,
                result.version,
                int(result.score or 0),
                int(result.score or 0),
                int(result.installations or 0),
                int(result.days_since_update or 0),
                None,
            ),
        )
        catalog_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT OR IGNORE INTO plugin_catalog_sessions (
                catalog_id, session_id, seen_at, score_snapshot, version_snapshot,
                installations_snapshot, days_since_update_snapshot, semgrep_findings_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                catalog_id,
                session_id,
                session_created_at,
                int(result.score or 0),
                result.version,
                int(result.installations or 0),
                int(result.days_since_update or 0),
                None,
            ),
        )

    def _refresh_catalog_entry(self, cursor: Any, catalog_id: int) -> None:
        cursor.execute(
            """
            SELECT COUNT(*) AS c, MIN(seen_at) AS first_seen, MAX(seen_at) AS last_seen
            FROM plugin_catalog_sessions
            WHERE catalog_id = ?
            """,
            (catalog_id,),
        )
        stats = cursor.fetchone()
        link_count = int((stats["c"] if stats else 0) or 0)

        if link_count <= 0:
            cursor.execute("DELETE FROM plugin_catalog WHERE id = ?", (catalog_id,))
            return

        cursor.execute(
            """
            SELECT session_id, score_snapshot, version_snapshot,
                   installations_snapshot, days_since_update_snapshot
            FROM plugin_catalog_sessions
            WHERE catalog_id = ?
            ORDER BY seen_at ASC, id ASC
            LIMIT 1
            """,
            (catalog_id,),
        )
        first_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT session_id, score_snapshot, version_snapshot,
                   installations_snapshot, days_since_update_snapshot
            FROM plugin_catalog_sessions
            WHERE catalog_id = ?
            ORDER BY seen_at DESC, id DESC
            LIMIT 1
            """,
            (catalog_id,),
        )
        last_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT MAX(COALESCE(score_snapshot, 0)) AS max_score
            FROM plugin_catalog_sessions
            WHERE catalog_id = ?
            """,
            (catalog_id,),
        )
        max_row = cursor.fetchone()
        max_score = int((max_row["max_score"] if max_row else 0) or 0)

        cursor.execute(
            """
            UPDATE plugin_catalog
            SET first_seen_session_id = ?,
                last_seen_session_id = ?,
                first_seen_at = ?,
                last_seen_at = ?,
                seen_count = ?,
                latest_version = ?,
                latest_score = ?,
                max_score_ever = ?,
                latest_installations = ?,
                latest_days_since_update = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                first_row["session_id"] if first_row else None,
                last_row["session_id"] if last_row else None,
                stats["first_seen"],
                stats["last_seen"],
                link_count,
                last_row["version_snapshot"] if last_row else None,
                int((last_row["score_snapshot"] if last_row else 0) or 0),
                max_score,
                int((last_row["installations_snapshot"] if last_row else 0) or 0),
                int((last_row["days_since_update_snapshot"] if last_row else 0) or 0),
                catalog_id,
            ),
        )

    def _maybe_backfill_catalog(self) -> None:
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM plugin_catalog")
            catalog_count = int((cursor.fetchone() or {"c": 0})["c"])
            if catalog_count > 0:
                return

            cursor.execute("SELECT COUNT(*) AS c FROM scan_results")
            results_count = int((cursor.fetchone() or {"c": 0})["c"])
            if results_count == 0:
                return

        self.rebuild_plugin_catalog(reset=True)

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
            inserted_id = cursor.lastrowid or 0

            session_created_at = self._get_session_created_at(cursor, session_id)
            self._upsert_catalog_entry(cursor, session_id, session_created_at, result)

            conn.commit()
            return inserted_id

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
            signature_counts: Dict[Tuple[bool, Tuple[str, ...]], int] = {}

            for row in rows:
                sid = row["id"]
                slug_signature = tuple(sorted(slugs_by_session.get(sid, set())))
                has_results = len(slug_signature) > 0
                signature = (has_results, slug_signature)
                if (
                    row["status"]
                    in {ScanStatus.COMPLETED.value, ScanStatus.MERGED.value}
                    and has_results
                ):
                    signature_counts[signature] = signature_counts.get(signature, 0) + 1

            for row in rows:
                sid = row["id"]
                slug_signature = tuple(sorted(slugs_by_session.get(sid, set())))
                has_results = len(slug_signature) > 0
                signature = (has_results, slug_signature)

                # Only deduplicate completed sessions with actual results.
                # Keep all failed/running/empty-result sessions visible.
                if (
                    row["status"]
                    in {ScanStatus.COMPLETED.value, ScanStatus.MERGED.value}
                    and has_results
                ):
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)

                status_value = row["status"]
                is_merged = status_value == ScanStatus.MERGED.value or (
                    status_value
                    in {ScanStatus.COMPLETED.value, ScanStatus.MERGED.value}
                    and has_results
                    and signature_counts.get(signature, 0) > 1
                )
                if is_merged:
                    status_value = ScanStatus.MERGED.value

                sessions.append(
                    {
                        "id": sid,
                        "created_at": row["created_at"],
                        "status": status_value,
                        "is_merged": is_merged,
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

            cursor.execute(
                "SELECT catalog_id FROM plugin_catalog_sessions WHERE session_id = ?",
                (session_id,),
            )
            affected_catalog_ids = [int(row["catalog_id"]) for row in cursor.fetchall()]

            cursor.execute(
                "DELETE FROM plugin_catalog_sessions WHERE session_id = ?", (session_id,)
            )

            # Delete results first
            cursor.execute(
                "DELETE FROM scan_results WHERE session_id = ?", (session_id,)
            )

            # Delete session
            cursor.execute("DELETE FROM scan_sessions WHERE id = ?", (session_id,))
            session_deleted = cursor.rowcount > 0

            for catalog_id in set(affected_catalog_ids):
                self._refresh_catalog_entry(cursor, catalog_id)

            conn.commit()
            return session_deleted

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
                WHERE status IN ('completed', 'merged') AND id != ?
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

    def mark_session_merged(self, session_id: int) -> None:
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE scan_sessions
                SET status = ?, created_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (ScanStatus.MERGED.value, session_id),
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

    _VALID_CATALOG_SORT_COLUMNS = {
        "last_seen": "pc.last_seen_at",
        "seen_count": "pc.seen_count",
        "max_score": "pc.max_score_ever",
        "latest_score": "pc.latest_score",
        "installs": "pc.latest_installations",
        "updated_days": "pc.latest_days_since_update",
        "slug": "pc.slug",
    }

    def get_catalog_plugins(
        self,
        q: str = "",
        sort_by: str = "last_seen",
        order: str = "desc",
        limit: int = 100,
        offset: int = 0,
        include_sessions: bool = False,
    ) -> Dict[str, Any]:
        try:
            self._maybe_backfill_catalog()
        except Exception:
            pass

        safe_sort_column = self._VALID_CATALOG_SORT_COLUMNS.get(sort_by, "pc.last_seen_at")
        safe_order = "DESC" if str(order or "").upper() == "DESC" else "ASC"
        safe_limit = max(1, min(int(limit or 100), 1000))
        safe_offset = max(0, int(offset or 0))
        query_text = str(q or "").strip().lower()

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            where_clause = ""
            params: List[Any] = []
            if query_text:
                where_clause = "WHERE LOWER(pc.slug) LIKE ?"
                params.append(f"%{query_text}%")

            cursor.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM plugin_catalog pc
                {where_clause}
                """,
                params,
            )
            total = int((cursor.fetchone() or {"c": 0})["c"])

            cursor.execute(
                f"""
                SELECT
                    pc.id,
                    pc.slug,
                    pc.is_theme,
                    pc.first_seen_session_id,
                    pc.last_seen_session_id,
                    pc.first_seen_at,
                    pc.last_seen_at,
                    pc.seen_count,
                    pc.latest_version,
                    pc.latest_score,
                    pc.max_score_ever,
                    pc.latest_installations,
                    pc.latest_days_since_update,
                    pc.latest_semgrep_findings,
                    pc.created_at,
                    pc.updated_at
                FROM plugin_catalog pc
                {where_clause}
                ORDER BY {safe_sort_column} {safe_order}
                LIMIT ? OFFSET ?
                """,
                params + [safe_limit, safe_offset],
            )

            rows = [dict(r) for r in cursor.fetchall()]

            if rows:
                slugs = [str(item.get("slug") or "") for item in rows if item.get("slug")]
                semgrep_statuses = self.get_semgrep_statuses_for_slugs(slugs)
                for item in rows:
                    semgrep = semgrep_statuses.get(str(item.get("slug") or ""))
                    item["semgrep"] = semgrep
                    if semgrep:
                        item["latest_semgrep_findings"] = int(
                            semgrep.get("findings_count") or 0
                        )

            if include_sessions and rows:
                catalog_ids = [int(r["id"]) for r in rows]
                placeholders = ",".join(["?"] * len(catalog_ids))
                cursor.execute(
                    f"""
                    SELECT catalog_id, session_id, seen_at
                    FROM plugin_catalog_sessions
                    WHERE catalog_id IN ({placeholders})
                    ORDER BY seen_at DESC
                    """,
                    catalog_ids,
                )
                sessions_by_catalog: Dict[int, List[Dict[str, Any]]] = {}
                for row in cursor.fetchall():
                    cid = int(row["catalog_id"])
                    sessions_by_catalog.setdefault(cid, []).append(
                        {
                            "session_id": row["session_id"],
                            "seen_at": row["seen_at"],
                        }
                    )
                for item in rows:
                    item["sessions"] = sessions_by_catalog.get(int(item["id"]), [])

            now_utc = datetime.now(timezone.utc)

            def _elapsed_days_since(ts: Any) -> int:
                if not ts:
                    return 0
                try:
                    normalized = str(ts).replace("Z", "+00:00")
                    dt = datetime.fromisoformat(normalized)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    delta = now_utc - dt.astimezone(timezone.utc)
                    return max(0, int(delta.total_seconds() // 86400))
                except Exception:
                    return 0

            for item in rows:
                item["is_theme"] = bool(item.get("is_theme"))
                base_days = item.get("latest_days_since_update")
                if base_days is None:
                    continue
                try:
                    base_days_int = max(0, int(base_days))
                except Exception:
                    base_days_int = 0

                dynamic_days = base_days_int + _elapsed_days_since(item.get("last_seen_at"))
                item["latest_days_since_update_snapshot"] = base_days_int
                item["latest_days_since_update"] = dynamic_days

            return {
                "total": total,
                "limit": safe_limit,
                "offset": safe_offset,
                "items": rows,
            }

    def rebuild_plugin_catalog(self, reset: bool = False) -> Dict[str, Any]:
        rebuilt = 0
        linked = 0

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            if reset:
                cursor.execute("DELETE FROM plugin_catalog_sessions")
                cursor.execute("DELETE FROM plugin_catalog")

            cursor.execute(
                """
                SELECT
                    sr.session_id,
                    ss.created_at AS session_created_at,
                    sr.slug,
                    sr.name,
                    sr.version,
                    sr.score,
                    sr.installations,
                    sr.days_since_update,
                    sr.tested_wp_version,
                    sr.author_trusted,
                    sr.is_risky_category,
                    sr.is_user_facing,
                    sr.is_theme,
                    sr.risk_tags,
                    sr.security_flags,
                    sr.feature_flags,
                    sr.download_link,
                    sr.wp_org_link,
                    sr.cve_search_link,
                    sr.wpscan_link,
                    sr.patchstack_link,
                    sr.wordfence_link,
                    sr.google_dork_link,
                    sr.trac_link
                FROM scan_results sr
                INNER JOIN scan_sessions ss ON ss.id = sr.session_id
                ORDER BY ss.created_at ASC, sr.id ASC
                """
            )

            for row in cursor.fetchall():
                result = PluginResult(
                    slug=row["slug"] or "",
                    name=row["name"] or "",
                    version=row["version"] or "",
                    score=int(row["score"] or 0),
                    installations=int(row["installations"] or 0),
                    days_since_update=int(row["days_since_update"] or 0),
                    tested_wp_version=row["tested_wp_version"] or "",
                    author_trusted=bool(row["author_trusted"]),
                    is_risky_category=bool(row["is_risky_category"]),
                    is_user_facing=bool(row["is_user_facing"]),
                    is_theme=bool(row["is_theme"]),
                    risk_tags=(row["risk_tags"].split(",") if row["risk_tags"] else []),
                    security_flags=(
                        row["security_flags"].split(",") if row["security_flags"] else []
                    ),
                    feature_flags=(
                        row["feature_flags"].split(",") if row["feature_flags"] else []
                    ),
                    download_link=row["download_link"] or "",
                    wp_org_link=row["wp_org_link"] or "",
                    cve_search_link=row["cve_search_link"] or "",
                    wpscan_link=row["wpscan_link"] or "",
                    patchstack_link=row["patchstack_link"] or "",
                    wordfence_link=row["wordfence_link"] or "",
                    google_dork_link=row["google_dork_link"] or "",
                    trac_link=row["trac_link"] or "",
                )

                before_changes = conn.total_changes
                self._upsert_catalog_entry(
                    cursor,
                    int(row["session_id"]),
                    row["session_created_at"] or "",
                    result,
                )
                after_changes = conn.total_changes
                if after_changes > before_changes:
                    rebuilt += 1
                    linked += 1

            conn.commit()

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM plugin_catalog")
            catalog_count = int((cursor.fetchone() or {"c": 0})["c"])
            cursor.execute("SELECT COUNT(*) AS c FROM plugin_catalog_sessions")
            link_count = int((cursor.fetchone() or {"c": 0})["c"])

        return {
            "status": "ok",
            "catalog_count": catalog_count,
            "link_count": link_count,
            "processed_rows": rebuilt,
            "linked_rows": linked,
        }

    def get_catalog_plugin_sessions(
        self, slug: str, is_theme: Optional[bool] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 50), 500))
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            where = "WHERE pc.slug = ?"
            params: List[Any] = [slug]
            if is_theme is not None:
                where += " AND pc.is_theme = ?"
                params.append(1 if is_theme else 0)

            cursor.execute(
                f"""
                SELECT
                    pcs.session_id,
                    pcs.seen_at,
                    pcs.score_snapshot,
                    pcs.version_snapshot,
                    pcs.installations_snapshot,
                    pcs.days_since_update_snapshot,
                    ss.status,
                    ss.total_found,
                    ss.high_risk_count
                FROM plugin_catalog pc
                INNER JOIN plugin_catalog_sessions pcs ON pcs.catalog_id = pc.id
                INNER JOIN scan_sessions ss ON ss.id = pcs.session_id
                {where}
                ORDER BY pcs.seen_at DESC
                LIMIT ?
                """,
                params + [safe_limit],
            )
            return [dict(row) for row in cursor.fetchall()]

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
        """Aggregate Semgrep statistics for a list of plugin slugs using each slug's latest scan."""
        if not slugs:
            return {
                "total_findings": 0,
                "breakdown": {},
                "scanned_count": 0,
                "running_count": 0,
                "pending_count": 0,
                "failed_count": 0,
                "completed_count": 0,
            }

        placeholders = ",".join(["?"] * len(slugs))
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(
                f"""
                SELECT s.slug, s.status, s.summary_json
                FROM semgrep_scans s
                INNER JOIN (
                    SELECT slug, MAX(id) AS max_id
                    FROM semgrep_scans
                    WHERE slug IN ({placeholders})
                    GROUP BY slug
                ) latest ON s.id = latest.max_id
            """,
                slugs,
            )

            rows = cursor.fetchall()
            if not rows:
                return {
                    "total_findings": 0,
                    "breakdown": {},
                    "scanned_count": 0,
                    "running_count": 0,
                    "pending_count": 0,
                    "failed_count": 0,
                    "completed_count": 0,
                }

            breakdown: Dict[str, int] = {}
            completed_count = 0
            failed_count = 0
            pending_count = 0
            running_count = 0

            for row in rows:
                status = str(row["status"] or "").lower()
                if status == "completed":
                    completed_count += 1
                    summary = json.loads(row["summary_json"]) if row["summary_json"] else {}
                    row_breakdown = summary.get("breakdown", {}) if isinstance(summary, dict) else {}
                    for sev, count in (row_breakdown or {}).items():
                        breakdown[str(sev)] = int(breakdown.get(str(sev), 0)) + int(count or 0)
                elif status == "failed":
                    failed_count += 1
                elif status == "running":
                    running_count += 1
                else:
                    pending_count += 1

            total_findings = sum(int(v or 0) for v in breakdown.values())
            scanned_count = completed_count + failed_count

            return {
                "total_findings": total_findings,
                "breakdown": breakdown,
                "scanned_count": scanned_count,
                "running_count": running_count,
                "pending_count": pending_count,
                "failed_count": failed_count,
                "completed_count": completed_count,
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
