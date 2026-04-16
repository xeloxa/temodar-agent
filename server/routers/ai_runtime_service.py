import logging
from pathlib import Path
from typing import Any, Callable, Dict, List

from fastapi import HTTPException, status

from ai.runtime_bridge import BridgeError, BridgeProtocolError, BridgeTimeoutError
from runtime_paths import resolve_runtime_paths
from server.routers.ai_serialization import (
    serialize_run_task,
    serialize_team_event,
    split_tool_activity,
)

logger = logging.getLogger("temodar_agent.ai.router")


def persist_failed_run_message(
    *,
    repo,
    run_id: int,
    thread_id: int,
    message: str,
    tool_calls: List[Dict[str, Any]] | None = None,
    tool_results: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return repo.fail_run_with_assistant_message(
        run_id=run_id,
        thread_id=thread_id,
        content=message,
        error_message=message,
        tool_calls=tool_calls,
        tool_results=tool_results,
    )


def resolve_effective_last_scan_session_id(
    thread: Dict[str, Any],
    requested_last_scan_session_id: int | None,
) -> int | None:
    if requested_last_scan_session_id is not None:
        return int(requested_last_scan_session_id)
    persisted_last_scan_session_id = thread.get("last_scan_session_id")
    if persisted_last_scan_session_id is None:
        return None
    return int(persisted_last_scan_session_id)


def resolve_source_dir(
    *,
    repo,
    thread: Dict[str, Any],
    last_scan_session_id: int | None,
    path_cwd: Callable[[], Path],
    resolve_existing_thread_source_path: Callable[..., Path | None],
) -> Path | None:
    try:
        return resolve_existing_thread_source_path(
            db_path=repo.db_path,
            plugin_slug=thread["plugin_slug"],
            is_theme=bool(thread.get("is_theme")),
            last_scan_session_id=last_scan_session_id,
            root_path=path_cwd(),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def prepare_thread_for_message(*, repo, payload) -> tuple[Dict[str, Any], int | None]:
    thread = repo.get_thread(payload.thread_id)
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI thread not found.",
        )

    effective_last_scan_session_id = resolve_effective_last_scan_session_id(
        thread,
        payload.last_scan_session_id,
    )
    if effective_last_scan_session_id is not None:
        repo.update_thread_metadata(
            thread_id=payload.thread_id,
            last_scan_session_id=effective_last_scan_session_id,
        )
    return repo.get_thread(payload.thread_id) or thread, effective_last_scan_session_id


def prepare_thread_run_context(
    *,
    repo,
    thread: Dict[str, Any],
    last_scan_session_id: int | None,
    path_cwd: Callable[[], Path],
    resolve_existing_thread_source_path: Callable[..., Path | None],
    runtime_events: List[Dict[str, Any]],
) -> tuple[Path | None, Path, str]:
    runtime_events.append(
        {
            "type": "source_prepare_started",
            "data": {
                "slug": str(thread.get("plugin_slug") or ""),
                "is_theme": bool(thread.get("is_theme")),
                "mode": "trusted_source_lookup",
            },
        }
    )
    source_dir = resolve_source_dir(
        repo=repo,
        thread=thread,
        last_scan_session_id=last_scan_session_id,
        path_cwd=path_cwd,
        resolve_existing_thread_source_path=resolve_existing_thread_source_path,
    )
    if source_dir is not None:
        resolved_source = source_dir.resolve()
        runtime_events.append(
            {
                "type": "source_prepare_completed",
                "data": {
                    "slug": str(thread.get("plugin_slug") or ""),
                    "is_theme": bool(thread.get("is_theme")),
                    "mode": "source",
                    "source_path": str(resolved_source),
                },
            }
        )
        return resolved_source, resolved_source, str(resolved_source)

    workspace_root = path_cwd()
    runtime_events.append(
        {
            "type": "source_prepare_failed",
            "data": {
                "slug": str(thread.get("plugin_slug") or ""),
                "is_theme": bool(thread.get("is_theme")),
                "mode": "metadata_only",
                "reason": "trusted_source_unavailable",
            },
        }
    )
    workspace_source_path = str(workspace_root.resolve())
    return source_dir, workspace_root, workspace_source_path


def create_user_message_and_run(
    *,
    repo,
    thread_id: int,
    content: str,
    active_provider: Dict[str, Any],
    workspace_source_path: str,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    user_message = repo.create_message(
        thread_id=thread_id,
        role="user",
        content=content,
    )
    run = repo.create_run(
        thread_id=thread_id,
        provider=active_provider["provider"],
        provider_label=active_provider.get("provider_label"),
        model=active_provider.get("model"),
        status="running",
        message_id=user_message["id"],
        workspace_path=workspace_source_path,
    )
    return user_message, run


def build_approval_control_path(*, workspace_root: Path, thread_id: int, run_id: int) -> Path:
    del workspace_root
    approvals_dir = resolve_runtime_paths().approvals_dir
    approvals_dir.mkdir(parents=True, exist_ok=True)
    return approvals_dir / f"thread-{thread_id}-run-{run_id}.json"


def arm_manual_run_approval_if_needed(*, repo, payload, run_id: int, workspace_root: Path) -> str | None:
    if str(getattr(payload, "approval_mode", "off") or "off") != "manual":
        return None
    approval_control_path = str(
        build_approval_control_path(
            workspace_root=workspace_root,
            thread_id=payload.thread_id,
            run_id=run_id,
        ).resolve()
    )
    repo.upsert_run_approval(
        run_id,
        payload.thread_id,
        status="armed",
        control_path=approval_control_path,
        mode="manual",
        request_payload={},
    )
    return approval_control_path


def auto_approve_pending_run_approval(*, repo, run_id: int, thread_id: int) -> None:
    existing_approval = repo.get_run_approval(run_id)
    if existing_approval and str(existing_approval.get("status") or "") == "pending":
        repo.upsert_run_approval(
            run_id,
            thread_id,
            status="decided",
            decision="approved",
        )


def persist_run_activity(
    *, repo, run_id: int, events: List[Dict[str, Any]], tasks: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    normalized_events: List[Dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("type") or "")
        raw_data = event.get("data")
        data: Dict[str, Any] = (
            dict(raw_data) if isinstance(raw_data, dict) else {"value": raw_data}
        )
        agent_name = data.get("from") or data.get("assignee")
        if event_type in {"agent_started", "agent_completed", "tool_call"}:
            agent_name = data.get("name") or agent_name
        task_id = data.get("id") or data.get("taskId")
        normalized_events.append(
            {
                "event_type": event_type,
                "agent_name": str(agent_name) if agent_name is not None else None,
                "task_id": str(task_id) if task_id is not None else None,
                "payload": data,
            }
        )

    normalized_tasks = [
        {
            "task_id": str(task.get("id") or ""),
            "title": str(task.get("title") or ""),
            "status": str(task.get("status") or "pending"),
            "assignee": str(task.get("assignee")) if task.get("assignee") is not None else None,
            "depends_on": [
                str(item)
                for item in task.get("dependsOn") or task.get("depends_on") or []
            ],
            "result_text": str(task.get("result")) if task.get("result") is not None else None,
        }
        for task in tasks
    ]

    repo.create_run_events(run_id, normalized_events)
    repo.upsert_run_tasks(run_id, normalized_tasks)

    return (
        [serialize_team_event(item) for item in normalized_events],
        [serialize_run_task(item) for item in normalized_tasks],
    )


def persist_completed_run(
    *,
    repo,
    thread_id: int,
    run_id: int,
    bridge_result: Dict[str, Any],
    source_dir: Path | None,
    runtime_events: List[Dict[str, Any]] | None = None,
) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    run_events = [*(runtime_events or []), *(bridge_result.get("events", []) or [])]
    run_result_payload = (
        bridge_result.get("result")
        if isinstance(bridge_result.get("result"), dict)
        else {}
    )
    run_tasks = (
        run_result_payload.get("tasks", [])
        if isinstance(run_result_payload, dict)
        else []
    )
    team_events, persisted_tasks = persist_run_activity(
        repo=repo,
        run_id=run_id,
        events=run_events,
        tasks=run_tasks,
    )
    tool_calls, tool_results = split_tool_activity(run_events)
    assistant_output = str(bridge_result.get("output") or "")
    if source_dir is None:
        note = "\n\n[Context note] No trusted local source directory was available, so this response used stored metadata only."
        assistant_output = f"{assistant_output}{note}" if assistant_output else note.strip()
    assistant_message = repo.create_message(
        thread_id=thread_id,
        role="assistant",
        content=assistant_output,
        tool_calls=tool_calls or None,
        tool_results=tool_results or None,
    )
    repo.finish_run(run_id=run_id, status="completed")
    return assistant_message, team_events, persisted_tasks


def raise_mapped_ai_error(
    *, repo, exc: Exception, run: Dict[str, Any] | None, thread_id: int
) -> None:
    if isinstance(exc, BridgeTimeoutError):
        message = str(exc)
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    elif isinstance(exc, (BridgeProtocolError, BridgeError)):
        message = str(exc)
        status_code = status.HTTP_502_BAD_GATEWAY
    elif isinstance(exc, OSError):
        message = f"Failed to prepare AI context: {exc}"
        status_code = status.HTTP_400_BAD_REQUEST
    else:
        message = f"AI request failed unexpectedly: {exc}"
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        logger.exception("Unexpected AI request failure", exc_info=exc)

    if run is not None:
        persist_failed_run_message(
            repo=repo,
            run_id=run["id"],
            thread_id=thread_id,
            message=message,
        )

    raise HTTPException(status_code=status_code, detail=message) from exc


def cleanup_workspace(
    *,
    source_dir: Path | None,
    workspace_root: Path | None,
    cleanup_run_workspace: Callable[[Path], None],
) -> None:
    if source_dir is None or workspace_root is None:
        return
    if workspace_root.resolve() == source_dir.resolve():
        return
    try:
        cleanup_run_workspace(workspace_root)
    except OSError:
        logger.warning(
            "Failed to clean up AI workspace: %s",
            workspace_root,
            exc_info=True,
        )
