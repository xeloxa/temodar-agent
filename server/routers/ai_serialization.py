import json
from pathlib import Path
from typing import Any, Dict, List

from ai.context_builder import resolve_existing_thread_source_path
from runtime_paths import resolve_runtime_paths


def serialize_settings(repo, settings: Dict[str, Any] | None) -> Dict[str, Any] | None:
    sanitized = repo.sanitize_provider_settings(settings)
    if sanitized is None:
        return None
    return {
        **sanitized,
        "is_active": bool(sanitized.get("is_active")),
    }


def serialize_settings_profiles(repo, profiles: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    return [serialize_settings(repo, item) for item in (profiles or []) if serialize_settings(repo, item) is not None]


def serialize_settings_dashboard(repo, active_profile: Dict[str, Any] | None, profiles: List[Dict[str, Any]] | None) -> Dict[str, Any]:
    serialized_profiles = serialize_settings_profiles(repo, profiles)
    active_serialized = serialize_settings(repo, active_profile)
    providers = {str(item.get('provider') or '').strip() for item in serialized_profiles if item.get('provider')}
    models = {str(item.get('model') or '').strip() for item in serialized_profiles if item.get('model')}
    active_count = sum(1 for item in serialized_profiles if item.get('is_active'))
    return {
        'active_profile': active_serialized,
        'profiles': serialized_profiles,
        'stats': {
            'total_profiles': len(serialized_profiles),
            'active_profiles': active_count,
            'provider_count': len(providers),
            'configured_models': len(models),
        },
    }


def serialize_message(message: Dict[str, Any]) -> Dict[str, Any]:
    tool_calls = message.get("tool_calls")
    if tool_calls is None and message.get("tool_calls_json"):
        tool_calls = json.loads(str(message["tool_calls_json"]))

    tool_results = message.get("tool_results")
    if tool_results is None and message.get("tool_results_json"):
        tool_results = json.loads(str(message["tool_results_json"]))

    return {
        "id": int(message["id"]),
        "thread_id": int(message["thread_id"]),
        "role": str(message["role"]),
        "content": str(message["content"]),
        "tool_calls": tool_calls or [],
        "tool_results": tool_results or [],
        "created_at": str(message["created_at"]),
    }


def serialize_thread(thread: Dict[str, Any]) -> Dict[str, Any]:
    last_source_path = str(thread.get("last_source_path") or "").strip()
    existing_source = resolve_existing_thread_source_path(
        db_path=None,
        plugin_slug=str(thread.get("plugin_slug") or "").strip(),
        is_theme=bool(thread.get("is_theme")),
        last_scan_session_id=thread.get("last_scan_session_id"),
        root_path=resolve_runtime_paths().root,
    )
    source_path = str(existing_source.resolve()) if existing_source is not None else last_source_path
    source_available = bool(source_path)
    source_context_mode = "attached" if source_available else "metadata_only"

    return {
        "id": int(thread["id"]),
        "plugin_slug": str(thread["plugin_slug"]),
        "is_theme": bool(thread.get("is_theme")),
        "title": thread.get("title"),
        "last_scan_session_id": thread.get("last_scan_session_id"),
        "created_at": str(thread["created_at"]),
        "updated_at": str(thread["updated_at"]),
        "source_available": source_available,
        "source_context_mode": source_context_mode,
        "source_path": source_path,
        "workspace_path": source_path,
    }


def event_payloads_to_structured_activity(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    activity: List[Dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("type") or "")
        if not event_type.startswith("tool_"):
            continue
        raw_data = event.get("data")
        data: Dict[str, Any] = dict(raw_data) if isinstance(raw_data, dict) else {"value": raw_data}
        payload = {**data, "type": event_type}
        activity.append(payload)
    return activity


def serialize_team_event(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": str(item.get("event_type") or ""),
        "agent": item.get("agent_name"),
        "task_id": item.get("task_id"),
        "data": item.get("payload") or {},
    }


def serialize_run_task(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(item.get("task_id") or ""),
        "title": str(item.get("title") or ""),
        "status": str(item.get("status") or "pending"),
        "assignee": item.get("assignee"),
        "depends_on": item.get("depends_on") or [],
        "result": item.get("result_text"),
    }


def serialize_run_approval(item: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not item:
        return None
    return {
        "run_id": int(item.get("run_id") or 0),
        "thread_id": int(item.get("thread_id") or 0),
        "status": str(item.get("status") or "pending"),
        "mode": item.get("mode"),
        "decision": item.get("decision"),
        "request_payload": item.get("request_payload") or {},
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def split_tool_activity(events: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    tool_calls: List[Dict[str, Any]] = []
    tool_results: List[Dict[str, Any]] = []
    for item in event_payloads_to_structured_activity(events):
        item_type = str(item.get("type") or "")
        payload = {key: value for key, value in item.items() if key != "type"}
        if item_type == "tool_call":
            tool_calls.append(payload)
        elif item_type in {"tool_result", "tool_output"}:
            tool_results.append(payload)
    return tool_calls, tool_results


def list_structured_thread_events(repo, thread_id: int) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for message in repo.list_messages(thread_id):
        if message.get("tool_calls"):
            events.extend({"type": "tool_call", "data": item} for item in message["tool_calls"])
        if message.get("tool_results"):
            events.extend({"type": "tool_result", "data": item} for item in message["tool_results"])
    return events


def list_latest_thread_team_events(repo, thread_id: int) -> List[Dict[str, Any]]:
    runs = repo.list_thread_runs(thread_id)
    if not runs:
        return []

    for run in reversed(runs):
        run_id = int(run.get("id") or 0)
        if run_id <= 0:
            continue
        run_events = repo.list_run_events(run_id)
        if run_events:
            return [serialize_team_event(item) for item in run_events]

    return []
