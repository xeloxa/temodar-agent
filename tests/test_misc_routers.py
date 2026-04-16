from typing import Optional

from fastapi.testclient import TestClient

from server.app import create_app


UPDATE_COMMAND = (
    "docker pull xeloxa/temodar-agent:latest\n"
    "docker rm -f temodar-agent >/dev/null 2>&1 || true\n"
    "docker run -d --name temodar-agent -p 8080:8080 "
    "-v temodar-agent-data:/home/appuser/.temodar-agent "
    "-v temodar-agent-plugins:/app/Plugins "
    "-v temodar-agent-semgrep:/app/semgrep_results "
    "xeloxa/temodar-agent:latest"
)


class _DummyRepo:
    def __init__(self):
        self.calls = []

    def get_catalog_plugins(self, **kwargs):
        self.calls.append(("get_catalog_plugins", kwargs))
        return {"items": [{"slug": "akismet"}], "total": 1}

    def get_catalog_plugin_sessions(self, **kwargs):
        self.calls.append(("get_catalog_plugin_sessions", kwargs))
        return [{"session_id": 7, "score": 90}]

    def get_favorites(self):
        self.calls.append(("get_favorites", {}))
        return [{"slug": "akismet"}]

    def add_favorite(self, payload):
        self.calls.append(("add_favorite", payload))
        return True

    def remove_favorite(self, slug):
        self.calls.append(("remove_favorite", {"slug": slug}))
        return True


class _DummyUpdateManager:
    def __init__(self):
        self.status_calls = []
        self.manual_payload_calls = 0
        self.raise_status: Optional[Exception] = None
        self.raise_manual_payload: Optional[Exception] = None

    def get_status(self, force=False):
        self.status_calls.append(force)
        if self.raise_status:
            raise self.raise_status
        return {
            "current_version": "0.1.3",
            "current_tag": "v0.1.3",
            "latest_version": "v0.2.0" if force else "v0.1.3",
            "update_available": force,
            "status": "update_available" if force else "up_to_date",
            "update_command": UPDATE_COMMAND if force else None,
            "message": "A newer release is available." if force else "Temodar Agent is already running the latest available release.",
            "manual_update_required": force,
        }

    def get_manual_update_payload(self):
        self.manual_payload_calls += 1
        if self.raise_manual_payload:
            raise self.raise_manual_payload
        return {
            "status": "update_available",
            "message": "Automatic updates are no longer supported. Pull the latest image and rerun the container manually.",
            "current_version": "0.1.3",
            "current_tag": "v0.1.3",
            "latest_version": "v0.2.0",
            "update_available": True,
            "update_command": UPDATE_COMMAND,
            "manual_update_required": True,
            "manual_update_only": True,
            "deprecated": True,
        }


def _create_test_client(monkeypatch):
    manager = _DummyUpdateManager()
    monkeypatch.setattr("server.app.update_manager.manager", manager)
    monkeypatch.setattr("server.routers.system.update_manager.manager", manager)
    return TestClient(create_app(), base_url="http://localhost"), manager


def test_catalog_plugins_endpoint_forwards_query_params(monkeypatch):
    from server.routers import catalog

    repo = _DummyRepo()
    monkeypatch.setattr(catalog, "repo", repo)
    client, _ = _create_test_client(monkeypatch)

    response = client.get(
        "/api/catalog/plugins",
        params={"q": "seo", "sort_by": "score", "order": "asc", "limit": 25, "offset": 10},
    )

    assert response.status_code == 200
    assert response.json() == {"items": [{"slug": "akismet"}], "total": 1}
    assert repo.calls == [
        (
            "get_catalog_plugins",
            {"q": "seo", "sort_by": "score", "order": "asc", "limit": 25, "offset": 10},
        )
    ]



def test_catalog_plugin_sessions_endpoint_wraps_repo_response(monkeypatch):
    from server.routers import catalog

    repo = _DummyRepo()
    monkeypatch.setattr(catalog, "repo", repo)
    client, _ = _create_test_client(monkeypatch)

    response = client.get(
        "/api/catalog/plugins/akismet/sessions",
        params={"is_theme": "false", "limit": 5},
    )

    assert response.status_code == 200
    assert response.json() == {
        "slug": "akismet",
        "sessions": [{"session_id": 7, "score": 90}],
    }
    assert repo.calls == [
        (
            "get_catalog_plugin_sessions",
            {"slug": "akismet", "is_theme": False, "limit": 5},
        )
    ]



def test_system_update_endpoint_exposes_runtime_metadata(monkeypatch):
    manager = _DummyUpdateManager()
    monkeypatch.setattr("server.app.update_manager.manager", manager)
    monkeypatch.setattr("server.routers.system.update_manager.manager", manager)
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_VERSION", "0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_TAG", "v0.1.3")
    monkeypatch.setenv("TEMODAR_AGENT_IMAGE_BUILD", "build-123")
    client = TestClient(create_app(), base_url="http://localhost")

    response = client.get("/api/system/update")

    assert response.status_code == 200
    assert response.json() == {
        "current_version": "0.1.3",
        "current_tag": "v0.1.3",
        "latest_version": "v0.1.3",
        "update_available": False,
        "status": "up_to_date",
        "update_command": None,
        "message": "Temodar Agent is already running the latest available release.",
        "manual_update_required": False,
    }
    assert client.app.version == "0.1.3"
    assert manager.status_calls == [False, False]



def test_favorites_endpoints_delegate_to_repository(monkeypatch):
    from server.routers import favorites

    repo = _DummyRepo()
    monkeypatch.setattr(favorites, "repo", repo)
    client, _ = _create_test_client(monkeypatch)

    list_response = client.get("/api/favorites")
    add_response = client.post(
        "/api/favorites",
        json={
            "slug": "akismet",
            "name": "Akismet",
            "version": "1.0.0",
            "score": 80,
            "installations": 1000,
            "days_since_update": 5,
            "tested_wp_version": "6.8",
            "is_theme": False,
            "download_link": "https://downloads.wordpress.org/plugin/akismet.zip",
            "wp_org_link": "https://wordpress.org/plugins/akismet/",
            "cve_search_link": "https://cve.mitre.org/cgi-bin/cvekey.cgi?keyword=akismet",
            "wpscan_link": "https://wpscan.com/plugin/akismet",
            "trac_link": "https://plugins.trac.wordpress.org/browser/akismet/",
            "author_trusted": False,
            "is_risky_category": False,
            "is_user_facing": True,
            "risk_tags": ["public-input"],
            "security_flags": ["custom-ajax"],
            "feature_flags": ["settings-page"],
            "code_analysis": {"summary": "ok"},
        },
    )
    delete_response = client.delete("/api/favorites/akismet")

    assert list_response.status_code == 200
    assert list_response.json() == {"favorites": [{"slug": "akismet"}]}
    assert add_response.status_code == 200
    assert add_response.json() == {"success": True}
    assert delete_response.status_code == 200
    assert delete_response.json() == {"success": True}

    assert repo.calls[0] == ("get_favorites", {})
    assert repo.calls[1][0] == "add_favorite"
    assert repo.calls[1][1]["slug"] == "akismet"
    assert repo.calls[1][1]["code_analysis"] == {"summary": "ok"}
    assert repo.calls[2] == ("remove_favorite", {"slug": "akismet"})



def test_system_update_status_endpoint_returns_manager_payload(monkeypatch):
    client, manager = _create_test_client(monkeypatch)

    response = client.get("/api/system/update", params={"force": "true"})

    assert response.status_code == 200
    assert response.json() == {
        "current_version": "0.1.3",
        "current_tag": "v0.1.3",
        "latest_version": "v0.2.0",
        "update_available": True,
        "status": "update_available",
        "update_command": UPDATE_COMMAND,
        "message": "A newer release is available.",
        "manual_update_required": True,
    }
    assert manager.status_calls[-1] is True


def test_system_update_status_endpoint_returns_degraded_payload(monkeypatch):
    client, manager = _create_test_client(monkeypatch)

    def degraded_status(force=False):
        manager.status_calls.append(force)
        return {
            "current_version": "0.1.3",
            "current_tag": "v0.1.3",
            "latest_version": None,
            "update_available": False,
            "status": "degraded",
            "update_command": None,
            "message": "Release information is temporarily unavailable.",
            "manual_update_required": False,
        }

    manager.get_status = degraded_status

    response = client.get("/api/system/update")

    assert response.status_code == 200
    assert response.json() == {
        "current_version": "0.1.3",
        "current_tag": "v0.1.3",
        "latest_version": None,
        "update_available": False,
        "status": "degraded",
        "update_command": None,
        "message": "Release information is temporarily unavailable.",
        "manual_update_required": False,
    }
    assert manager.status_calls[-1] is False


def test_system_update_status_endpoint_payload_is_stable_across_states(monkeypatch):
    client, _ = _create_test_client(monkeypatch)

    up_to_date_response = client.get("/api/system/update")
    update_available_response = client.get("/api/system/update", params={"force": "true"})

    up_to_date_payload = up_to_date_response.json()
    update_available_payload = update_available_response.json()

    assert up_to_date_response.status_code == 200
    assert update_available_response.status_code == 200
    assert set(up_to_date_payload.keys()) == set(update_available_payload.keys())
    assert up_to_date_payload["status"] == "up_to_date"
    assert update_available_payload["status"] == "update_available"
    assert up_to_date_payload["current_version"] == update_available_payload["current_version"] == "0.1.3"
    assert up_to_date_payload["current_tag"] == update_available_payload["current_tag"] == "v0.1.3"
    assert up_to_date_payload["update_command"] is None
    assert update_available_payload["update_command"] == UPDATE_COMMAND
    assert up_to_date_payload["update_available"] is False
    assert update_available_payload["update_available"] is True
    assert up_to_date_payload["manual_update_required"] is False
    assert update_available_payload["manual_update_required"] is True
    assert up_to_date_payload["latest_version"] == "v0.1.3"
    assert update_available_payload["latest_version"] == "v0.2.0"


def test_system_update_endpoint_degraded_payload_is_frontend_consumable(monkeypatch):
    client, manager = _create_test_client(monkeypatch)

    def degraded_status(force=False):
        manager.status_calls.append(force)
        return {
            "current_version": "0.1.3",
            "current_tag": "v0.1.3",
            "latest_version": None,
            "update_available": False,
            "status": "degraded",
            "update_command": None,
            "message": "Release information is temporarily unavailable.",
            "manual_update_required": False,
        }

    manager.get_status = degraded_status

    response = client.get("/api/system/update")
    payload = response.json()

    assert response.status_code == 200
    assert set(payload.keys()) == {
        "current_version",
        "current_tag",
        "latest_version",
        "update_available",
        "status",
        "update_command",
        "message",
        "manual_update_required",
    }
    assert payload["status"] == "degraded"
    assert payload["latest_version"] is None
    assert payload["update_command"] is None
    assert payload["update_available"] is False



def test_system_update_status_endpoint_returns_503_on_failure(monkeypatch):
    client, manager = _create_test_client(monkeypatch)
    manager.raise_status = RuntimeError("boom")

    response = client.get("/api/system/update")

    assert response.status_code == 503
    assert response.json()["detail"] == "Unable to check for releases right now."



def test_system_trigger_update_returns_manual_helper_payload(monkeypatch):
    client, manager = _create_test_client(monkeypatch)

    response = client.post("/api/system/update")

    assert response.status_code == 200
    assert response.json() == {
        "status": "update_available",
        "message": "Automatic updates are no longer supported. Pull the latest image and rerun the container manually.",
        "current_version": "0.1.3",
        "current_tag": "v0.1.3",
        "latest_version": "v0.2.0",
        "update_available": True,
        "update_command": UPDATE_COMMAND,
        "manual_update_required": True,
        "manual_update_only": True,
        "deprecated": True,
    }
    assert manager.manual_payload_calls == 1


def test_system_trigger_update_is_deprecated_manual_only_endpoint(monkeypatch):
    client, manager = _create_test_client(monkeypatch)

    response = client.post("/api/system/update")
    payload = response.json()

    assert response.status_code == 200
    assert payload["deprecated"] is True
    assert payload["manual_update_only"] is True
    assert payload["update_command"] == UPDATE_COMMAND
    assert manager.manual_payload_calls == 1
    assert manager.status_calls == [False]


def test_system_trigger_update_degraded_payload_stays_notify_only(monkeypatch):
    client, manager = _create_test_client(monkeypatch)

    def degraded_manual_payload():
        manager.manual_payload_calls += 1
        return {
            "status": "degraded",
            "message": "Automatic updates are no longer supported. Pull the latest image and rerun the container manually.",
            "current_version": "0.1.3",
            "current_tag": "v0.1.3",
            "latest_version": None,
            "update_available": False,
            "update_command": None,
            "manual_update_required": False,
            "manual_update_only": True,
            "deprecated": True,
        }

    manager.get_manual_update_payload = degraded_manual_payload

    response = client.post("/api/system/update")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "message": "Automatic updates are no longer supported. Pull the latest image and rerun the container manually.",
        "current_version": "0.1.3",
        "current_tag": "v0.1.3",
        "latest_version": None,
        "update_available": False,
        "update_command": None,
        "manual_update_required": False,
        "manual_update_only": True,
        "deprecated": True,
    }
    assert manager.manual_payload_calls == 1
    assert manager.status_calls == [False]



def test_system_trigger_update_returns_503_when_helper_generation_fails(monkeypatch):
    client, manager = _create_test_client(monkeypatch)
    manager.raise_manual_payload = RuntimeError("boom")

    response = client.post("/api/system/update")

    assert response.status_code == 503
    assert response.json()["detail"] == "Unable to prepare manual update instructions right now."
    assert manager.manual_payload_calls == 1
