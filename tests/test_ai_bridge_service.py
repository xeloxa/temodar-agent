from pathlib import Path

from ai.runtime_bridge import _build_child_env, _payload_without_runtime_env
from server.routers.ai_bridge_service import build_bridge_payload, build_system_prompt


def test_build_system_prompt_includes_wp_hunter_security_focus_and_metadata_context():
    prompt = build_system_prompt(
        context={
            "plugin": {
                "slug": "akismet",
                "metrics": {
                    "risk_score": 2,
                    "installations": 1000,
                    "days_since_update": 0,
                    "latest_version": "1.2.3",
                    "semgrep_findings": 0,
                },
            },
            "semgrep": {
                "snapshot": {
                    "findings_count": 0,
                    "latest_version": "1.2.3",
                    "has_completed_scan": True,
                    "summary_total_findings": 0,
                }
            },
            "source": {"available": False},
        },
        workspace_root=Path("/tmp/workspace"),
        execution_mode="raw_open_multi_agent",
        team_mode="single_agent",
        context_summary="",
    )

    assert "Temodar Agent" in prompt
    assert "No trusted source directory is available" in prompt
    assert "attempt a tool-based fetch first" in prompt
    assert '"metrics": {' in prompt
    assert '"risk_score": 2' in prompt
    assert '"installations": 1000' in prompt
    assert '"findings_count": 0' in prompt
    assert "Tool policy:" in prompt


def test_build_bridge_payload_filters_unsupported_custom_fields():
    payload = build_bridge_payload(
        active_provider={
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "api_key": "secret",
            "base_url": "https://api.anthropic.com",
            "tool_policy": {"legacy": True},
            "working_directory": "/tmp/workspace",
            "allowed_tools": ["read"],
            "disallowed_tools": ["python3"],
            "metadata": {"legacy": True},
            "stream": True,
            "debug": True,
            "session_id": "abc",
            "agent_name": "legacy",
            "team_name": "legacy-team",
            "extra": {"legacy": True},
        },
        prompt="inspect source",
        context={"plugin": {"slug": "akismet"}, "source": {"available": True}},
        workspace_root=Path("/tmp/workspace"),
        source_dir=Path("/tmp/workspace"),
        execution_mode="raw_open_multi_agent",
        team_mode="single_agent",
        strategy="agent",
        context_summary="",
        needs_tools=True,
        trace_enabled=True,
    )

    assert payload["workspaceRoot"].endswith("/tmp/workspace")
    assert payload["provider"] == "anthropic"
    assert payload["needsTools"] is True
    assert payload["traceEnabled"] is True
    assert payload["runtimeEnv"]["TEMODAR_AI_API_KEY"] == "secret"
    assert "loopDetection" not in payload
    assert "toolPolicy" not in payload
    assert "workingDirectory" not in payload
    assert "allowedTools" not in payload
    assert "disallowedTools" not in payload
    assert "metadata" not in payload
    assert "stream" not in payload
    assert "debug" not in payload
    assert "sessionId" not in payload
    assert "agentName" not in payload
    assert "teamName" not in payload
    assert "extra" not in payload


def test_build_bridge_payload_passes_supported_runtime_overrides():
    payload = build_bridge_payload(
        active_provider={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "api_key": "secret",
            "base_url": "http://localhost:11434/v1",
            "output_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
        },
        prompt="inspect source",
        context={"plugin": {"slug": "akismet"}, "source": {"available": True}},
        workspace_root=Path("/tmp/workspace"),
        source_dir=Path("/tmp/workspace"),
        execution_mode="raw_open_multi_agent",
        team_mode="tasks",
        strategy="tasks",
        context_summary="recent context",
        tasks=[{"title": "Inspect source", "description": "Read files", "assignee": "researcher"}],
        fanout={"analysts": [{"name": "optimist", "role": "optimist"}]},
        loop_detection={"maxRepetitions": 3, "loopDetectionWindow": 5, "onLoopDetected": "warn"},
        needs_tools=True,
        trace_enabled=False,
    )

    assert payload["strategy"] == "tasks"
    assert payload["teamMode"] == "tasks"
    assert payload["traceEnabled"] is False
    assert payload["contextSummary"] == "recent context"
    assert payload["outputSchema"]["type"] == "object"
    assert payload["tasks"][0]["title"] == "Inspect source"
    assert payload["fanout"]["analysts"][0]["name"] == "optimist"
    assert payload["loopDetection"]["onLoopDetected"] == "warn"


def test_runtime_env_is_scoped_to_child_process(monkeypatch):
    monkeypatch.setenv("TEMODAR_AI_API_KEY", "stale")
    payload = {
        "provider": "openai",
        "runtimeEnv": {"TEMODAR_AI_API_KEY": "fresh", "EXTRA_FLAG": "1"},
    }

    child_env = _build_child_env(payload)
    sanitized_payload = _payload_without_runtime_env(payload)

    assert child_env["TEMODAR_AI_API_KEY"] == "fresh"
    assert child_env["EXTRA_FLAG"] == "1"
    assert "runtimeEnv" not in sanitized_payload
