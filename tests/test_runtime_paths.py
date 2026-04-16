from pathlib import Path

from ai.repository import AIRepository
from database.models import DEFAULT_DB_PATH, get_db_path
from database.repository import ScanRepository
from logger import get_log_file
from runtime_paths import CANONICAL_RUNTIME_ROOT, resolve_runtime_paths
from scanners.semgrep_scanner import DEFAULT_SEMGREP_OUTPUT_DIR
from server.routers import semgrep_helpers
from server.routers.semgrep_task_service import SEMGREP_OUTPUTS_DIR


def test_canonical_runtime_root_constant_matches_contract():
    assert CANONICAL_RUNTIME_ROOT == Path("/home/appuser/.temodar-agent")




def test_runtime_paths_define_canonical_root_and_children():
    paths = resolve_runtime_paths()

    assert paths.root == Path("/home/appuser/.temodar-agent")
    assert paths.db_file == paths.root / "temodar_agent.db"
    assert paths.logs_dir == paths.root / "logs"
    assert paths.plugins_dir == paths.root / "plugins"
    assert paths.semgrep_dir == paths.root / "semgrep"
    assert paths.semgrep_outputs_dir == paths.root / "semgrep-results"
    assert paths.approvals_dir == paths.root / "approvals"


def test_runtime_paths_are_stable_within_one_process():
    first = resolve_runtime_paths()
    second = resolve_runtime_paths()

    assert first is second
    assert first == second


def test_semgrep_helpers_and_scanner_use_runtime_paths():
    paths = resolve_runtime_paths()

    assert semgrep_helpers.SEMGREP_STATE_DIR == paths.semgrep_dir
    assert semgrep_helpers.SEM_RESULTS_DIR == paths.semgrep_outputs_dir
    assert semgrep_helpers.CUSTOM_RULES_PATH == paths.semgrep_dir / "custom_rules.yaml"
    assert semgrep_helpers.DISABLED_CONFIG_PATH == paths.semgrep_dir / "disabled_config.json"
    assert SEMGREP_OUTPUTS_DIR == paths.semgrep_outputs_dir
    assert DEFAULT_SEMGREP_OUTPUT_DIR == paths.semgrep_outputs_dir


def test_database_defaults_use_runtime_resolver(monkeypatch):
    monkeypatch.delenv("TEMODAR_AGENT_DB", raising=False)

    assert DEFAULT_DB_PATH == resolve_runtime_paths().db_file
    assert get_db_path() == resolve_runtime_paths().db_file


def test_logger_uses_runtime_resolver():
    assert get_log_file() == resolve_runtime_paths().logs_dir / "temodar_agent.log"


def test_scan_repository_accepts_explicit_runtime_resolver_path(tmp_path):
    runtime_db_path = tmp_path / "runtime-root" / "temodar_agent.db"
    repo = ScanRepository(db_path=runtime_db_path)

    assert repo.db_path == runtime_db_path
    assert runtime_db_path.exists()


def test_ai_repository_accepts_explicit_runtime_resolver_path(tmp_path):
    runtime_db_path = tmp_path / "runtime-root" / "temodar_agent.db"
    repository = AIRepository(db_path=runtime_db_path)

    assert repository.db_path == runtime_db_path
    assert runtime_db_path.exists()
