"""
Temodar Agent Database Models

SQLite database schema and connection handling.
"""

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Optional

from runtime_paths import resolve_runtime_paths

logger = logging.getLogger("temodar_agent")

SCAN_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS scan_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending',
        config_json TEXT,
        total_found INTEGER DEFAULT 0,
        high_risk_count INTEGER DEFAULT 0,
        error_message TEXT
    )
    """,
    """
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
        trac_link TEXT,
        code_analysis_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES scan_sessions(id)
    )
    """,
    """
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
        trac_link TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS semgrep_scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL,
        version TEXT,
        status TEXT DEFAULT 'pending',
        summary_json TEXT,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS semgrep_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id INTEGER NOT NULL,
        rule_id TEXT NOT NULL,
        message TEXT,
        severity TEXT,
        file_path TEXT,
        line_number INTEGER,
        code_snippet TEXT,
        metadata_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (scan_id) REFERENCES semgrep_scans(id) ON DELETE CASCADE
    )
    """,
    """
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
    """,
    """
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
    """,
]

AI_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ai_provider_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_key TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        provider TEXT NOT NULL,
        provider_label TEXT,
        api_key TEXT,
        model TEXT,
        base_url TEXT,
        is_active INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_threads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plugin_slug TEXT NOT NULL,
        is_theme INTEGER NOT NULL DEFAULT 0,
        title TEXT,
        last_scan_session_id INTEGER,
        conversation_summary TEXT,
        analysis_summary TEXT,
        important_files_json TEXT,
        findings_summary TEXT,
        architecture_notes TEXT,
        last_route_hint TEXT,
        last_source_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        tool_calls_json TEXT,
        tool_results_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (thread_id) REFERENCES ai_threads(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        provider_label TEXT,
        model TEXT,
        message_id INTEGER,
        workspace_path TEXT,
        error_message TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        FOREIGN KEY (thread_id) REFERENCES ai_threads(id) ON DELETE CASCADE,
        FOREIGN KEY (message_id) REFERENCES ai_messages(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_run_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        agent_name TEXT,
        task_id TEXT,
        payload_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES ai_runs(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_run_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        task_id TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        assignee TEXT,
        depends_on_json TEXT,
        result_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(run_id, task_id),
        FOREIGN KEY (run_id) REFERENCES ai_runs(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_run_approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL UNIQUE,
        thread_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        control_path TEXT,
        mode TEXT,
        request_payload_json TEXT,
        decision TEXT,
        decided_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES ai_runs(id) ON DELETE CASCADE,
        FOREIGN KEY (thread_id) REFERENCES ai_threads(id) ON DELETE CASCADE
    )
    """,
]

INDEX_STATEMENTS = [
    """
    CREATE INDEX IF NOT EXISTS idx_results_session
    ON scan_results(session_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_results_score
    ON scan_results(score DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plugin_catalog_last_seen
    ON plugin_catalog(last_seen_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plugin_catalog_seen_count
    ON plugin_catalog(seen_count DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plugin_catalog_max_score
    ON plugin_catalog(max_score_ever DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_catalog_sessions_session
    ON plugin_catalog_sessions(session_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_catalog_sessions_catalog
    ON plugin_catalog_sessions(catalog_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_run_events_run
    ON ai_run_events(run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_run_tasks_run
    ON ai_run_tasks(run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_threads_plugin
    ON ai_threads(plugin_slug, is_theme)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_runs_message
    ON ai_runs(message_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_messages_thread
    ON ai_messages(thread_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_runs_thread
    ON ai_runs(thread_id)
    """,
]

AI_MIGRATION_STATEMENTS = [
    "ALTER TABLE ai_provider_settings ADD COLUMN provider_label TEXT",
    "ALTER TABLE ai_provider_settings ADD COLUMN profile_key TEXT",
    "ALTER TABLE ai_provider_settings ADD COLUMN display_name TEXT",
    "ALTER TABLE ai_provider_settings ADD COLUMN models_json TEXT",
    "ALTER TABLE ai_threads ADD COLUMN is_theme INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE ai_threads ADD COLUMN title TEXT",
    "ALTER TABLE ai_threads ADD COLUMN last_scan_session_id INTEGER",
    "ALTER TABLE ai_threads ADD COLUMN conversation_summary TEXT",
    "ALTER TABLE ai_threads ADD COLUMN analysis_summary TEXT",
    "ALTER TABLE ai_threads ADD COLUMN important_files_json TEXT",
    "ALTER TABLE ai_threads ADD COLUMN findings_summary TEXT",
    "ALTER TABLE ai_threads ADD COLUMN architecture_notes TEXT",
    "ALTER TABLE ai_threads ADD COLUMN last_route_hint TEXT",
    "ALTER TABLE ai_threads ADD COLUMN last_source_path TEXT",
    "ALTER TABLE ai_messages ADD COLUMN tool_calls_json TEXT",
    "ALTER TABLE ai_messages ADD COLUMN tool_results_json TEXT",
    "ALTER TABLE ai_runs ADD COLUMN provider_label TEXT",
    "ALTER TABLE ai_runs ADD COLUMN message_id INTEGER",
    "ALTER TABLE ai_runs ADD COLUMN workspace_path TEXT",
    "ALTER TABLE ai_runs ADD COLUMN error_message TEXT",
    "CREATE TABLE IF NOT EXISTS ai_run_events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, event_type TEXT NOT NULL, agent_name TEXT, task_id TEXT, payload_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (run_id) REFERENCES ai_runs(id) ON DELETE CASCADE)",
    "CREATE TABLE IF NOT EXISTS ai_run_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, task_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, assignee TEXT, depends_on_json TEXT, result_text TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(run_id, task_id), FOREIGN KEY (run_id) REFERENCES ai_runs(id) ON DELETE CASCADE)",
    "CREATE INDEX IF NOT EXISTS idx_ai_runs_message ON ai_runs(message_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_run_events_run ON ai_run_events(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_run_tasks_run ON ai_run_tasks(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_ai_threads_plugin_scope_guard ON ai_threads(plugin_slug, is_theme)",
]

DEFAULT_DB_PATH = resolve_runtime_paths().db_file


def _table_has_unique_thread_scope(cursor) -> bool:
    cursor.execute("PRAGMA index_list(ai_threads)")
    for row in cursor.fetchall():
        if not row[2]:
            continue
        index_name = row[1]
        cursor.execute(f"PRAGMA index_info({index_name!r})")
        columns = [index_row[2] for index_row in cursor.fetchall()]
        if columns == ["plugin_slug", "is_theme"]:
            return True
    return False


def _table_columns(cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in cursor.fetchall()}


def _table_sql_references(cursor, table_name: str, referenced_name: str) -> bool:
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    row = cursor.fetchone()
    sql = row[0] if row and row[0] else ""
    return referenced_name in sql


def _safe_execute(cursor, statement: str) -> None:
    try:
        cursor.execute(statement)
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "duplicate column name" in message or "already exists" in message:
            return
        raise


def _execute_statements(cursor, statements: list[str]) -> None:
    for statement in statements:
        cursor.execute(statement)


def _safe_execute_statements(cursor, statements: list[str]) -> None:
    for statement in statements:
        _safe_execute(cursor, statement)


def _migrate_ai_threads_for_multi_session(cursor) -> None:
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ai_threads'"
    )
    if cursor.fetchone() is None or not _table_has_unique_thread_scope(cursor):
        return

    cursor.execute("ALTER TABLE ai_threads RENAME TO ai_threads_legacy")
    cursor.execute(
        """
        CREATE TABLE ai_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plugin_slug TEXT NOT NULL,
            is_theme INTEGER NOT NULL DEFAULT 0,
            title TEXT,
            last_scan_session_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO ai_threads (id, plugin_slug, is_theme, title, last_scan_session_id, created_at, updated_at)
        SELECT id, plugin_slug, is_theme, title, last_scan_session_id, created_at, updated_at
        FROM ai_threads_legacy
        ORDER BY id ASC
        """
    )
    cursor.execute("DROP TABLE ai_threads_legacy")


def _migrate_ai_provider_settings_for_profiles(cursor) -> None:
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ai_provider_settings'"
    )
    if cursor.fetchone() is None:
        return

    columns = _table_columns(cursor, "ai_provider_settings")
    if {"profile_key", "display_name"}.issubset(columns):
        return

    cursor.execute("ALTER TABLE ai_provider_settings RENAME TO ai_provider_settings_legacy")
    cursor.execute(
        """
        CREATE TABLE ai_provider_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_label TEXT,
            api_key TEXT,
            model TEXT,
            models_json TEXT,
            base_url TEXT,
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO ai_provider_settings (
            id, profile_key, display_name, provider, provider_label, api_key, model, base_url, is_active, created_at, updated_at
        )
        SELECT
            id,
            LOWER(provider || '-' || COALESCE(NULLIF(REPLACE(model, ' ', '-'), ''), 'default')),
            COALESCE(provider_label, provider) || ' / ' || COALESCE(NULLIF(model, ''), 'default'),
            provider,
            COALESCE(provider_label, provider),
            api_key,
            model,
            base_url,
            COALESCE(is_active, 0),
            created_at,
            updated_at
        FROM ai_provider_settings_legacy
        ORDER BY id ASC
        """
    )
    cursor.execute("DROP TABLE ai_provider_settings_legacy")


def _rebuild_ai_messages_table(cursor) -> None:
    if not _table_sql_references(cursor, "ai_messages", '"ai_threads_legacy"'):
        return
    legacy_columns = _table_columns(cursor, "ai_messages")
    cursor.execute("ALTER TABLE ai_messages RENAME TO ai_messages_legacy")
    cursor.execute(
        """
        CREATE TABLE ai_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool_calls_json TEXT,
            tool_results_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (thread_id) REFERENCES ai_threads(id) ON DELETE CASCADE
        )
        """
    )
    tool_calls_select = "tool_calls_json" if "tool_calls_json" in legacy_columns else "NULL"
    tool_results_select = "tool_results_json" if "tool_results_json" in legacy_columns else "NULL"
    cursor.execute(
        f"""
        INSERT INTO ai_messages (id, thread_id, role, content, tool_calls_json, tool_results_json, created_at)
        SELECT id, thread_id, role, content, {tool_calls_select}, {tool_results_select}, created_at
        FROM ai_messages_legacy
        ORDER BY id ASC
        """
    )
    cursor.execute("DROP TABLE ai_messages_legacy")


def _rebuild_ai_runs_table(cursor) -> None:
    if not _table_sql_references(cursor, "ai_runs", '"ai_threads_legacy"'):
        return
    legacy_columns = _table_columns(cursor, "ai_runs")
    cursor.execute("ALTER TABLE ai_runs RENAME TO ai_runs_legacy")
    cursor.execute(
        """
        CREATE TABLE ai_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            provider_label TEXT,
            model TEXT,
            message_id INTEGER,
            workspace_path TEXT,
            error_message TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (thread_id) REFERENCES ai_threads(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES ai_messages(id) ON DELETE SET NULL
        )
        """
    )
    provider_label_select = "provider_label" if "provider_label" in legacy_columns else "NULL"
    message_id_select = "message_id" if "message_id" in legacy_columns else "NULL"
    workspace_path_select = "workspace_path" if "workspace_path" in legacy_columns else "NULL"
    error_message_select = "error_message" if "error_message" in legacy_columns else "NULL"
    cursor.execute(
        f"""
        INSERT INTO ai_runs (
            id, thread_id, provider, provider_label, model, message_id, workspace_path,
            error_message, status, created_at, completed_at
        )
        SELECT
            id, thread_id, provider, {provider_label_select}, model, {message_id_select}, {workspace_path_select},
            {error_message_select}, status, created_at, completed_at
        FROM ai_runs_legacy
        ORDER BY id ASC
        """
    )
    cursor.execute("DROP TABLE ai_runs_legacy")


def _rebuild_ai_run_event_tables(cursor) -> None:
    if _table_sql_references(cursor, "ai_run_events", "ai_runs_legacy"):
        cursor.execute("ALTER TABLE ai_run_events RENAME TO ai_run_events_legacy")
        cursor.execute(
            """
            CREATE TABLE ai_run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                agent_name TEXT,
                task_id TEXT,
                payload_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES ai_runs(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO ai_run_events (id, run_id, event_type, agent_name, task_id, payload_json, created_at)
            SELECT id, run_id, event_type, agent_name, task_id, payload_json, created_at
            FROM ai_run_events_legacy
            ORDER BY id ASC
            """
        )
        cursor.execute("DROP TABLE ai_run_events_legacy")

    if _table_sql_references(cursor, "ai_run_tasks", "ai_runs_legacy"):
        cursor.execute("ALTER TABLE ai_run_tasks RENAME TO ai_run_tasks_legacy")
        cursor.execute(
            """
            CREATE TABLE ai_run_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                task_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                assignee TEXT,
                depends_on_json TEXT,
                result_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_id, task_id),
                FOREIGN KEY (run_id) REFERENCES ai_runs(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO ai_run_tasks (id, run_id, task_id, title, status, assignee, depends_on_json, result_text, created_at, updated_at)
            SELECT id, run_id, task_id, title, status, assignee, depends_on_json, result_text, created_at, updated_at
            FROM ai_run_tasks_legacy
            ORDER BY id ASC
            """
        )
        cursor.execute("DROP TABLE ai_run_tasks_legacy")


def _backfill_ai_defaults(cursor) -> None:
    cursor.execute("UPDATE ai_provider_settings SET provider_label = COALESCE(provider_label, provider)")
    cursor.execute("UPDATE ai_provider_settings SET profile_key = COALESCE(profile_key, LOWER(provider || '-' || COALESCE(NULLIF(REPLACE(model, ' ', '-'), ''), 'default'))) WHERE profile_key IS NULL OR profile_key = ''")
    cursor.execute("UPDATE ai_provider_settings SET display_name = COALESCE(display_name, COALESCE(provider_label, provider) || ' / ' || COALESCE(NULLIF(model, ''), 'default')) WHERE display_name IS NULL OR display_name = ''")
    cursor.execute("UPDATE ai_provider_settings SET models_json = CASE WHEN models_json IS NULL OR models_json = '' THEN CASE WHEN model IS NULL OR TRIM(model) = '' THEN '[]' ELSE json_array(model) END ELSE models_json END")
    cursor.execute("UPDATE ai_threads SET is_theme = COALESCE(is_theme, 0)")


def _migrate_ai_tables(cursor) -> None:
    _rebuild_ai_messages_table(cursor)
    _rebuild_ai_runs_table(cursor)
    _rebuild_ai_run_event_tables(cursor)
    _migrate_ai_threads_for_multi_session(cursor)
    _migrate_ai_provider_settings_for_profiles(cursor)
    _rebuild_ai_messages_table(cursor)
    _rebuild_ai_runs_table(cursor)
    _rebuild_ai_run_event_tables(cursor)
    _safe_execute_statements(cursor, AI_MIGRATION_STATEMENTS)
    _backfill_ai_defaults(cursor)


def _is_directory_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, delete=True):
            pass
        return True
    except OSError:
        return False


def ensure_db_dir(path: Optional[Path] = None) -> Path:
    """Ensure the database directory exists and return the effective path."""
    target = path or DEFAULT_DB_PATH
    if _is_directory_writable(target.parent):
        return target

    raise PermissionError(f"Database directory is not writable: {target.parent}")


def get_db_path() -> Path:
    """Get the database path, respecting environment variable if set."""
    env_path = os.environ.get("TEMODAR_AGENT_DB")
    return Path(env_path) if env_path else DEFAULT_DB_PATH


def _resolve_db_path(db_path: Optional[Path]) -> Path:
    """Resolve the effective database path and ensure its directory exists."""
    if db_path is not None:
        return ensure_db_dir(db_path)

    env_path = os.environ.get("TEMODAR_AGENT_DB")
    if env_path:
        return ensure_db_dir(Path(env_path))

    return ensure_db_dir()


def init_db(db_path: Optional[Path] = None) -> None:
    """Initialize the database with required tables."""
    resolved_db_path = _resolve_db_path(db_path)
    conn = sqlite3.connect(str(resolved_db_path))
    cursor = conn.cursor()
    try:
        _execute_statements(cursor, SCAN_SCHEMA_STATEMENTS)
        _execute_statements(cursor, AI_SCHEMA_STATEMENTS)
        _migrate_ai_tables(cursor)
        _execute_statements(cursor, INDEX_STATEMENTS)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_db(db_path: Optional[Path] = None):
    """Get a database connection as a context manager."""
    resolved_db_path = _resolve_db_path(db_path)
    if not resolved_db_path.exists():
        init_db(resolved_db_path)

    conn = sqlite3.connect(str(resolved_db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
