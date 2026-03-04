"""
WP-Hunter Database Models

SQLite database schema and connection handling.
"""

import sqlite3
import os
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

# Default database location
DEFAULT_DB_PATH = Path.home() / ".wp-hunter" / "wp_hunter.db"


def ensure_db_dir():
    """Ensure the database directory exists."""
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_db_path() -> Path:
    """Get the database path, respecting environment variable if set."""
    env_path = os.environ.get("WP_HUNTER_DB")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def init_db(db_path: Optional[Path] = None) -> None:
    """Initialize the database with required tables."""
    if db_path is None:
        ensure_db_dir()
        db_path = get_db_path()

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create scan_sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending',
            config_json TEXT,
            total_found INTEGER DEFAULT 0,
            high_risk_count INTEGER DEFAULT 0,
            error_message TEXT
        )
    """)

    # Create scan_results table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            slug TEXT NOT NULL,
            name TEXT,
            version TEXT,
            score INTEGER DEFAULT 0,
            installations INTEGER DEFAULT 0,
            days_since_update INTEGER DEFAULT 0,
            tested_wp_version TEXT,
            author_trusted INTEGER DEFAULT 0,
            is_risky_category INTEGER DEFAULT 0,
            is_user_facing INTEGER DEFAULT 0,
            is_duplicate INTEGER DEFAULT 0,
            is_theme INTEGER DEFAULT 0,
            risk_tags TEXT,
            security_flags TEXT,
            feature_flags TEXT,
            download_link TEXT,
            wp_org_link TEXT,
            cve_search_link TEXT,
            wpscan_link TEXT,
            patchstack_link TEXT,
            wordfence_link TEXT,
            google_dork_link TEXT,
            trac_link TEXT,
            code_analysis_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES scan_sessions(id)
        )
    """)

    # Create index for faster lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_results_session 
        ON scan_results(session_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_results_score 
        ON scan_results(score DESC)
    """)

    # Create favorite_plugins table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS favorite_plugins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            name TEXT,
            version TEXT,
            score INTEGER DEFAULT 0,
            installations INTEGER DEFAULT 0,
            days_since_update INTEGER DEFAULT 0,
            tested_wp_version TEXT,
            is_theme INTEGER DEFAULT 0,
            download_link TEXT,
            wp_org_link TEXT,
            cve_search_link TEXT,
            wpscan_link TEXT,
            patchstack_link TEXT,
            wordfence_link TEXT,
            google_dork_link TEXT,
            trac_link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create semgrep_scans table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS semgrep_scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            version TEXT,
            status TEXT DEFAULT 'pending', -- pending, running, completed, failed
            summary_json TEXT, -- total_findings, breakdown by severity
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)

    # Create semgrep_findings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS semgrep_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            rule_id TEXT NOT NULL,
            message TEXT,
            severity TEXT, -- ERROR, WARNING, INFO
            file_path TEXT,
            line_number INTEGER,
            code_snippet TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (scan_id) REFERENCES semgrep_scans(id) ON DELETE CASCADE
        )
    """)

    # Create plugin_catalog table (global store across all scans)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plugin_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            is_theme INTEGER NOT NULL DEFAULT 0,
            first_seen_session_id INTEGER,
            last_seen_session_id INTEGER,
            first_seen_at TEXT,
            last_seen_at TEXT,
            seen_count INTEGER NOT NULL DEFAULT 0,
            latest_version TEXT,
            latest_score INTEGER NOT NULL DEFAULT 0,
            max_score_ever INTEGER NOT NULL DEFAULT 0,
            latest_installations INTEGER NOT NULL DEFAULT 0,
            latest_days_since_update INTEGER,
            latest_semgrep_findings INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(slug, is_theme)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugin_catalog_last_seen
        ON plugin_catalog(last_seen_at DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugin_catalog_seen_count
        ON plugin_catalog(seen_count DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugin_catalog_max_score
        ON plugin_catalog(max_score_ever DESC)
    """)

    # Create plugin_catalog_sessions table (plugin <-> scan session link)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plugin_catalog_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            catalog_id INTEGER NOT NULL,
            session_id INTEGER NOT NULL,
            seen_at TEXT NOT NULL,
            score_snapshot INTEGER,
            version_snapshot TEXT,
            installations_snapshot INTEGER,
            days_since_update_snapshot INTEGER,
            semgrep_findings_snapshot INTEGER,
            UNIQUE(catalog_id, session_id),
            FOREIGN KEY (catalog_id) REFERENCES plugin_catalog(id) ON DELETE CASCADE,
            FOREIGN KEY (session_id) REFERENCES scan_sessions(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_catalog_sessions_session
        ON plugin_catalog_sessions(session_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_catalog_sessions_catalog
        ON plugin_catalog_sessions(catalog_id)
    """)

    conn.commit()
    conn.close()


@contextmanager
def get_db(db_path: Optional[Path] = None):
    """Get a database connection as a context manager."""
    if db_path is None:
        db_path = get_db_path()

    # Initialize if needed
    if not db_path.exists():
        init_db(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
