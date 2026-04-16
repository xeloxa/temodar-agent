from pathlib import Path

import pytest

from database.models import _resolve_db_path
from runtime_paths import resolve_runtime_paths
from server.update_manager import UpdateManager


ROOT = Path(__file__).resolve().parents[1]


class _TestUpdateManager(UpdateManager):
    def __init__(self, state_dir: Path):
        self._test_state_dir = state_dir
        super().__init__()


def test_status_reads_runtime_metadata_from_env(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_BUILD", "build-123")
    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": None, "update_available": False}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["current_version"] == "0.1.3"
    assert status["current_tag"] == "v0.1.3"
    assert status["build_id"] == "build-123"
    assert status["runtime_status"] == "ready"
    assert status["status"] == "up_to_date"


def test_status_returns_up_to_date_without_helper_command(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")
    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.1.3", "update_available": False}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["status"] == "up_to_date"
    assert status["update_available"] is False
    assert status["update_command"] is None
    assert status["manual_update_required"] is False



def test_resolve_db_path_raises_when_default_runtime_root_is_unwritable(monkeypatch, tmp_path):
    blocked_db_path = tmp_path / "blocked-home" / ".temodar-agent" / "temodar_agent.db"
    monkeypatch.delenv("TEMODAR_AGENT_DB", raising=False)
    monkeypatch.setattr("database.models.DEFAULT_DB_PATH", blocked_db_path)
    monkeypatch.setattr("database.models._is_directory_writable", lambda path: path != blocked_db_path.parent)

    with pytest.raises(PermissionError, match=str(blocked_db_path.parent)):
        _resolve_db_path(None)



def test_runtime_paths_define_canonical_durable_root_and_children():
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



def test_resolve_db_path_raises_for_explicit_unwritable_path(monkeypatch, tmp_path):
    explicit_db_path = tmp_path / "blocked" / "temodar_agent.db"
    monkeypatch.setattr("database.models._is_directory_writable", lambda path: False)

    try:
        _resolve_db_path(explicit_db_path)
        assert False, "Expected PermissionError"
    except PermissionError as exc:
        assert str(explicit_db_path.parent) in str(exc)






def test_resolve_db_path_keeps_explicit_env_path_when_set(monkeypatch, tmp_path):
    explicit_db_path = tmp_path / "state" / "temodar_agent.db"
    monkeypatch.setenv("TEMODAR_AGENT_DB", str(explicit_db_path))

    resolved = _resolve_db_path(None)

    assert resolved == explicit_db_path
    assert explicit_db_path.parent.exists()


def test_status_returns_helper_command_when_new_release_exists(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")
    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {
            "tag_name": "v0.2.0",
            "name": "v0.2.0",
            "body": "Bug fixes",
            "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0",
            "published_at": "2026-04-16T00:00:00Z",
            "update_available": True,
        }

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["status"] == "update_available"
    assert status["update_available"] is True
    assert status["manual_update_required"] is True
    assert "docker pull xeloxa/temodar-agent:latest" in status["update_command"]
    assert "-v temodar-agent-data:/home/appuser/.temodar-agent" in status["update_command"]
    assert "temodar-agent-plugins" not in status["update_command"]
    assert "temodar-agent-semgrep" not in status["update_command"]
    assert "/app/Plugins" not in status["update_command"]
    assert "/app/semgrep_results" not in status["update_command"]


def test_status_degrades_when_release_lookup_fails(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")
    monkeypatch.setattr(manager, "_fetch_release", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))

    status = manager.get_status(force=True)

    assert status["status"] == "degraded"
    assert status["update_available"] is False
    assert status["update_command"] is None
    assert status["last_error"] == "RuntimeError: boom"
    assert "temporarily unavailable" in status["message"]


def test_status_degrades_when_runtime_metadata_malformed(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.delenv("TEMODAR_AGENT_IMAGE_TAG", raising=False)
    monkeypatch.delenv("TEMODAR_AGENT_IMAGE_BUILD", raising=False)
    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": None, "update_available": False}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["current_version"] == "unknown"
    assert status["current_tag"] == "unknown"
    assert status["runtime_status"] == "degraded"
    assert status["status"] == "degraded"
    assert "Runtime version metadata is incomplete" in status["message"]


def test_get_status_does_not_write_host_update_request_file(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")
    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.0", "update_available": True}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status(force=True)

    assert status["update_available"] is True
    assert not (tmp_path / ".temodar-agent" / "update_state.json").exists()


def test_manual_update_payload_is_notify_only(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")
    def get_status(*args, **kwargs):
        del args, kwargs
        return {
            "status": "update_available",
            "current_version": "0.1.3",
            "current_tag": "v0.1.3",
            "latest_version": "v0.2.0",
            "update_available": True,
            "update_command": "docker pull xeloxa/temodar-agent:latest",
            "manual_update_required": True,
        }

    monkeypatch.setattr(manager, "get_status", get_status)

    payload = manager.get_manual_update_payload()

    assert payload == {
        "status": "update_available",
        "message": "Automatic updates are no longer supported. Pull the latest image and rerun the container manually.",
        "current_version": "0.1.3",
        "current_tag": "v0.1.3",
        "latest_version": "v0.2.0",
        "update_available": True,
        "update_command": "docker pull xeloxa/temodar-agent:latest",
        "manual_update_required": True,
        "manual_update_only": True,
        "deprecated": True,
    }


def test_manual_update_payload_is_deprecated_even_when_release_lookup_degraded(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    def get_status(*args, **kwargs):
        del args, kwargs
        return {
            "status": "degraded",
            "current_version": "0.1.3",
            "current_tag": "v0.1.3",
            "latest_version": None,
            "update_available": False,
            "update_command": None,
            "manual_update_required": False,
        }

    monkeypatch.setattr(manager, "get_status", get_status)

    payload = manager.get_manual_update_payload()

    assert payload["status"] == "degraded"
    assert payload["deprecated"] is True
    assert payload["manual_update_only"] is True
    assert payload["update_command"] is None
    assert payload["latest_version"] is None
    assert payload["current_tag"] == "v0.1.3"


def test_legacy_host_update_scripts_are_removed_from_supported_runtime_path():
    assert not (ROOT / "run.sh").exists()
    assert not (ROOT / "infrastructure" / "host_update_watcher.sh").exists()
    assert not (ROOT / "infrastructure" / "update_docker_install.sh").exists()


def test_readme_uses_image_first_install_flow_without_legacy_scripts():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docker pull xeloxa/temodar-agent:latest" in readme
    assert "docker run -d --name temodar-agent -p 8080:8080" in readme
    assert "-v temodar-agent-data:/home/appuser/.temodar-agent" in readme
    assert "This is a hard cutover to the canonical runtime root." in readme
    assert "only `temodar-agent-data` mounted at `/home/appuser/.temodar-agent`" in readme
    assert "three named Docker volumes" not in readme
    assert "-v temodar-agent-plugins:/app/Plugins" not in readme
    assert "-v temodar-agent-semgrep:/app/semgrep_results" not in readme
    assert "./run.sh" not in readme
    assert "host-side update watcher" not in readme
    assert "rebuild and restart everything" not in readme
    assert "git clone https://github.com/xeloxa/temodar-agent.git" not in readme


def test_manual_update_command_does_not_reference_legacy_scripts(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    command = manager._build_manual_update_command()

    assert command.count("-v ") == 1
    assert "docker pull xeloxa/temodar-agent:latest" in command
    assert "-v temodar-agent-data:/home/appuser/.temodar-agent" in command
    assert "temodar-agent-plugins" not in command
    assert "temodar-agent-semgrep" not in command
    assert "/app/Plugins" not in command
    assert "/app/semgrep_results" not in command
    assert "run.sh" not in command
    assert "update_docker_install.sh" not in command
    assert "host_update_watcher.sh" not in command
    assert "docker build" not in command
    assert "git pull" not in command
    assert "update_state.json" not in command
    assert "update-runtime.json" not in command


def test_runtime_metadata_falls_back_without_wrapper_runtime_file(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.delenv("TEMODAR_AGENT_IMAGE_VERSION", raising=False)
    monkeypatch.delenv("TEMODAR_AGENT_IMAGE_TAG", raising=False)
    monkeypatch.delenv("TEMODAR_AGENT_IMAGE_BUILD", raising=False)
    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": None, "update_available": False}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["current_version"] == "0.2.0"
    assert status["current_tag"] == "0.2.0"
    assert status["runtime_status"] == "fallback"
    assert status["status"] == "up_to_date"
    assert not (tmp_path / ".temodar-agent" / "update-runtime.json").exists()


def test_status_uses_runtime_version_for_release_comparison(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.2")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.2")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {
            "tag_name": "v0.1.3",
            "name": "v0.1.3",
            "body": "Bug fixes",
            "html_url": "https://github.com/xeloxa/temodar-agent/releases/tag/v0.1.3",
            "published_at": "2026-04-16T00:00:00Z",
        }

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["current_version"] == "0.1.2"
    assert status["current_tag"] == "v0.1.2"
    assert status["latest_version"] == "v0.1.3"
    assert status["release_url"] == "https://github.com/xeloxa/temodar-agent/tree/v0.1.3"
    assert status["update_available"] is True
    assert status["status"] == "update_available"


def test_release_payload_rejects_unsupported_html_host(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    with pytest.raises(ValueError, match="Unsupported release URL host"):
        manager._release_metadata.build_release_payload(
            {
                "tag_name": "v0.1.3",
                "name": "v0.1.3",
                "body": "Bug fixes",
                "html_url": "https://example.com/releases/v0.1.3",
                "published_at": "2026-04-16T00:00:00Z",
            }
        )


def test_release_payload_rejects_unsupported_api_host(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    manager._release_metadata.release_api_url = "https://example.com/tags"

    with pytest.raises(ValueError, match="Unsupported release API host"):
        manager._release_metadata.fetch_release()


def test_tag_picker_chooses_highest_semver_tag(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag(
        [
            {"name": "v0.1.9"},
            {"name": "v0.2.0"},
            {"name": "main"},
            {"name": "v0.10.0"},
        ]
    )

    assert picked == "v0.10.0"


def test_tag_picker_ignores_non_semver_tags(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag(
        [
            {"name": "latest"},
            {"name": "main"},
            {"name": "release-candidate"},
        ]
    )

    assert picked is None


def test_fetch_release_builds_tag_payload_from_tags_api(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": "main"}, {"name": "v0.2.0"}, {"name": "v0.1.3"}]

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())

    payload = manager._release_metadata.fetch_release()

    assert payload == {
        "tag_name": "v0.2.0",
        "name": "v0.2.0",
        "body": "",
        "published_at": None,
        "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0",
    }


def test_fetch_release_returns_empty_payload_when_no_semver_tags_exist(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": "main"}, {"name": "latest"}]

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())

    payload = manager._release_metadata.fetch_release()

    assert payload == manager._release_metadata.empty_release_payload()


def test_tag_url_uses_stable_github_tree_page(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    assert manager._release_metadata.tag_url("v0.2.0") == "https://github.com/xeloxa/temodar-agent/tree/v0.2.0"
    assert manager._release_metadata.tag_url("release/test") == "https://github.com/xeloxa/temodar-agent/tree/release/test"


def test_update_manager_uses_tags_api_endpoint(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    assert manager.RELEASE_API_URL.endswith("/tags")
    assert manager._release_metadata.release_api_url.endswith("/tags")


def test_up_to_date_status_uses_tag_tree_url(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {
            "tag_name": "v0.1.3",
            "name": "v0.1.3",
            "body": "",
            "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.1.3",
            "published_at": None,
            "update_available": False,
        }

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["release_url"] == "https://github.com/xeloxa/temodar-agent/tree/v0.1.3"
    assert status["release_notes"] == ""
    assert status["release_published_at"] is None
    assert status["status"] == "up_to_date"


def test_update_available_status_uses_tag_tree_url(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.2")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.2")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {
            "tag_name": "v0.1.3",
            "name": "v0.1.3",
            "body": "",
            "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.1.3",
            "published_at": None,
        }

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["release_url"] == "https://github.com/xeloxa/temodar-agent/tree/v0.1.3"
    assert status["update_available"] is True
    assert status["status"] == "update_available"


def test_degraded_status_keeps_stable_keys_when_tag_lookup_fails(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")
    monkeypatch.setattr(manager, "_fetch_release", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))

    status = manager.get_status(force=True)

    assert status["status"] == "degraded"
    assert status["latest_version"] is None
    assert status["release_name"] is None
    assert status["release_notes"] == ""
    assert status["release_url"] is None
    assert status["release_published_at"] is None
    assert status["last_error"] == "RuntimeError: boom"


def test_release_metadata_service_reuses_release_headers_for_tags(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    assert manager._release_metadata.tag_headers() == manager._release_metadata.release_headers()


def test_status_prefers_current_tag_for_comparison_when_present(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.2")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.2")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.0", "name": "v0.2.0", "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["latest_version"] == "v0.2.0"
    assert status["update_available"] is True


def test_status_uses_runtime_version_when_current_tag_unknown(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.2")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "unknown")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.0", "name": "v0.2.0", "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["update_available"] is True
    assert status["latest_version"] == "v0.2.0"


def test_status_handles_empty_tag_payload_as_up_to_date(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return manager._release_metadata.empty_release_payload()

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["latest_version"] is None
    assert status["update_available"] is False
    assert status["status"] == "up_to_date"


def test_release_payload_accepts_stable_tag_tree_url(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    payload = manager._release_metadata.build_release_payload(
        {
            "tag_name": "v0.1.3",
            "name": "v0.1.3",
            "body": "",
            "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.1.3",
            "published_at": None,
        }
    )

    assert payload["html_url"] == "https://github.com/xeloxa/temodar-agent/tree/v0.1.3"


def test_pick_latest_tag_handles_longer_version_tuples(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag(
        [{"name": "v0.2"}, {"name": "v0.2.1"}, {"name": "v0.2.0"}]
    )

    assert picked == "v0.2.1"


def test_tag_picker_allows_uppercase_v_prefix(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag([{"name": "V0.2.0"}, {"name": "v0.1.0"}])

    assert picked == "V0.2.0"


def test_tag_picker_rejects_prerelease_style_tags(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag([{"name": "v0.2.0-rc1"}, {"name": "v0.1.9"}])

    assert picked == "v0.1.9"


def test_tag_url_rejects_unsupported_host_via_release_payload(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    with pytest.raises(ValueError, match="Unsupported release URL host"):
        manager._release_metadata.build_release_payload(
            {
                "tag_name": "v0.2.0",
                "name": "v0.2.0",
                "body": "",
                "html_url": "https://example.com/tree/v0.2.0",
                "published_at": None,
            }
        )


def test_fetch_release_rejects_non_list_tags_response(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"unexpected": True}

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())

    with pytest.raises(ValueError, match="Unexpected tags API response shape"):
        manager._release_metadata.fetch_release()


def test_fetch_release_calls_github_tags_endpoint(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    seen = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": "v0.2.0"}]

    def fake_get(url, headers, timeout):
        seen["url"] = url
        seen["headers"] = headers
        seen["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("server.update_manager.requests.get", fake_get)

    manager._release_metadata.fetch_release()

    assert seen["url"].endswith("/tags")
    assert seen["headers"]["User-Agent"] == "Temodar Agent Update Agent"
    assert seen["timeout"] == 15


def test_fetch_release_handles_slash_in_tag_name_for_url_encoding(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    assert manager._release_metadata.tag_url("release/test") == "https://github.com/xeloxa/temodar-agent/tree/release/test"


def test_status_preserves_manual_update_message_under_tag_model(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.0", "name": "v0.2.0", "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["manual_update_required"] is True
    assert status["manual_update_message"] == manager.MESSAGE_MANUAL_UPDATE_ONLY


def test_status_uses_empty_string_release_notes_when_tag_metadata_has_none(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.1.3", "name": "v0.1.3", "body": None, "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.1.3", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["release_notes"] == ""


def test_status_uses_tag_name_when_release_name_missing(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.0", "name": None, "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["release_name"] == "v0.2.0"


def test_status_handles_tag_payload_without_url(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.0", "name": "v0.2.0", "body": "", "html_url": None, "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["release_url"] is None


def test_status_handles_tag_payload_without_tag_name(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": None, "name": None, "body": "", "html_url": None, "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["latest_version"] is None
    assert status["update_available"] is False
    assert status["status"] == "up_to_date"


def test_status_uses_tree_url_in_helper_payload(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    def get_status(*args, **kwargs):
        del args, kwargs
        return {
            "status": "update_available",
            "current_version": "0.1.3",
            "current_tag": "v0.1.3",
            "latest_version": "v0.2.0",
            "release_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0",
            "update_available": True,
            "update_command": "docker pull xeloxa/temodar-agent:latest",
            "manual_update_required": True,
        }

    monkeypatch.setattr(manager, "get_status", get_status)

    payload = manager.get_manual_update_payload()

    assert payload["latest_version"] == "v0.2.0"
    assert payload["update_command"] == "docker pull xeloxa/temodar-agent:latest"


def test_release_payload_normalizes_empty_body_to_empty_string(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    payload = manager._release_metadata.build_release_payload(
        {"tag_name": "v0.2.0", "name": "v0.2.0", "body": None, "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0", "published_at": None}
    )

    assert payload["body"] == ""


def test_release_payload_uses_tag_name_when_name_missing(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    payload = manager._release_metadata.build_release_payload(
        {"tag_name": "v0.2.0", "name": None, "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0", "published_at": None}
    )

    assert payload["name"] == "v0.2.0"


def test_fetch_release_returns_empty_payload_for_empty_list(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())

    payload = manager._release_metadata.fetch_release()

    assert payload == manager._release_metadata.empty_release_payload()


def test_normalized_version_compares_tag_values_consistently(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    assert manager._release_metadata.normalized_version("v0.2.0") > manager._release_metadata.normalized_version("v0.1.9")


def test_tag_picker_ignores_blank_names(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag([{"name": ""}, {"name": "v0.1.0"}])

    assert picked == "v0.1.0"


def test_release_payload_rejects_unsupported_tag_tree_host(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    with pytest.raises(ValueError, match="Unsupported release URL host"):
        manager._release_metadata.build_release_payload(
            {"tag_name": "v0.1.3", "name": "v0.1.3", "body": "", "html_url": "https://bad.example/tree/v0.1.3", "published_at": None}
        )


def test_fetch_release_preserves_selected_tag_as_release_name(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": "v0.2.0"}]

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())

    payload = manager._release_metadata.fetch_release()

    assert payload["name"] == "v0.2.0"


def test_fetch_release_sets_no_published_timestamp_for_tags(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": "v0.2.0"}]

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())

    payload = manager._release_metadata.fetch_release()

    assert payload["published_at"] is None


def test_fetch_release_sets_empty_body_for_tags(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": "v0.2.0"}]

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())

    payload = manager._release_metadata.fetch_release()

    assert payload["body"] == ""


def test_tag_picker_prefers_higher_semver_over_lexical_order(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag([{"name": "v0.9.0"}, {"name": "v0.10.0"}])

    assert picked == "v0.10.0"


def test_status_update_available_message_stays_manual_docker_focused(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.0", "name": "v0.2.0", "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert "Pull the latest image" in status["message"] or status["status"] == "update_available"


def test_status_up_to_date_message_remains_defined(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.1.3", "name": "v0.1.3", "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.1.3", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["message"] == manager.MESSAGE_UP_TO_DATE


def test_tag_picker_handles_patchless_versions(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag([{"name": "v1.2"}, {"name": "v1.2.1"}])

    assert picked == "v1.2.1"


def test_status_returns_stable_release_fields_when_up_to_date(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.2.0")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.2.0")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.0", "name": "v0.2.0", "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["release_name"] == "v0.2.0"
    assert status["release_url"] == "https://github.com/xeloxa/temodar-agent/tree/v0.2.0"
    assert status["release_notes"] == ""
    assert status["release_published_at"] is None


def test_status_current_tag_unknown_uses_current_version_string(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.2.0")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "unknown")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.1", "name": "v0.2.1", "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.1", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["update_available"] is True


def test_pick_latest_tag_returns_none_for_empty_input(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    assert manager._release_metadata._pick_latest_tag([]) is None


def test_fetch_release_uses_pick_latest_tag_result(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": "v0.1.0"}, {"name": "v0.2.0"}]

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())
    monkeypatch.setattr(manager._release_metadata, "_pick_latest_tag", lambda tags: "v0.2.0")

    payload = manager._release_metadata.fetch_release()

    assert payload["tag_name"] == "v0.2.0"


def test_release_payload_accepts_empty_html_url(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    payload = manager._release_metadata.build_release_payload(
        {"tag_name": "v0.2.0", "name": "v0.2.0", "body": "", "html_url": None, "published_at": None}
    )

    assert payload["html_url"] is None


def test_tag_picker_handles_extra_numeric_segments(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag([{"name": "v1.2.3.4"}, {"name": "v1.2.3"}])

    assert picked == "v1.2.3.4"


def test_update_available_status_exposes_tag_name_as_release_name(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.0")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.0")

    def resolve_release(*args, **kwargs):
        del args, kwargs
        return {"tag_name": "v0.2.0", "name": "v0.2.0", "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.2.0", "published_at": None}

    monkeypatch.setattr(manager, "_resolve_release_for_status", resolve_release)

    status = manager.get_status()

    assert status["release_name"] == "v0.2.0"


def test_manual_update_payload_still_deprecated_under_tag_model(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    def get_status(*args, **kwargs):
        del args, kwargs
        return {
            "status": "update_available",
            "current_version": "0.1.3",
            "current_tag": "v0.1.3",
            "latest_version": "v0.2.0",
            "update_available": True,
            "update_command": "docker pull xeloxa/temodar-agent:latest",
            "manual_update_required": True,
        }

    monkeypatch.setattr(manager, "get_status", get_status)

    payload = manager.get_manual_update_payload()

    assert payload["deprecated"] is True
    assert payload["manual_update_only"] is True


def test_fetch_release_ignores_non_matching_tag_case_when_needed(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": "release"}, {"name": "V0.2.0"}]

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())

    payload = manager._release_metadata.fetch_release()

    assert payload["tag_name"] == "V0.2.0"


def test_tag_picker_ignores_missing_name_entries(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    picked = manager._release_metadata._pick_latest_tag([{}, {"name": "v0.1.0"}])

    assert picked == "v0.1.0"


def test_fetch_release_returns_empty_payload_when_pick_latest_tag_returns_none(monkeypatch, tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"name": "main"}]

    monkeypatch.setattr("server.update_manager.requests.get", lambda *args, **kwargs: _FakeResponse())
    monkeypatch.setattr(manager._release_metadata, "_pick_latest_tag", lambda tags: None)

    payload = manager._release_metadata.fetch_release()

    assert payload == manager._release_metadata.empty_release_payload()


def test_release_payload_html_url_host_validation_allows_github(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    payload = manager._release_metadata.build_release_payload(
        {"tag_name": "v0.1.0", "name": "v0.1.0", "body": "", "html_url": "https://github.com/xeloxa/temodar-agent/tree/v0.1.0", "published_at": None}
    )

    assert payload["tag_name"] == "v0.1.0"
