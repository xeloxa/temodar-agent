import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from server.routers import semgrep_helpers
from server.routers.semgrep_helpers import get_disabled_config, save_custom_rules_document

DB_TEST_PATH = Path(tempfile.gettempdir()) / "temodar-agent-semgrep-router-tests.db"
os.environ.setdefault("TEMODAR_AGENT_DB", str(DB_TEST_PATH))

from server.app import create_app


class _DummyRepo:
    def __init__(self):
        self.semgrep_scan_calls = []

    def create_semgrep_scan(self, slug, version=None):
        self.semgrep_scan_calls.append((slug, version))
        return 77

    def get_catalog_latest_version(self, slug, is_theme=False):
        if slug == "akismet" and not is_theme:
            return "5.3.1"
        return None

    def get_semgrep_scan(self, slug):
        if slug == "akismet":
            return {"id": 77, "slug": slug, "status": "completed"}
        return None

    def get_session_results(self, session_id, *args, **kwargs):
        del args, kwargs
        if session_id == 10:
            return [
                {
                    "slug": "akismet",
                    "version": "5.3.1",
                    "download_link": "https://downloads.wordpress.org/plugin/akismet.5.3.1.zip",
                },
                {
                    "slug": "hello-dolly",
                    "version": "1.7.2",
                    "download_link": "https://downloads.wordpress.org/plugin/hello-dolly.1.7.2.zip",
                },
            ]
        return []

    def get_semgrep_stats_for_slugs(self, slugs):
        if not slugs:
            return {
                "scanned_count": 0,
                "total_findings": 0,
                "breakdown": {},
                "running_count": 0,
                "pending_count": 0,
                "failed_count": 0,
                "completed_count": 0,
            }
        return {
            "scanned_count": 1,
            "total_findings": 3,
            "breakdown": {"HIGH": 1, "MEDIUM": 2},
            "running_count": 0,
            "pending_count": 1,
            "failed_count": 0,
            "completed_count": 1,
        }



def _create_client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "server.app.update_manager.manager.get_status",
        lambda force=False: {"status": "ok", "force": force},
    )
    test_db_path = tmp_path / "runtime-root" / "temodar_agent.db"
    monkeypatch.setattr("database.models.DEFAULT_DB_PATH", test_db_path)
    return TestClient(create_app(), base_url="http://localhost")


def _patch_semgrep_state(monkeypatch, tmp_path: Path):
    from server.routers import semgrep_helpers, semgrep_service

    state_dir = tmp_path / "runtime-root" / "semgrep"
    custom_rules_path = state_dir / "custom_rules.yaml"
    disabled_config_path = state_dir / "disabled_config.json"
    monkeypatch.setattr(semgrep_helpers, "SEMGREP_STATE_DIR", state_dir)
    monkeypatch.setattr(semgrep_helpers, "CUSTOM_RULES_PATH", custom_rules_path)
    monkeypatch.setattr(semgrep_helpers, "DISABLED_CONFIG_PATH", disabled_config_path)
    monkeypatch.setattr(semgrep_service, "CUSTOM_RULES_PATH", custom_rules_path)
    return state_dir


def _patch_semgrep_background_tasks(monkeypatch):
    async def _noop_single(*args, **kwargs):
        del args, kwargs

    async def _noop_bulk(*args, **kwargs):
        del args, kwargs

    monkeypatch.setattr("server.routers.semgrep_service.run_plugin_semgrep_scan", _noop_single)
    monkeypatch.setattr("server.routers.semgrep_service.run_bulk_semgrep_task", _noop_bulk)


def test_semgrep_scan_endpoints_work(monkeypatch, tmp_path):
    from server.routers import semgrep

    repo = _DummyRepo()
    monkeypatch.setattr(semgrep, "repo", repo)
    _patch_semgrep_background_tasks(monkeypatch)

    client = _create_client(monkeypatch, tmp_path)

    start_response = client.post(
        "/api/semgrep/scan",
        json={
            "slug": "akismet",
            "download_url": "https://downloads.wordpress.org/plugin/akismet.5.3.1.zip",
        },
    )
    assert start_response.status_code == 200
    assert start_response.json()["success"] is True

    get_response = client.get("/api/semgrep/scan/akismet")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "completed"


def test_semgrep_rules_and_rulesets_endpoints(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    client = _create_client(monkeypatch, tmp_path)

    rules_response = client.get("/api/semgrep/rules")
    assert rules_response.status_code == 200
    assert "rulesets" in rules_response.json()

    create_rule_response = client.post(
        "/api/semgrep/rules",
        json={
            "id": "custom_eval_rule",
            "pattern": "eval($X)",
            "message": "Avoid eval",
            "severity": "WARNING",
            "languages": ["php"],
        },
    )
    assert create_rule_response.status_code == 200
    assert create_rule_response.json()["success"] is True
    assert (state_dir / "custom_rules.yaml").exists()

    toggle_rule_response = client.post("/api/semgrep/rules/custom_eval_rule/toggle")
    assert toggle_rule_response.status_code == 200
    assert toggle_rule_response.json()["rule_id"] == "custom_eval_rule"
    disabled_state = json.loads((state_dir / "disabled_config.json").read_text())
    assert disabled_state["rules"] == ["custom_eval_rule"]

    toggle_all_new = client.post("/api/semgrep/rules/actions/toggle-all", json={"enabled": True})
    assert toggle_all_new.status_code == 200
    assert toggle_all_new.json()["success"] is True

    toggle_all_legacy = client.post("/api/semgrep/rules/toggle-all", json={"enabled": False})
    assert toggle_all_legacy.status_code == 405

    create_ruleset_response = client.post("/api/semgrep/rulesets", json={"ruleset": "r/custom-demo"})
    assert create_ruleset_response.status_code == 200
    assert create_ruleset_response.json()["ruleset_id"] == "r/custom-demo"

    toggle_ruleset_response = client.post("/api/semgrep/rulesets/r/custom-demo/toggle")
    assert toggle_ruleset_response.status_code == 200
    assert toggle_ruleset_response.json()["ruleset_id"] == "r/custom-demo"

    delete_ruleset_response = client.delete("/api/semgrep/rulesets/r/custom-demo")
    assert delete_ruleset_response.status_code == 200
    assert delete_ruleset_response.json()["deleted"] == "r/custom-demo"

    delete_rule_response = client.delete("/api/semgrep/rules/custom_eval_rule")
    assert delete_rule_response.status_code == 200
    assert delete_rule_response.json()["deleted"] == "custom_eval_rule"
    assert get_disabled_config()["rules"] == []
    assert "custom_eval_rule" not in [
        rule.get("id") for rule in semgrep_helpers.load_custom_rules_document().get("rules", [])
    ]


def test_semgrep_bulk_endpoints(monkeypatch, tmp_path):
    from server.routers import semgrep
    from server.routers import semgrep_tasks

    repo = _DummyRepo()
    monkeypatch.setattr(semgrep, "repo", repo)
    _patch_semgrep_background_tasks(monkeypatch)
    semgrep_tasks.active_bulk_scans.clear()

    client = _create_client(monkeypatch, tmp_path)

    start_bulk_response = client.post("/api/semgrep/bulk/10")
    assert start_bulk_response.status_code == 200
    assert start_bulk_response.json()["status"] == "started"
    assert start_bulk_response.json()["count"] == 2

    stats_response = client.get("/api/semgrep/bulk/10/stats")
    assert stats_response.status_code == 200
    stats = stats_response.json()
    assert stats["session_id"] == 10
    assert stats["total_plugins"] == 2
    assert stats["scanned_count"] == 1

    stop_bulk_response = client.post("/api/semgrep/bulk/10/stop")
    assert stop_bulk_response.status_code == 200
    assert stop_bulk_response.json()["status"] == "stopping"


def test_semgrep_scan_rejects_invalid_slug(monkeypatch, tmp_path):
    from server.routers import semgrep

    repo = _DummyRepo()
    monkeypatch.setattr(semgrep, "repo", repo)

    client = _create_client(monkeypatch, tmp_path)
    response = client.post(
        "/api/semgrep/scan",
        json={
            "slug": "..bad-slug",
            "download_url": "https://downloads.wordpress.org/plugin/akismet.5.3.1.zip",
        },
    )

    assert response.status_code == 422



def test_semgrep_helpers_reads_fallback_when_state_dir_is_unwritable(monkeypatch, tmp_path):
    blocked_state_dir = tmp_path / "blocked-home" / ".temodar-agent" / "semgrep"
    legacy_disabled_config = tmp_path / "legacy-disabled.json"
    legacy_disabled_config.write_text(json.dumps({"rules": ["rule-a"], "rulesets": [], "extra_rulesets": []}))

    original_mkdir = Path.mkdir

    def fail_mkdir(self, *args, **kwargs):
        if self == blocked_state_dir:
            raise PermissionError("blocked")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(semgrep_helpers, "SEMGREP_STATE_DIR", blocked_state_dir)
    monkeypatch.setattr(semgrep_helpers, "CUSTOM_RULES_PATH", blocked_state_dir / "custom_rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "DISABLED_CONFIG_PATH", blocked_state_dir / "disabled_config.json")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_DISABLED_CONFIG_PATH", legacy_disabled_config)
    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    assert get_disabled_config() == {"rules": [], "rulesets": [], "extra_rulesets": []}



def test_semgrep_helpers_write_raises_when_state_dir_is_unwritable(monkeypatch, tmp_path):
    blocked_state_dir = tmp_path / "blocked-home" / ".temodar-agent" / "semgrep"
    original_mkdir = Path.mkdir

    def fail_mkdir(self, *args, **kwargs):
        if self == blocked_state_dir:
            raise PermissionError("blocked")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(semgrep_helpers, "SEMGREP_STATE_DIR", blocked_state_dir)
    monkeypatch.setattr(semgrep_helpers, "CUSTOM_RULES_PATH", blocked_state_dir / "custom_rules.yaml")
    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    try:
        save_custom_rules_document({"rules": []})
        assert False, "Expected PermissionError"
    except PermissionError as exc:
        assert "not writable" in str(exc)



def test_semgrep_helpers_bootstrap_is_noop_when_state_dir_is_unwritable(monkeypatch, tmp_path):
    blocked_state_dir = tmp_path / "blocked-home" / ".temodar-agent" / "semgrep"
    original_mkdir = Path.mkdir

    def fail_mkdir(self, *args, **kwargs):
        if self == blocked_state_dir:
            raise PermissionError("blocked")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(semgrep_helpers, "SEMGREP_STATE_DIR", blocked_state_dir)
    monkeypatch.setattr(semgrep_helpers, "CUSTOM_RULES_PATH", blocked_state_dir / "custom_rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "DISABLED_CONFIG_PATH", blocked_state_dir / "disabled_config.json")
    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    semgrep_helpers.bootstrap_default_custom_rules()

    assert not (blocked_state_dir / "custom_rules.yaml").exists()
    assert not (blocked_state_dir / "disabled_config.json").exists()



def test_semgrep_helpers_write_succeeds_when_state_dir_is_writable(monkeypatch, tmp_path):
    writable_state_dir = tmp_path / "writable-home" / ".temodar-agent" / "semgrep"
    monkeypatch.setattr(semgrep_helpers, "SEMGREP_STATE_DIR", writable_state_dir)
    monkeypatch.setattr(semgrep_helpers, "CUSTOM_RULES_PATH", writable_state_dir / "custom_rules.yaml")

    save_custom_rules_document({"rules": [{"id": "demo-rule"}]})

    assert (writable_state_dir / "custom_rules.yaml").exists()
    assert semgrep_helpers.load_custom_rules_document()["rules"] == [{"id": "demo-rule"}]


def test_semgrep_rules_endpoint_bootstraps_legacy_custom_rules_into_canonical_state(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    legacy_rules_path = tmp_path / "legacy-semgrep-results" / "custom_rules.yaml"
    legacy_rules_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rules_path.write_text(
        "rules:\n  - id: migrated-rule\n    message: Migrated\n    severity: WARNING\n    pattern: eval($X)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", legacy_rules_path)
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")

    client = _create_client(monkeypatch, tmp_path)
    response = client.get("/api/semgrep/rules")

    assert response.status_code == 200
    body = response.json()
    assert [rule["id"] for rule in body["custom_rules"]] == ["migrated-rule"]
    assert (state_dir / "custom_rules.yaml").exists()
    assert "migrated-rule" in (state_dir / "custom_rules.yaml").read_text(encoding="utf-8")


def test_semgrep_helpers_bootstrap_migrates_disabled_config_without_overwriting_existing_rules(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    canonical_rules = state_dir / "custom_rules.yaml"
    canonical_rules.parent.mkdir(parents=True, exist_ok=True)
    canonical_rules.write_text(
        "rules:\n  - id: canonical-rule\n    message: Canonical\n    severity: WARNING\n    pattern: exec($X)\n",
        encoding="utf-8",
    )
    legacy_disabled_path = tmp_path / "legacy-disabled.json"
    legacy_disabled_path.write_text(json.dumps({"rules": ["canonical-rule"], "rulesets": [], "extra_rulesets": []}), encoding="utf-8")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_DISABLED_CONFIG_PATH", legacy_disabled_path)

    semgrep_helpers.bootstrap_default_custom_rules()

    assert semgrep_helpers.load_custom_rules_document()["rules"][0]["id"] == "canonical-rule"
    assert json.loads((state_dir / "disabled_config.json").read_text(encoding="utf-8"))["rules"] == ["canonical-rule"]


def test_semgrep_helpers_load_custom_rules_document_bootstraps_legacy_rules(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    legacy_rules_path = tmp_path / "legacy-semgrep-results" / "custom_rules.yaml"
    legacy_rules_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rules_path.write_text(
        "rules:\n  - id: legacy-doc-rule\n    message: Legacy\n    severity: WARNING\n    pattern: eval($X)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", legacy_rules_path)
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")

    doc = semgrep_helpers.load_custom_rules_document()

    assert doc["rules"][0]["id"] == "legacy-doc-rule"
    assert (state_dir / "custom_rules.yaml").exists()


def test_semgrep_helpers_load_custom_rules_bootstraps_legacy_rules(monkeypatch, tmp_path):
    _patch_semgrep_state(monkeypatch, tmp_path)
    legacy_rules_path = tmp_path / "legacy-semgrep-results" / "custom_rules.yaml"
    legacy_rules_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rules_path.write_text(
        "rules:\n  - id: legacy-list-rule\n    message: Legacy\n    severity: WARNING\n    pattern: eval($X)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", legacy_rules_path)
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")

    rules = semgrep_helpers.load_custom_rules()

    assert [rule["id"] for rule in rules] == ["legacy-list-rule"]


def test_semgrep_helpers_bootstrap_is_idempotent_when_canonical_rules_exist(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    canonical_rules = state_dir / "custom_rules.yaml"
    canonical_rules.parent.mkdir(parents=True, exist_ok=True)
    canonical_rules.write_text(
        "rules:\n  - id: keep-me\n    message: Canonical\n    severity: WARNING\n    pattern: exec($X)\n",
        encoding="utf-8",
    )
    legacy_rules_path = tmp_path / "legacy-semgrep-results" / "custom_rules.yaml"
    legacy_rules_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rules_path.write_text(
        "rules:\n  - id: old-rule\n    message: Old\n    severity: WARNING\n    pattern: eval($X)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", legacy_rules_path)
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")

    semgrep_helpers.bootstrap_default_custom_rules()

    text = canonical_rules.read_text(encoding="utf-8")
    assert "keep-me" in text
    assert "old-rule" not in text


def test_semgrep_rules_endpoint_returns_empty_custom_rules_when_no_legacy_or_canonical_rules_exist(monkeypatch, tmp_path):
    _patch_semgrep_state(monkeypatch, tmp_path)
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", tmp_path / "missing-legacy-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")

    client = _create_client(monkeypatch, tmp_path)
    response = client.get("/api/semgrep/rules")

    assert response.status_code == 200
    assert response.json()["custom_rules"] == []


def test_semgrep_helpers_bootstrap_copies_package_fallback_when_legacy_missing(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    package_rules_path = tmp_path / "package-semgrep-results" / "custom_rules.yaml"
    package_rules_path.parent.mkdir(parents=True, exist_ok=True)
    package_rules_path.write_text(
        "rules:\n  - id: package-rule\n    message: Package\n    severity: WARNING\n    pattern: eval($X)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", tmp_path / "missing-legacy-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", package_rules_path)

    semgrep_helpers.bootstrap_default_custom_rules()

    assert (state_dir / "custom_rules.yaml").exists()
    assert "package-rule" in (state_dir / "custom_rules.yaml").read_text(encoding="utf-8")


def test_semgrep_helpers_bootstrap_prefers_root_rules_before_legacy(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    root_rules_path = tmp_path / "root-custom-rules.yaml"
    root_rules_path.write_text(
        "rules:\n  - id: root-rule\n    message: Root\n    severity: WARNING\n    pattern: eval($X)\n",
        encoding="utf-8",
    )
    legacy_rules_path = tmp_path / "legacy-semgrep-results" / "custom_rules.yaml"
    legacy_rules_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rules_path.write_text(
        "rules:\n  - id: legacy-rule\n    message: Legacy\n    severity: WARNING\n    pattern: exec($X)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", root_rules_path)
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", legacy_rules_path)
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")

    semgrep_helpers.bootstrap_default_custom_rules()

    text = (state_dir / "custom_rules.yaml").read_text(encoding="utf-8")
    assert "root-rule" in text
    assert "legacy-rule" not in text


def test_semgrep_rules_endpoint_preserves_disabled_rule_state_after_bootstrap(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    legacy_rules_path = tmp_path / "legacy-semgrep-results" / "custom_rules.yaml"
    legacy_rules_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rules_path.write_text(
        "rules:\n  - id: disabled-after-bootstrap\n    message: Legacy\n    severity: WARNING\n    pattern: eval($X)\n",
        encoding="utf-8",
    )
    legacy_disabled_path = tmp_path / "legacy-disabled.json"
    legacy_disabled_path.write_text(json.dumps({"rules": ["disabled-after-bootstrap"], "rulesets": [], "extra_rulesets": []}), encoding="utf-8")
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", legacy_rules_path)
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_DISABLED_CONFIG_PATH", legacy_disabled_path)

    client = _create_client(monkeypatch, tmp_path)
    response = client.get("/api/semgrep/rules")

    assert response.status_code == 200
    custom_rule = response.json()["custom_rules"][0]
    assert custom_rule["id"] == "disabled-after-bootstrap"
    assert custom_rule["enabled"] is False
    assert json.loads((state_dir / "disabled_config.json").read_text(encoding="utf-8"))["rules"] == ["disabled-after-bootstrap"]


def test_semgrep_load_custom_rules_document_returns_empty_when_bootstrap_has_no_source(monkeypatch, tmp_path):
    _patch_semgrep_state(monkeypatch, tmp_path)
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", tmp_path / "missing-legacy.yaml")
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package.yaml")

    assert semgrep_helpers.load_custom_rules_document() == {"rules": []}


def test_semgrep_bootstrap_does_not_create_custom_rules_from_empty_legacy_yaml(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    legacy_rules_path = tmp_path / "legacy-semgrep-results" / "custom_rules.yaml"
    legacy_rules_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rules_path.write_text("rules: []\n", encoding="utf-8")
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", legacy_rules_path)
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")

    semgrep_helpers.bootstrap_default_custom_rules()

    assert not (state_dir / "custom_rules.yaml").exists()


def test_semgrep_bootstrap_ignores_missing_disabled_config_source(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    monkeypatch.setattr(semgrep_helpers, "LEGACY_DISABLED_CONFIG_PATH", tmp_path / "missing-disabled.json")

    semgrep_helpers.bootstrap_default_custom_rules()

    assert not (state_dir / "disabled_config.json").exists()


def test_semgrep_bootstrap_preserves_existing_disabled_config(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    disabled_path = state_dir / "disabled_config.json"
    disabled_path.parent.mkdir(parents=True, exist_ok=True)
    disabled_path.write_text(json.dumps({"rules": ["keep-disabled"], "rulesets": [], "extra_rulesets": []}), encoding="utf-8")
    legacy_disabled_path = tmp_path / "legacy-disabled.json"
    legacy_disabled_path.write_text(json.dumps({"rules": ["old-disabled"], "rulesets": [], "extra_rulesets": []}), encoding="utf-8")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_DISABLED_CONFIG_PATH", legacy_disabled_path)

    semgrep_helpers.bootstrap_default_custom_rules()

    assert json.loads(disabled_path.read_text(encoding="utf-8"))["rules"] == ["keep-disabled"]


def test_semgrep_rules_endpoint_bootstrap_runs_via_load_custom_rules_document(monkeypatch, tmp_path):
    state_dir = _patch_semgrep_state(monkeypatch, tmp_path)
    legacy_rules_path = tmp_path / "legacy-semgrep-results" / "custom_rules.yaml"
    legacy_rules_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rules_path.write_text(
        "rules:\n  - id: endpoint-bootstrap\n    message: Legacy\n    severity: WARNING\n    pattern: eval($X)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", legacy_rules_path)
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")

    client = _create_client(monkeypatch, tmp_path)
    client.get("/api/semgrep/rules")

    assert (state_dir / "custom_rules.yaml").exists()
    assert "endpoint-bootstrap" in (state_dir / "custom_rules.yaml").read_text(encoding="utf-8")


def test_semgrep_helpers_load_custom_rules_marks_custom_rules_true(monkeypatch, tmp_path):
    _patch_semgrep_state(monkeypatch, tmp_path)
    save_custom_rules_document({"rules": [{"id": "demo-rule", "message": "Demo", "severity": "WARNING", "pattern": "eval($X)"}]})

    rules = semgrep_helpers.load_custom_rules()

    assert rules[0]["is_custom"] is True


def test_semgrep_helpers_load_custom_rules_extracts_pattern_from_patterns_array(monkeypatch, tmp_path):
    _patch_semgrep_state(monkeypatch, tmp_path)
    save_custom_rules_document({"rules": [{"id": "demo-rule", "message": "Demo", "severity": "WARNING", "patterns": [{"pattern": "eval($X)"}]}]})

    rules = semgrep_helpers.load_custom_rules()

    assert rules[0]["pattern"] == "eval($X)"


def test_semgrep_rules_endpoint_returns_bootstrapped_rule_enabled_by_default(monkeypatch, tmp_path):
    _patch_semgrep_state(monkeypatch, tmp_path)
    legacy_rules_path = tmp_path / "legacy-semgrep-results" / "custom_rules.yaml"
    legacy_rules_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_rules_path.write_text(
        "rules:\n  - id: bootstrapped-enabled\n    message: Legacy\n    severity: WARNING\n    pattern: eval($X)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(semgrep_helpers, "ROOT_CUSTOM_RULES_PATH", tmp_path / "missing-root-custom-rules.yaml")
    monkeypatch.setattr(semgrep_helpers, "LEGACY_CUSTOM_RULES_PATH", legacy_rules_path)
    monkeypatch.setattr(semgrep_helpers, "PACKAGE_CUSTOM_RULES_PATH", tmp_path / "missing-package-custom-rules.yaml")

    client = _create_client(monkeypatch, tmp_path)
    response = client.get("/api/semgrep/rules")

    assert response.json()["custom_rules"][0]["enabled"] is True
