import json
import sqlite3
from pathlib import Path

from ai.context_builder import (
    build_plugin_context,
    ensure_thread_source_dir,
    resolve_thread_source_path,
)
from ai.repository import AIRepository
from database.models import init_db
from runtime_paths import RuntimePaths



def _runtime_paths(runtime_root):
    return RuntimePaths(
        root=runtime_root,
        db_file=runtime_root / "temodar_agent.db",
        logs_dir=runtime_root / "logs",
        plugins_dir=runtime_root / "plugins",
        semgrep_dir=runtime_root / "semgrep",
        semgrep_outputs_dir=runtime_root / "semgrep-results",
        approvals_dir=runtime_root / "approvals",
    )


def _insert_scan_session(cursor, status, total_found, high_risk_count):
    cursor.execute(
        "INSERT INTO scan_sessions (status, total_found, high_risk_count) VALUES (?, ?, ?)",
        (status, total_found, high_risk_count),
    )
    return cursor.lastrowid


def _insert_plugin_catalog(
    cursor,
    slug,
    session_id,
    version,
    score,
    installations,
    days_since_update,
    semgrep_findings,
):
    cursor.execute(
        """
        INSERT INTO plugin_catalog (
            slug, is_theme, first_seen_session_id, last_seen_session_id,
            first_seen_at, last_seen_at, seen_count, latest_version,
            latest_score, max_score_ever, latest_installations,
            latest_days_since_update, latest_semgrep_findings
        ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            slug,
            0,
            session_id,
            session_id,
            1,
            version,
            score,
            score,
            installations,
            days_since_update,
            semgrep_findings,
        ),
    )
    return cursor.lastrowid


def _insert_plugin_catalog_session(
    cursor,
    catalog_id,
    session_id,
    score,
    version,
    installations,
    days_since_update,
    semgrep_findings,
):
    cursor.execute(
        """
        INSERT INTO plugin_catalog_sessions (
            catalog_id, session_id, seen_at, score_snapshot, version_snapshot,
            installations_snapshot, days_since_update_snapshot, semgrep_findings_snapshot
        ) VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
        """,
        (
            catalog_id,
            session_id,
            score,
            version,
            installations,
            days_since_update,
            semgrep_findings,
        ),
    )


def _insert_semgrep_scan(cursor, slug, version, status, summary):
    cursor.execute(
        "INSERT INTO semgrep_scans (slug, version, status, summary_json) VALUES (?, ?, ?, ?)",
        (slug, version, status, json.dumps(summary)),
    )
    return cursor.lastrowid


def _insert_semgrep_finding(
    cursor,
    scan_id,
    rule_id,
    message,
    severity,
    file_path,
    line_number,
    code_snippet,
    metadata,
):
    cursor.execute(
        """
        INSERT INTO semgrep_findings (
            scan_id, rule_id, message, severity, file_path, line_number, code_snippet, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan_id,
            rule_id,
            message,
            severity,
            file_path,
            line_number,
            code_snippet,
            json.dumps(metadata),
        ),
    )


def test_resolve_thread_source_path_uses_thread_scope_and_requires_matching_scan_result(monkeypatch, tmp_path):
    runtime_root = tmp_path / ".temodar-agent"
    monkeypatch.setattr("ai.context_builder.resolve_runtime_paths", lambda: _runtime_paths(runtime_root))
    db_path = tmp_path / "ai_context.db"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        session_id = _insert_scan_session(cursor, "completed", 1, 0)
        cursor.execute(
            """
            INSERT INTO scan_results (session_id, slug, version, is_theme)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, "hello-dolly", "1.0.0", 0),
        )
        cursor.execute(
            """
            INSERT INTO scan_results (session_id, slug, version, is_theme)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, "hello-dolly", "2.0.0", 1),
        )
        conn.commit()

    assert session_id is not None
    assert resolve_thread_source_path(
        db_path=db_path,
        plugin_slug="hello-dolly",
        is_theme=False,
        last_scan_session_id=session_id,
    ) == str(runtime_root / "plugins" / "Plugins" / "hello-dolly" / "source")
    assert resolve_thread_source_path(
        db_path=db_path,
        plugin_slug="hello-dolly",
        is_theme=True,
        last_scan_session_id=session_id,
    ) == str(runtime_root / "plugins" / "Themes" / "hello-dolly" / "source")

    assert session_id is not None

    missing_session_id = session_id + 1
    repository = AIRepository(db_path=db_path)
    plugin_thread = repository.get_or_create_thread(
        plugin_slug="hello-dolly",
        is_theme=False,
        last_scan_session_id=missing_session_id,
    )
    theme_thread = repository.get_or_create_thread(
        plugin_slug="hello-dolly",
        is_theme=True,
        last_scan_session_id=missing_session_id,
    )

    assert plugin_thread["id"] != theme_thread["id"]

    try:
        resolve_thread_source_path(
            db_path=db_path,
            plugin_slug="hello-dolly",
            is_theme=False,
            last_scan_session_id=missing_session_id,
        )
    except LookupError as exc:
        assert str(exc) == "Trusted source path requires a matching scan result for the selected thread scope."
    else:
        raise AssertionError("Expected plugin thread source path lookup to fail for missing scan result")

    try:
        resolve_thread_source_path(
            db_path=db_path,
            plugin_slug="hello-dolly",
            is_theme=True,
            last_scan_session_id=missing_session_id,
        )
    except LookupError as exc:
        assert str(exc) == "Trusted source path requires a matching scan result for the selected thread scope."
    else:
        raise AssertionError("Expected theme thread source path lookup to fail for missing scan result")



def test_build_plugin_context_returns_only_selected_plugin_with_latest_relevant_semgrep_data(
    tmp_path,
):
    db_path = tmp_path / "ai_context.db"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        selected_session_id = _insert_scan_session(cursor, "completed", 5, 2)
        other_session_id = _insert_scan_session(cursor, "completed", 1, 0)

        target_catalog_id = _insert_plugin_catalog(
            cursor,
            "target-plugin",
            selected_session_id,
            "1.2.3",
            87,
            1000,
            12,
            2,
        )
        other_catalog_id = _insert_plugin_catalog(
            cursor,
            "other-plugin",
            other_session_id,
            "9.9.9",
            10,
            5,
            90,
            1,
        )

        _insert_plugin_catalog_session(
            cursor,
            target_catalog_id,
            selected_session_id,
            87,
            "1.2.3",
            1000,
            12,
            2,
        )
        _insert_plugin_catalog_session(
            cursor,
            other_catalog_id,
            other_session_id,
            10,
            "9.9.9",
            5,
            90,
            1,
        )

        stale_scan_id = _insert_semgrep_scan(
            cursor,
            "target-plugin",
            "1.0.0",
            "completed",
            {"total_findings": 1, "breakdown": {"WARNING": 1}},
        )
        _insert_semgrep_finding(
            cursor,
            stale_scan_id,
            "stale.rule",
            "Stale issue",
            "WARNING",
            "target-plugin/old.php",
            7,
            "old()",
            {"category": "stale"},
        )

        relevant_scan_id = _insert_semgrep_scan(
            cursor,
            "target-plugin",
            "1.2.3",
            "completed",
            {"total_findings": 2, "breakdown": {"ERROR": 1, "WARNING": 1}},
        )
        _insert_semgrep_finding(
            cursor,
            relevant_scan_id,
            "security.eval",
            "Use of eval detected",
            "ERROR",
            "target-plugin/includes/danger.php",
            42,
            "eval($payload);",
            {"owasp": "A03"},
        )
        _insert_semgrep_finding(
            cursor,
            relevant_scan_id,
            "security.input",
            "Unsanitized input",
            "WARNING",
            "target-plugin/includes/input.php",
            10,
            "$_GET['id']",
            {"source": "querystring"},
        )

        unrelated_scan_id = _insert_semgrep_scan(
            cursor,
            "other-plugin",
            "9.9.9",
            "completed",
            {"total_findings": 1, "breakdown": {"INFO": 1}},
        )
        _insert_semgrep_finding(
            cursor,
            unrelated_scan_id,
            "other.rule",
            "Other plugin issue",
            "INFO",
            "other-plugin/other.php",
            3,
            "$x = 1;",
            {"plugin": "other-plugin"},
        )
        conn.commit()

    assert selected_session_id is not None
    context = build_plugin_context(
        db_path=db_path,
        plugin_slug="target-plugin",
        is_theme=False,
        source_path="/tmp/target-plugin",
        last_scan_session_id=selected_session_id,
    )

    assert context["source_path"] == "/tmp/target-plugin"
    assert context["plugin"]["slug"] == "target-plugin"
    assert context["plugin"]["is_theme"] == 0
    assert context["plugin"]["latest_version"] == "1.2.3"
    assert context["plugin"]["last_scan_session_id"] == selected_session_id
    assert context["plugin"]["score"] == 87
    assert context["plugin"]["installations"] == 1000
    assert context["plugin"]["days_since_update"] == 12
    assert context["plugin"]["semgrep_findings"] == 2
    assert context["plugin"]["metrics"] == {
        "risk_score": 87,
        "installations": 1000,
        "days_since_update": 12,
        "latest_version": "1.2.3",
        "semgrep_findings": 2,
    }

    assert context["semgrep"]["scan"]["id"] == relevant_scan_id
    assert context["semgrep"]["snapshot"] == {
        "findings_count": 2,
        "latest_version": "1.2.3",
        "has_completed_scan": True,
        "summary_total_findings": 2,
    }
    assert context["semgrep"]["scan"]["version"] == "1.2.3"
    assert context["semgrep"]["summary"] == {
        "total_findings": 2,
        "breakdown": {"ERROR": 1, "WARNING": 1},
    }
    assert [finding["rule_id"] for finding in context["semgrep"]["findings"]] == [
        "security.eval",
        "security.input",
    ]

    serialized = json.dumps(context)
    assert "other-plugin" not in serialized
    assert "Other plugin issue" not in serialized
    assert "stale.rule" not in serialized


def test_build_plugin_context_does_not_return_stale_older_version_semgrep_findings(
    tmp_path,
):
    db_path = tmp_path / "ai_context.db"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        session_id = _insert_scan_session(cursor, "completed", 2, 0)
        catalog_id = _insert_plugin_catalog(
            cursor,
            "target-plugin",
            session_id,
            "2.0.0",
            42,
            500,
            5,
            0,
        )
        _insert_plugin_catalog_session(
            cursor,
            catalog_id,
            session_id,
            42,
            "2.0.0",
            500,
            5,
            0,
        )

        old_scan_id = _insert_semgrep_scan(
            cursor,
            "target-plugin",
            "1.9.9",
            "completed",
            {"total_findings": 1, "breakdown": {"WARNING": 1}},
        )
        _insert_semgrep_finding(
            cursor,
            old_scan_id,
            "stale.rule",
            "Older version issue",
            "WARNING",
            "target-plugin/legacy.php",
            11,
            "legacy()",
            {"category": "stale"},
        )
        conn.commit()

    assert session_id is not None
    context = build_plugin_context(
        db_path=db_path,
        plugin_slug="target-plugin",
        is_theme=False,
        source_path="/tmp/target-plugin",
        last_scan_session_id=session_id,
    )

    assert context["plugin"]["latest_version"] == "2.0.0"
    assert context["plugin"]["metrics"] == {
        "risk_score": 42,
        "installations": 500,
        "days_since_update": 5,
        "latest_version": "2.0.0",
        "semgrep_findings": 0,
    }
    assert context["semgrep"] == {
        "scan": None,
        "summary": {},
        "findings": [],
        "snapshot": {
            "findings_count": 0,
            "latest_version": "2.0.0",
            "has_completed_scan": False,
            "summary_total_findings": 0,
        },
    }


def test_ensure_thread_source_dir_accepts_canonical_runtime_plugin_path(monkeypatch, tmp_path):
    runtime_root = tmp_path / ".temodar-agent"
    monkeypatch.setattr("ai.context_builder.resolve_runtime_paths", lambda: _runtime_paths(runtime_root))

    downloaded_source = runtime_root / "plugins" / "Plugins" / "akismet" / "source"
    downloaded_source.mkdir(parents=True, exist_ok=True)
    (downloaded_source / "plugin.php").write_text("<?php // ok", encoding="utf-8")

    monkeypatch.setattr(
        "ai.context_builder.resolve_existing_thread_source_path",
        lambda **__: None,
    )
    monkeypatch.setattr(
        "ai.context_builder.resolve_source_download_info",
        lambda **__: {
            "download_url": "https://downloads.wordpress.org/plugin/akismet.latest.zip",
            "version": "1.0.0",
        },
    )

    class _FakeDownloader:
        def __init__(self, base_dir):
            assert Path(base_dir) == runtime_root / "plugins"

        def download_and_extract(self, download_url, slug, verbose=False):
            assert download_url == "https://downloads.wordpress.org/plugin/akismet.latest.zip"
            assert slug == "akismet"
            assert verbose is False
            return downloaded_source

    monkeypatch.setattr("ai.context_builder.PluginDownloader", _FakeDownloader)

    resolved = ensure_thread_source_dir(
        db_path=tmp_path / "ai_context.db",
        plugin_slug="akismet",
        is_theme=False,
        last_scan_session_id=1,
        root_path=tmp_path / "workspace",
    )

    assert resolved == downloaded_source.resolve()



def test_build_plugin_context_returns_empty_payload_when_plugin_is_missing(tmp_path):
    db_path = tmp_path / "ai_context.db"
    init_db(db_path)

    context = build_plugin_context(
        db_path=db_path,
        plugin_slug="missing-plugin",
        is_theme=False,
        source_path="/tmp/missing-plugin",
        last_scan_session_id=999,
    )

    assert context == {
        "source_path": "/tmp/missing-plugin",
        "plugin": None,
        "semgrep": {"scan": None, "summary": {}, "findings": []},
    }
