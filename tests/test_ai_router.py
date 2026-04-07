import json
import sqlite3

from fastapi.testclient import TestClient

from ai.repository import AIRepository
from database.models import init_db
from server.app import create_app


def _insert_scan_result(db_path, session_id, slug, is_theme=False, version="1.0.0"):
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO scan_sessions (id, status, total_found, high_risk_count) VALUES (?, 'completed', 1, 0)",
            (session_id,),
        )
        cursor.execute(
            "INSERT INTO scan_results (session_id, slug, version, is_theme) VALUES (?, ?, ?, ?)",
            (session_id, slug, version, int(is_theme)),
        )
        conn.commit()


def _prepare_thread_source(tmp_path, slug, *, is_theme=False):
    root_dir = "Themes" if is_theme else "Plugins"
    source_dir = tmp_path / root_dir / slug / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "plugin.php").write_text("<?php // plugin", encoding="utf-8")
    return source_dir


def _prepare_trusted_source(monkeypatch, tmp_path, db_path, slug, session_id, *, is_theme=False):
    _insert_scan_result(db_path, session_id, slug, is_theme=is_theme)
    _prepare_thread_source(tmp_path, slug, is_theme=is_theme)
    monkeypatch.setattr("server.routers.ai.Path.cwd", lambda: tmp_path)
    return tmp_path


def _create_test_client(monkeypatch, db_path):
    monkeypatch.setenv("TEMODAR_AGENT_DB", str(db_path))
    monkeypatch.setattr(
        "server.app.update_manager.manager.get_status",
        lambda force=False: {"status": "ok"},
    )
    return TestClient(create_app(), base_url="http://localhost")


def test_classify_message_intent_always_routes_to_workspace(tmp_path):
    from server.routers.ai_intent_service import classify_message_intent

    repo = AIRepository(db_path=tmp_path / "ai_router.db")
    thread = repo.get_or_create_thread(plugin_slug="akismet", is_theme=False)

    social_intent = classify_message_intent(content="hello", repo=repo, thread_id=thread["id"])
    assert social_intent["needs_tools"] is True
    assert social_intent["needs_workspace_access"] is True

    workspace_intent = classify_message_intent(content="scan this plugin source code for security issues", repo=repo, thread_id=thread["id"])
    assert workspace_intent["needs_tools"] is True
    assert workspace_intent["needs_workspace_access"] is True
    assert workspace_intent["execution_mode"] == "raw_open_multi_agent"


def test_resolve_message_intent_returns_raw_open_multi_agent_shape(tmp_path):
    from server.routers.ai_intent_service import resolve_message_intent

    repo = AIRepository(db_path=tmp_path / "ai_router.db")
    thread = repo.get_or_create_thread(plugin_slug="akismet", is_theme=False)

    result = resolve_message_intent(
        content="read the source and summarize the main attack surface",
        repo=repo,
        thread_id=thread["id"],
        thread=thread,
        context_summary="",
        active_provider={"provider": "anthropic", "api_key": "k", "model": "m"},
    )

    assert result["execution_mode"] == "raw_open_multi_agent"
    assert result["team_mode"] == "single_agent"
    assert result["normalized_decision"]["composition_source"] == "raw_open_multi_agent"


def test_summarize_recent_thread_context_returns_recent_messages(tmp_path):
    from server.routers.ai_service import summarize_recent_thread_context

    repo = AIRepository(db_path=tmp_path / "ai_router.db")
    thread = repo.get_or_create_thread(plugin_slug="akismet", is_theme=False)
    repo.create_message(thread_id=thread["id"], role="user", content="First message")
    repo.create_message(thread_id=thread["id"], role="assistant", content="First reply")

    summary = summarize_recent_thread_context(repo, thread["id"])

    assert "- user: First message" in summary
    assert "- assistant: First reply" in summary


def test_list_thread_messages_keeps_long_running_runs_pending(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)
    user_message = repository.create_message(thread_id=thread["id"], role="user", content="Run a full scan")
    repository.create_run(
        thread_id=thread["id"],
        provider="anthropic",
        provider_label="Anthropic",
        model="claude",
        status="running",
        message_id=user_message["id"],
        workspace_path=str(tmp_path),
    )

    client = _create_test_client(monkeypatch, db_path)
    response = client.get(
        f"/api/ai/threads/{thread['id']}/messages",
        params={"plugin_slug": "akismet", "is_theme": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_pending_run"] is True
    assert payload["messages"][0]["role"] == "user"


def test_list_thread_messages_hides_stale_pending_approval_for_completed_run(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)

    run = repository.create_run(
        thread_id=thread["id"],
        provider="anthropic",
        provider_label="Anthropic",
        model="claude",
        status="running",
        workspace_path=str(tmp_path),
    )
    repository.upsert_run_approval(
        run_id=run["id"],
        thread_id=thread["id"],
        status="pending",
        mode="manual",
        request_payload={"nextTasks": [{"id": "task-1", "title": "Inspect workspace"}]},
    )
    repository.finish_run(run["id"], "completed")

    client = _create_test_client(monkeypatch, db_path)
    response = client.get(
        f"/api/ai/threads/{thread['id']}/messages",
        params={"plugin_slug": "akismet", "is_theme": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_pending_run"] is False
    assert payload["pending_approval"] is None


def test_create_message_workspace_default_prepares_workspace_even_for_short_prompt(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    repository.upsert_provider_settings(
        provider="anthropic",
        api_key="test-key",
        model="claude-3-7-sonnet",
        base_url="https://api.anthropic.com",
        is_active=True,
    )
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)

    monkeypatch.setattr("server.routers.ai.Path.cwd", lambda: tmp_path)

    prepare_calls = []
    bridge_payloads = []

    def fake_prepare(**kwargs):
        prepare_calls.append(kwargs)
        return tmp_path, tmp_path, str(tmp_path)

    def fake_bridge(payload):
        bridge_payloads.append(payload)
        return {"output": "Hello!", "events": [], "result": {"content": "Hello!", "agents": [], "tasks": []}}

    monkeypatch.setattr("server.routers.ai_service.prepare_thread_run_context", fake_prepare)
    monkeypatch.setattr("server.routers.ai.run_agent_bridge", fake_bridge)
    monkeypatch.setattr(
        "server.routers.ai.build_plugin_context_for_source",
        lambda **kwargs: {"plugin": {"slug": "akismet"}, "source": {"available": True, "mode": "source"}},
    )

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        "/api/ai/messages",
        json={"thread_id": thread["id"], "content": "hello"},
    )

    assert response.status_code == 200
    assert len(prepare_calls) == 1
    assert bridge_payloads[0]["executionMode"] == "raw_open_multi_agent"
    assert bridge_payloads[0]["teamMode"] == "single_agent"
    assert bridge_payloads[0]["needsTools"] is True


def test_create_message_workspace_mode_builds_bridge_payload(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    repository.upsert_provider_settings(
        provider="anthropic",
        api_key="test-key",
        model="claude-3-7-sonnet",
        base_url="https://api.anthropic.com",
        is_active=True,
    )
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)
    _prepare_trusted_source(monkeypatch, tmp_path, db_path, "akismet", 1, is_theme=False)

    captured_payload = {}
    monkeypatch.setattr(
        "server.routers.ai.build_plugin_context_for_source",
        lambda **kwargs: {
            "source_path": str(kwargs["source_dir"]),
            "plugin": {"slug": "akismet"},
            "semgrep": {"scan": None, "summary": {}, "findings": []},
            "source": {"available": True, "mode": "source"},
        },
    )
    monkeypatch.setattr(
        "server.routers.ai.run_agent_bridge",
        lambda payload: captured_payload.update(payload) or {"output": "Assistant summary", "events": [], "result": {"content": "Assistant summary", "agents": [], "tasks": []}},
    )

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        "/api/ai/messages",
        json={
            "thread_id": thread["id"],
            "content": "scan this plugin for security issues",
            "last_scan_session_id": 1,
        },
    )

    assert response.status_code == 200
    assert captured_payload["executionMode"] == "raw_open_multi_agent"
    assert captured_payload["teamMode"] == "single_agent"
    assert captured_payload["workspaceRoot"].endswith("/Plugins/akismet/source")
    assert captured_payload["needsTools"] is True
    assert captured_payload["runtimeEnv"]["TEMODAR_AI_API_KEY"] == "test-key"
    assert 'Temodar Agent' in captured_payload["systemPrompt"]


def test_create_message_runs_bridge_and_stores_assistant_output(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    repository.upsert_provider_settings(
        provider="anthropic",
        api_key="test-key",
        model="claude-3-7-sonnet",
        base_url="https://api.anthropic.com",
        is_active=True,
    )
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)
    _prepare_trusted_source(monkeypatch, tmp_path, db_path, "akismet", 1, is_theme=False)

    monkeypatch.setattr(
        "server.routers.ai.build_plugin_context_for_source",
        lambda **kwargs: {"source": {"available": True}, "plugin": {"slug": "akismet"}, "source_path": str(kwargs["source_dir"])},
    )

    def fake_bridge(payload):
        return {
            "output": "Assistant summary",
            "events": [
                {"type": "decision_trace", "data": {"execution_mode": "raw_open_multi_agent"}},
                {"type": "tool_call", "data": {"name": "read", "path": "plugin.php"}},
                {"type": "tool_result", "data": {"name": "read", "status": "ok"}},
            ],
            "result": {
                "content": "Assistant summary",
                "agents": [{"name": "source_agent", "role": "source_code_assistant", "success": True, "output": "Assistant summary"}],
                "tasks": [{"id": "direct-source-conversation", "title": "Direct source conversation", "status": "completed", "assignee": "source_agent", "result": "Assistant summary"}],
            },
        }

    monkeypatch.setattr("server.routers.ai.run_agent_bridge", fake_bridge)

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        "/api/ai/messages",
        json={
            "thread_id": thread["id"],
            "content": "scan this plugin for security issues",
            "last_scan_session_id": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_message"]["content"] == "Assistant summary"
    assert payload["events"] == [
        {"type": "tool_call", "data": {"name": "read", "path": "plugin.php"}},
        {"type": "tool_result", "data": {"name": "read", "status": "ok"}},
    ]
    assert payload["agents"][0]["name"] == "source_agent"
    assert payload["tasks"][0]["id"] == "direct-source-conversation"


def test_create_message_uses_metadata_only_mode_when_trusted_source_path_is_missing(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    repository.upsert_provider_settings(
        provider="anthropic",
        api_key="test-key",
        model="claude-3-7-sonnet",
        base_url="https://api.anthropic.com",
        is_active=True,
    )
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)

    _insert_scan_result(db_path, 1, "akismet", is_theme=False)
    monkeypatch.setattr("server.routers.ai.Path.cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "server.routers.ai.run_agent_bridge",
        lambda payload: {"output": "Assistant summary", "events": [], "result": {"content": "Assistant summary"}},
    )

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        "/api/ai/messages",
        json={
            "thread_id": thread["id"],
            "content": "scan this plugin",
            "last_scan_session_id": 1,
        },
    )

    assert response.status_code == 200
    assert "No trusted local source directory was available" in response.json()["assistant_message"]["content"]


def test_create_message_applies_runtime_overrides_to_bridge_payload(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    repository.upsert_provider_settings(
        provider="openai",
        api_key="test-key",
        model="gpt-4.1-mini",
        base_url="http://localhost:11434/v1",
        is_active=True,
    )
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)
    _prepare_trusted_source(monkeypatch, tmp_path, db_path, "akismet", 1, is_theme=False)

    captured_payload = {}
    monkeypatch.setattr(
        "server.routers.ai.build_plugin_context_for_source",
        lambda **kwargs: {"source": {"available": True}, "plugin": {"slug": "akismet"}, "source_path": str(kwargs["source_dir"])},
    )
    monkeypatch.setattr(
        "server.routers.ai.run_agent_bridge",
        lambda payload: captured_payload.update(payload) or {"output": "Assistant summary", "events": [], "result": {"content": "Assistant summary", "agents": [], "tasks": []}},
    )

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        "/api/ai/messages",
        json={
            "thread_id": thread["id"],
            "content": "inspect this plugin with a task pipeline",
            "last_scan_session_id": 1,
            "strategy": "tasks",
            "trace_enabled": False,
            "output_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
            "tasks": [{"title": "Inspect source", "description": "Read key files", "assignee": "researcher", "maxRetries": 2}],
            "fanout": {"analysts": [{"name": "optimist", "role": "optimist"}]},
            "loop_detection": {"maxRepetitions": 3, "loopDetectionWindow": 5, "onLoopDetected": "warn"},
            "approval_mode": "auto_approve",
            "before_run": {"promptPrefix": "Use strict evidence."},
            "after_run": {"outputSuffix": "End of reviewed output."},
        },
    )

    assert response.status_code == 200
    assert captured_payload["strategy"] == "tasks"
    assert captured_payload["teamMode"] == "tasks"
    assert captured_payload["traceEnabled"] is False
    assert captured_payload["outputSchema"]["properties"]["summary"]["type"] == "string"
    assert captured_payload["tasks"][0]["maxRetries"] == 2
    assert captured_payload["fanout"]["analysts"][0]["name"] == "optimist"
    assert captured_payload["loopDetection"]["onLoopDetected"] == "warn"
    assert captured_payload["approvalMode"] == "auto_approve"
    assert captured_payload["beforeRun"]["promptPrefix"] == "Use strict evidence."
    assert captured_payload["afterRun"]["outputSuffix"] == "End of reviewed output."


def test_create_message_stream_emits_runtime_bridge_and_final_events(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    repository.upsert_provider_settings(
        provider="anthropic",
        api_key="test-key",
        model="claude-3-7-sonnet",
        base_url="https://api.anthropic.com",
        is_active=True,
    )
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)
    _prepare_trusted_source(monkeypatch, tmp_path, db_path, "akismet", 1, is_theme=False)

    monkeypatch.setattr(
        "server.routers.ai.build_plugin_context_for_source",
        lambda **kwargs: {"source": {"available": True}, "plugin": {"slug": "akismet"}, "source_path": str(kwargs["source_dir"])},
    )

    def fake_stream(payload):
        yield {"type": "decision_trace", "data": {"execution_mode": "raw_open_multi_agent"}}
        yield {"type": "tool_call", "data": {"name": "read", "path": "plugin.php"}}
        yield {"type": "run_completed", "data": {"content": "Streamed assistant summary", "agents": [], "tasks": []}}

    monkeypatch.setattr("server.routers.ai.run_agent_bridge_stream", fake_stream)

    client = _create_test_client(monkeypatch, db_path)
    with client.stream(
        "POST",
        "/api/ai/messages/stream",
        json={"thread_id": thread["id"], "content": "scan this plugin", "last_scan_session_id": 1},
    ) as response:
        assert response.status_code == 200
        chunks = [json.loads(line) for line in response.iter_lines() if line]

    chunk_types = [chunk["type"] for chunk in chunks]
    assert "runtime_event" in chunk_types
    assert "bridge_event" in chunk_types
    assert "final" in chunk_types
    final_chunk = next(chunk for chunk in chunks if chunk["type"] == "final")
    assert final_chunk["data"]["assistant_message"]["content"] == "Streamed assistant summary"


def test_ai_settings_dashboard_lists_active_profile(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    repository.upsert_provider_settings(
        provider="anthropic",
        profile_key="anthropic-main",
        display_name="Anthropic Main",
        api_key="test-key",
        model="claude-3-7-sonnet",
        models=["claude-3-7-sonnet", "claude-3-5-haiku"],
        base_url="https://api.anthropic.com",
        is_active=True,
    )

    client = _create_test_client(monkeypatch, db_path)
    response = client.get("/api/ai/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_profile"]["profile_key"] == "anthropic-main"
    assert payload["active_profile"]["provider"] == "anthropic"
    assert payload["active_profile"]["is_active"] is True
    assert payload["stats"]["total_profiles"] == 1


def test_create_or_get_and_list_plugin_threads_endpoints(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)

    client = _create_test_client(monkeypatch, db_path)

    create_response = client.post(
        "/api/ai/threads/plugin",
        json={"plugin_slug": "akismet", "is_theme": False, "title": "Chat A"},
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["plugin_slug"] == "akismet"

    list_response = client.get(
        "/api/ai/threads/plugin",
        params={"plugin_slug": "akismet", "is_theme": False},
    )
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["threads"]
    assert listed["threads"][0]["id"] == created["id"]


def test_update_and_delete_thread_endpoints(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)

    client = _create_test_client(monkeypatch, db_path)

    patch_response = client.patch(
        f"/api/ai/threads/{thread['id']}",
        json={"plugin_slug": "akismet", "is_theme": False, "title": "Renamed Thread"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["title"] == "Renamed Thread"

    delete_response = client.request(
        "DELETE",
        f"/api/ai/threads/{thread['id']}",
        json={"plugin_slug": "akismet", "is_theme": False},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["ok"] is True


def test_prepare_thread_source_endpoint_returns_attached_thread(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)

    source_dir = _prepare_thread_source(tmp_path, "akismet", is_theme=False)
    monkeypatch.setattr("server.routers.ai.Path.cwd", lambda: tmp_path)

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        f"/api/ai/threads/{thread['id']}/source",
        json={
            "plugin_slug": "akismet",
            "is_theme": False,
            "last_scan_session_id": None,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["thread"]["id"] == thread["id"]
    assert payload["thread"]["source_available"] is True
    assert payload["thread"]["source_context_mode"] == "attached"
    assert payload["thread"]["source_path"] == str(source_dir.resolve())


def test_run_approval_endpoint_rejects_pending_run(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)
    run = repository.create_run(
        thread_id=thread["id"],
        provider="anthropic",
        provider_label="Anthropic",
        model="claude",
        status="running",
        workspace_path=str(tmp_path),
    )

    control_file = tmp_path / ".temodar-ai-approvals" / "decision.json"
    repository.upsert_run_approval(
        run_id=run["id"],
        thread_id=thread["id"],
        status="pending",
        mode="manual",
        control_path=str(control_file),
        request_payload={"nextTasks": [{"id": "t1", "title": "inspect"}]},
    )

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        f"/api/ai/runs/{run['id']}/approval",
        json={"plugin_slug": "akismet", "is_theme": False, "decision": "rejected"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "decided"
    assert payload["decision"] == "rejected"
    assert control_file.exists()
    assert json.loads(control_file.read_text(encoding="utf-8"))["decision"] == "rejected"


def test_run_approval_endpoint_returns_404_for_missing_run(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    AIRepository(db_path=db_path)

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        "/api/ai/runs/999/approval",
        json={"plugin_slug": "akismet", "is_theme": False, "decision": "approved"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "AI run not found."


def test_run_approval_endpoint_rejects_control_path_outside_workspace(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)
    run = repository.create_run(
        thread_id=thread["id"],
        provider="anthropic",
        provider_label="Anthropic",
        model="claude",
        status="running",
        workspace_path=str(tmp_path / "workspace"),
    )

    bad_control_file = tmp_path / "somewhere-else" / ".temodar-ai-approvals" / "decision.json"
    repository.upsert_run_approval(
        run_id=run["id"],
        thread_id=thread["id"],
        status="pending",
        mode="manual",
        control_path=str(bad_control_file),
        request_payload={"nextTasks": [{"id": "t1", "title": "inspect"}]},
    )

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        f"/api/ai/runs/{run['id']}/approval",
        json={"plugin_slug": "akismet", "is_theme": False, "decision": "approved"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid approval control path."


def test_update_thread_requires_valid_scope(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)

    client = _create_test_client(monkeypatch, db_path)
    response = client.patch(
        f"/api/ai/threads/{thread['id']}",
        json={"plugin_slug": "jetpack", "is_theme": False, "title": "Wrong scope"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "AI thread not found."


def test_prepare_thread_source_returns_404_for_invalid_scope(monkeypatch, tmp_path):
    db_path = tmp_path / "ai_router.db"
    repository = AIRepository(db_path=db_path)
    thread = repository.get_or_create_thread(plugin_slug="akismet", is_theme=False)

    client = _create_test_client(monkeypatch, db_path)
    response = client.post(
        f"/api/ai/threads/{thread['id']}/source",
        json={
            "plugin_slug": "jetpack",
            "is_theme": False,
            "last_scan_session_id": None,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "AI thread not found."
