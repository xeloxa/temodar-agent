# SQLite storage for WordPress plugin metadata

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from wp_hunter.database.models import ensure_db_dir

DEFAULT_METADATA_DB_PATH = Path.home() / ".wp-hunter" / "plugins_metadata.db"


def get_metadata_db_path() -> Path:
    import os

    env_path = os.environ.get("WP_HUNTER_METADATA_DB")
    if env_path:
        return Path(env_path)
    return DEFAULT_METADATA_DB_PATH


def init_metadata_db(db_path: Optional[Path] = None):
    if db_path is None:
        ensure_db_dir()
        db_path = get_metadata_db_path()

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Main plugins table with full API metadata
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plugins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            name TEXT,
            version TEXT,
            author TEXT,
            author_profile TEXT,
            contributors_json TEXT,
            active_installs INTEGER DEFAULT 0,
            downloaded INTEGER DEFAULT 0,
            last_updated TEXT,
            added TEXT,
            tested TEXT,
            requires TEXT,
            requires_php TEXT,
            rating INTEGER DEFAULT 0,
            num_ratings INTEGER DEFAULT 0,
            ratings_json TEXT,
            short_description TEXT,
            description TEXT,
            tags_json TEXT,
            sections_json TEXT,
            download_link TEXT,
            homepage TEXT,
            donate_link TEXT,
            support_threads INTEGER DEFAULT 0,
            support_threads_resolved INTEGER DEFAULT 0,
            banners_json TEXT,
            icons_json TEXT,
            raw_json TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(slug, version)
        )
    """)

    # Create indexes for common queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugins_slug 
        ON plugins(slug)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugins_installs 
        ON plugins(active_installs DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugins_updated 
        ON plugins(last_updated DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugins_fetched 
        ON plugins(fetched_at DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugins_rating 
        ON plugins(rating DESC)
    """)

    # Sync status table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type TEXT NOT NULL,
            pages_synced INTEGER DEFAULT 0,
            plugins_synced INTEGER DEFAULT 0,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            status TEXT DEFAULT 'running',
            error_message TEXT
        )
    """)

    conn.commit()
    conn.close()


@contextmanager
def get_metadata_db(db_path: Optional[Path] = None):
    """Get a metadata database connection as a context manager."""
    if db_path is None:
        db_path = get_metadata_db_path()

    if not db_path.exists():
        init_metadata_db(db_path)

    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
    finally:
        conn.close()


class PluginMetadataRepository:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        init_metadata_db(db_path)

    def upsert_plugin(self, plugin_data: Dict[str, Any]) -> bool:
        with get_metadata_db(self.db_path) as conn:
            cursor = conn.cursor()

            slug = plugin_data.get("slug", "")
            version = plugin_data.get("version", "")

            if not slug:
                return False

            tags_json = json.dumps(plugin_data.get("tags", {}))
            sections_json = json.dumps(plugin_data.get("sections", {}))
            contributors_json = json.dumps(plugin_data.get("contributors", {}))
            ratings_json = json.dumps(plugin_data.get("ratings", {}))
            banners_json = json.dumps(plugin_data.get("banners", {}))
            icons_json = json.dumps(plugin_data.get("icons", {}))
            raw_json = json.dumps(plugin_data)

            try:
                cursor.execute(
                    """
                    INSERT INTO plugins (
                        slug, name, version, author, author_profile, contributors_json,
                        active_installs, downloaded, last_updated, added, tested,
                        requires, requires_php, rating, num_ratings, ratings_json,
                        short_description, description, tags_json, sections_json,
                        download_link, homepage, donate_link, support_threads,
                        support_threads_resolved, banners_json, icons_json, raw_json,
                        fetched_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slug, version) DO UPDATE SET
                        name = excluded.name,
                        author = excluded.author,
                        author_profile = excluded.author_profile,
                        contributors_json = excluded.contributors_json,
                        active_installs = excluded.active_installs,
                        downloaded = excluded.downloaded,
                        last_updated = excluded.last_updated,
                        tested = excluded.tested,
                        requires = excluded.requires,
                        requires_php = excluded.requires_php,
                        rating = excluded.rating,
                        num_ratings = excluded.num_ratings,
                        ratings_json = excluded.ratings_json,
                        short_description = excluded.short_description,
                        description = excluded.description,
                        tags_json = excluded.tags_json,
                        sections_json = excluded.sections_json,
                        download_link = excluded.download_link,
                        homepage = excluded.homepage,
                        donate_link = excluded.donate_link,
                        support_threads = excluded.support_threads,
                        support_threads_resolved = excluded.support_threads_resolved,
                        banners_json = excluded.banners_json,
                        icons_json = excluded.icons_json,
                        raw_json = excluded.raw_json,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    (
                        slug,
                        plugin_data.get("name", ""),
                        version,
                        plugin_data.get("author", ""),
                        plugin_data.get("author_profile", ""),
                        contributors_json,
                        plugin_data.get("active_installs", 0),
                        plugin_data.get("downloaded", 0),
                        plugin_data.get("last_updated", ""),
                        plugin_data.get("added", ""),
                        plugin_data.get("tested", ""),
                        plugin_data.get("requires", ""),
                        plugin_data.get("requires_php", ""),
                        plugin_data.get("rating", 0),
                        plugin_data.get("num_ratings", 0),
                        ratings_json,
                        plugin_data.get("short_description", ""),
                        plugin_data.get("sections", {}).get("description", ""),
                        tags_json,
                        sections_json,
                        plugin_data.get("download_link", ""),
                        plugin_data.get("homepage", ""),
                        plugin_data.get("donate_link", ""),
                        plugin_data.get("support_threads", 0),
                        plugin_data.get("support_threads_resolved", 0),
                        banners_json,
                        icons_json,
                        raw_json,
                        datetime.now().isoformat(),
                        datetime.now().isoformat(),
                    ),
                )
                conn.commit()
                return True
            except Exception as e:
                print(f"Error upserting plugin {slug}: {e}")
                return False

    def bulk_upsert(self, plugins: List[Dict[str, Any]]) -> int:
        success_count = 0
        for plugin in plugins:
            if self.upsert_plugin(plugin):
                success_count += 1
        return success_count

    def query_plugins(
        self,
        min_installs: int = 0,
        max_installs: int = 0,
        min_rating: int = 0,
        tags: Optional[List[str]] = None,
        search: Optional[str] = None,
        author: Optional[str] = None,
        requires_php: Optional[str] = None,
        tested_wp: Optional[str] = None,
        abandoned: bool = False,
        min_days: int = 0,
        max_days: int = 0,
        sort_by: str = "active_installs",
        sort_order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        with get_metadata_db(self.db_path) as conn:
            cursor = conn.cursor()

            conditions = []
            params = []

            if min_installs > 0:
                conditions.append("active_installs >= ?")
                params.append(min_installs)

            if max_installs > 0:
                conditions.append("active_installs <= ?")
                params.append(max_installs)

            if min_rating > 0:
                conditions.append("rating >= ?")
                params.append(min_rating)

            if tags:
                tag_conditions = []
                for tag in tags:
                    tag_conditions.append("tags_json LIKE ?")
                    params.append(f'%"{tag}"%')
                conditions.append(f"({' OR '.join(tag_conditions)})")

            if search:
                conditions.append(
                    "(name LIKE ? OR slug LIKE ? OR short_description LIKE ?)"
                )
                search_pattern = f"%{search}%"
                params.extend([search_pattern, search_pattern, search_pattern])

            if author:
                conditions.append("author LIKE ?")
                params.append(f"%{author}%")

            if requires_php:
                conditions.append("requires_php LIKE ?")
                params.append(f"%{requires_php}%")

            if tested_wp:
                conditions.append("tested LIKE ?")
                params.append(f"%{tested_wp}%")

            if abandoned:
                conditions.append("julianday('now') - julianday(last_updated) > 730")

            if min_days > 0:
                conditions.append("julianday('now') - julianday(last_updated) >= ?")
                params.append(min_days)

            if max_days > 0:
                conditions.append("julianday('now') - julianday(last_updated) <= ?")
                params.append(max_days)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            # Validate sort column
            valid_columns = {
                "active_installs",
                "downloaded",
                "rating",
                "last_updated",
                "fetched_at",
                "name",
                "slug",
            }
            if sort_by not in valid_columns:
                sort_by = "active_installs"

            order = "DESC" if sort_order.lower() == "desc" else "ASC"

            query = f"""
                SELECT * FROM plugins 
                {where_clause}
                ORDER BY {sort_by} {order}
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            cursor.execute(query, params)

            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_last_sync_time(self) -> Optional[str]:
        with get_metadata_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT completed_at FROM sync_status 
                WHERE status = 'completed' 
                ORDER BY completed_at DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return row[0] if row else None

    def get_stats(self) -> Dict[str, Any]:
        with get_metadata_db(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM plugins")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT slug) FROM plugins")
            unique_slugs = cursor.fetchone()[0]

            cursor.execute("SELECT MAX(fetched_at) FROM plugins")
            last_sync = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM plugins WHERE active_installs >= 10000
            """)
            popular = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM plugins WHERE active_installs >= 100000
            """)
            very_popular = cursor.fetchone()[0]

            return {
                "total_records": total,
                "unique_plugins": unique_slugs,
                "last_sync": last_sync,
                "popular_10k": popular,
                "popular_100k": very_popular,
            }

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        if not row:
            return {}

        result = dict(row)

        # Parse JSON fields
        json_fields = [
            "tags_json",
            "sections_json",
            "contributors_json",
            "ratings_json",
            "banners_json",
            "icons_json",
        ]

        for field in json_fields:
            if field in result and result[field]:
                try:
                    key = field.replace("_json", "")
                    result[key] = json.loads(result[field])
                except:
                    pass

        return result

    def record_sync_start(self, sync_type: str) -> int:
        with get_metadata_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sync_status (sync_type, status)
                VALUES (?, 'running')
            """,
                (sync_type,),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def record_sync_complete(
        self, sync_id: int, pages: int, plugins: int, error: Optional[str] = None
    ) -> None:
        with get_metadata_db(self.db_path) as conn:
            cursor = conn.cursor()
            status = "failed" if error else "completed"
            cursor.execute(
                """
                UPDATE sync_status 
                SET pages_synced = ?, plugins_synced = ?, 
                    completed_at = CURRENT_TIMESTAMP, status = ?, error_message = ?
                WHERE id = ?
            """,
                (pages, plugins, status, error, sync_id),
            )
            conn.commit()
