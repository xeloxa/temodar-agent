from pathlib import Path

import pytest

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
            "html_url": "https://github.com/xeloxa/temodar-agent/releases/tag/v0.2.0",
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
    assert "-v temodar-agent-plugins:/app/Plugins" in status["update_command"]
    assert "-v temodar-agent-semgrep:/app/semgrep_results" in status["update_command"]


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
    assert "-v temodar-agent-plugins:/app/Plugins" in readme
    assert "-v temodar-agent-semgrep:/app/semgrep_results" in readme
    assert "./run.sh" not in readme
    assert "host-side update watcher" not in readme
    assert "rebuild and restart everything" not in readme
    assert "git clone https://github.com/xeloxa/temodar-agent.git" not in readme


def test_manual_update_command_does_not_reference_legacy_scripts(tmp_path):
    manager = _TestUpdateManager(tmp_path / ".temodar-agent")

    command = manager._build_manual_update_command()

    assert "docker pull xeloxa/temodar-agent:latest" in command
    assert "-v temodar-agent-data:/home/appuser/.temodar-agent" in command
    assert "-v temodar-agent-plugins:/app/Plugins" in command
    assert "-v temodar-agent-semgrep:/app/semgrep_results" in command
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

    assert status["current_version"] == "0.1.3"
    assert status["current_tag"] == "0.1.3"
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
    manager._release_metadata.release_api_url = "https://example.com/releases/latest"

    with pytest.raises(ValueError, match="Unsupported release API host"):
        manager._release_metadata.fetch_release()
