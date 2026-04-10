import json

import yaml
from fastapi import BackgroundTasks

from database.models import get_db, init_db
from database.repository import ScanRepository
from scanners.semgrep_scanner import SemgrepScanner
from server.routers.semgrep_service import start_semgrep_scan_for_plugin


class _ScanRequest:
    def __init__(self, slug: str, download_url: str):
        self.slug = slug
        self.download_url = download_url


class _RecordingRepo:
    def __init__(self, version=None):
        self.version = version
        self.created = []

    def get_catalog_latest_version(self, slug, is_theme=False):
        assert slug == "akismet"
        assert is_theme is False
        return self.version

    def create_semgrep_scan(self, slug, version=None):
        self.created.append((slug, version))
        return 41



def test_start_semgrep_scan_for_plugin_uses_catalog_latest_version_when_available():
    repo = _RecordingRepo(version="5.3.1")
    background_tasks = BackgroundTasks()

    result = start_semgrep_scan_for_plugin(
        repo=repo,
        scan_request=_ScanRequest(
            slug="akismet",
            download_url="https://downloads.wordpress.org/plugin/akismet.5.3.1.zip",
        ),
        background_tasks=background_tasks,
    )

    assert result == {"success": True, "scan_id": 41, "status": "pending"}
    assert repo.created == [("akismet", "5.3.1")]
    assert len(background_tasks.tasks) == 1



def test_start_semgrep_scan_for_plugin_falls_back_to_latest_when_catalog_version_missing():
    repo = _RecordingRepo(version=None)
    background_tasks = BackgroundTasks()

    start_semgrep_scan_for_plugin(
        repo=repo,
        scan_request=_ScanRequest(
            slug="akismet",
            download_url="https://downloads.wordpress.org/plugin/akismet.latest.zip",
        ),
        background_tasks=background_tasks,
    )

    assert repo.created == [("akismet", "latest")]



def test_scan_repository_can_lookup_catalog_latest_version(tmp_path):
    db_path = tmp_path / "semgrep_version_lookup.db"
    init_db(db_path)
    repo = ScanRepository(db_path=db_path)

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO plugin_catalog (
                slug, is_theme, first_seen_session_id, last_seen_session_id,
                first_seen_at, last_seen_at, seen_count,
                latest_version, latest_score, max_score_ever,
                latest_installations, latest_days_since_update, latest_semgrep_findings
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("akismet", 0, 1, 1, 1, "5.3.1", 0, 0, 0, 0, None),
        )
        conn.commit()

    assert repo.get_catalog_latest_version("akismet") == "5.3.1"
    assert repo.get_catalog_latest_version("missing-plugin") is None



def test_semgrep_scanner_filters_disabled_custom_rules_and_dedupes_configs(tmp_path):
    output_dir = tmp_path / "semgrep-output"
    output_dir.mkdir(parents=True, exist_ok=True)

    custom_rules = {
        "rules": [
            {"id": "enabled-rule", "pattern": "eval($X)", "message": "Enabled", "languages": ["php"], "severity": "ERROR"},
            {"id": "disabled-rule", "pattern": "exec($X)", "message": "Disabled", "languages": ["php"], "severity": "WARNING"},
        ]
    }
    with open(output_dir / "custom_rules.yaml", "w", encoding="utf-8") as handle:
        yaml.dump(custom_rules, handle, sort_keys=False)
    with open(output_dir / "disabled_rules.json", "w", encoding="utf-8") as handle:
        handle.write('["disabled-rule"]')

    scanner = SemgrepScanner(
        output_dir=str(output_dir),
        use_registry_rules=True,
        registry_rulesets=["php-security", "php-security", "p/php", "security-audit"],
    )

    config_args = scanner._get_config_args()

    assert config_args[0] == "--config"
    filtered_custom_path = config_args[1]
    assert filtered_custom_path.endswith("active_custom_rules.yaml")

    with open(filtered_custom_path, "r", encoding="utf-8") as handle:
        filtered = yaml.safe_load(handle)

    assert [rule["id"] for rule in filtered["rules"]] == ["enabled-rule"]
    assert config_args == [
        "--config",
        filtered_custom_path,
        "--config",
        "p/php",
        "--config",
        "p/security-audit",
    ]



def test_semgrep_scanner_treats_json_errors_as_failed_execution(tmp_path):
    output_dir = tmp_path / "semgrep-error-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "akismet_results.json"
    output_file.write_text(
        '{"results": [], "errors": [{"message": "Invalid rule schema"}]}',
        encoding="utf-8",
    )

    scanner = SemgrepScanner(output_dir=str(output_dir))
    parsed = scanner._parse_output_file(output_file, "")

    assert parsed.success is False
    assert parsed.findings == []
    assert parsed.errors == ["Invalid rule schema"]



def test_semgrep_scanner_treats_syntax_errors_as_non_fatal_when_findings_exist(tmp_path):
    output_dir = tmp_path / "semgrep-partial-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "plugin_results.json"
    output_file.write_text(
        json.dumps(
            {
                "results": [{"check_id": "rule-1", "path": "test.php"}],
                "errors": [
                    {
                        "message": "Syntax error at line /app/Plugins/video-gallery-block/source/public/js/plyr.js:1: `?.5:.0625` was unexpected"
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    scanner = SemgrepScanner(output_dir=str(output_dir))
    parsed = scanner._parse_output_file(output_file, "scan summary on stderr")

    assert parsed.success is True
    assert len(parsed.findings) == 1
    assert parsed.errors == [
        "Syntax error at line /app/Plugins/video-gallery-block/source/public/js/plyr.js:1: `?.5:.0625` was unexpected"
    ]



def test_semgrep_scanner_treats_rule_timeouts_as_non_fatal_when_findings_exist(tmp_path):
    output_dir = tmp_path / "semgrep-rule-timeout-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "plugin_results.json"
    output_file.write_text(
        json.dumps(
            {
                "results": [{"check_id": "rule-1", "path": "test.php"}],
                "errors": [
                    {
                        "message": "Timeout when running javascript.aws-lambda.security.tainted-html-response.tainted-html-response on /app/Plugins/example/source/file.js:"
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    scanner = SemgrepScanner(output_dir=str(output_dir))
    parsed = scanner._parse_output_file(output_file, "scan summary on stderr")

    assert parsed.success is True
    assert len(parsed.findings) == 1
    assert parsed.errors == [
        "Timeout when running javascript.aws-lambda.security.tainted-html-response.tainted-html-response on /app/Plugins/example/source/file.js:"
    ]



def test_semgrep_scanner_keeps_syntax_errors_fatal_when_no_findings_exist(tmp_path):
    output_dir = tmp_path / "semgrep-empty-partial-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "plugin_results.json"
    output_file.write_text(
        json.dumps(
            {
                "results": [],
                "errors": [
                    {
                        "message": "Syntax error at line /app/Plugins/video-gallery-block/source/public/js/plyr.js:1: `?.5:.0625` was unexpected"
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    scanner = SemgrepScanner(output_dir=str(output_dir))
    parsed = scanner._parse_output_file(output_file, "scan summary on stderr")

    assert parsed.success is False
    assert parsed.findings == []
    assert parsed.errors == [
        "Syntax error at line /app/Plugins/video-gallery-block/source/public/js/plyr.js:1: `?.5:.0625` was unexpected",
        "stderr: scan summary on stderr",
    ]



def test_semgrep_scanner_keeps_timeout_findings_as_partial_success(tmp_path):
    output_dir = tmp_path / "semgrep-timeout-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "plugin_results.json"
    output_file.write_text(
        json.dumps(
            {
                "results": [{"check_id": "rule-1", "path": "test.php"}],
                "errors": [
                    {
                        "message": "Syntax error at line /app/Plugins/big-plugin/source/file.php:10: `$foo` was unexpected"
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    scanner = SemgrepScanner(output_dir=str(output_dir))
    parsed = scanner._parse_subprocess_result(
        output_file=output_file,
        returncode=1,
        stderr="timed out after long scan",
        timed_out=True,
    )

    assert parsed.success is True
    assert parsed.partial is True
    assert len(parsed.findings) == 1
    assert parsed.errors == [
        "Scan timeout",
        "Syntax error at line /app/Plugins/big-plugin/source/file.php:10: `$foo` was unexpected",
    ]



def test_semgrep_scanner_marks_timeout_without_output_as_failed(tmp_path):
    output_dir = tmp_path / "semgrep-timeout-empty-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "plugin_results.json"

    scanner = SemgrepScanner(output_dir=str(output_dir))
    parsed = scanner._parse_subprocess_result(
        output_file=output_file,
        returncode=1,
        stderr="timed out after long scan",
        timed_out=True,
    )

    assert parsed.success is False
    assert parsed.partial is False
    assert parsed.findings == []
    assert parsed.errors == ["Semgrep failed (code 1): timed out after long scan"]



def test_semgrep_scanner_skips_invalid_custom_rules_instead_of_disabling_scan(tmp_path, monkeypatch):
    output_dir = tmp_path / "semgrep-invalid-custom-output"
    output_dir.mkdir(parents=True, exist_ok=True)

    custom_rules = {
        "rules": [
            {"id": "valid-rule", "pattern": "eval(...)", "message": "valid", "languages": ["php"], "severity": "ERROR"},
            {"id": "invalid-rule", "pattern": "echo $_GET[$X]", "message": "invalid", "languages": ["php"], "severity": "ERROR"},
        ]
    }
    with open(output_dir / "custom_rules.yaml", "w", encoding="utf-8") as handle:
        yaml.dump(custom_rules, handle, sort_keys=False)

    scanner = SemgrepScanner(output_dir=str(output_dir), use_registry_rules=False)

    def fake_validate(rule):
        return rule.get("id") == "valid-rule"

    monkeypatch.setattr(scanner, "_validate_custom_rule", fake_validate)

    filtered_path = scanner._filter_custom_rules()

    assert filtered_path is not None
    with open(filtered_path, "r", encoding="utf-8") as handle:
        filtered = yaml.safe_load(handle)
    assert [rule["id"] for rule in filtered["rules"]] == ["valid-rule"]

    invalid_log = output_dir / "invalid_custom_rules.json"
    assert invalid_log.exists()
    assert 'invalid-rule' in invalid_log.read_text(encoding='utf-8')
