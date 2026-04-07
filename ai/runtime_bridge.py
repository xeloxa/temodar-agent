import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterator, List


DEFAULT_BRIDGE_TIMEOUT_SECONDS = 120
NODE_RUNNER_PATH = Path(__file__).resolve().parent / "node_runner" / "dist" / "index.js"


class BridgeError(RuntimeError):
    pass


class BridgeTimeoutError(BridgeError):
    pass


class BridgeProtocolError(BridgeError):
    pass


def _validate_bridge_environment() -> None:
    if shutil.which("node") is None:
        raise BridgeError("AI agent bridge requires Node.js in the runtime environment.")
    if not NODE_RUNNER_PATH.exists():
        raise BridgeError("AI agent bridge runner is missing. Build ai/node_runner before use.")



def _parse_bridge_event_line(raw_line: str) -> Dict[str, Any]:
    line = raw_line.strip()
    if not line:
        return {}
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise BridgeProtocolError("AI agent bridge returned malformed output.") from exc



def _build_child_env(payload: Dict[str, Any]) -> Dict[str, str]:
    child_env = os.environ.copy()
    child_env.pop("TEMODAR_AI_API_KEY", None)

    runtime_env = payload.get("runtimeEnv") or {}
    if isinstance(runtime_env, dict):
        for key, value in runtime_env.items():
            if value is None:
                child_env.pop(str(key), None)
            else:
                child_env[str(key)] = str(value)
    return child_env



def _payload_without_runtime_env(payload: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(payload)
    sanitized.pop("runtimeEnv", None)
    return sanitized



def run_agent_bridge_stream(
    payload: Dict[str, Any],
    timeout_seconds: int = DEFAULT_BRIDGE_TIMEOUT_SECONDS,
) -> Iterator[Dict[str, Any]]:
    _validate_bridge_environment()
    child_env = _build_child_env(payload)
    safe_payload = _payload_without_runtime_env(payload)

    try:
        process = subprocess.Popen(
            ["node", str(NODE_RUNNER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=child_env,
        )
    except OSError as exc:
        raise BridgeError(f"AI agent bridge failed to start: {exc}") from exc

    try:
        if process.stdin is None or process.stdout is None:
            raise BridgeError("AI agent bridge failed to initialize stdio pipes.")

        process.stdin.write(json.dumps(safe_payload))
        process.stdin.close()

        completed_event_seen = False
        run_failed_message = ""
        for raw_line in process.stdout:
            event = _parse_bridge_event_line(raw_line)
            if not event:
                continue
            event_type = str(event.get("type") or "")
            if event_type == "run_completed":
                completed_event_seen = True
            elif event_type == "run_failed":
                event_data = event.get("data") or {}
                if isinstance(event_data, dict):
                    run_failed_message = str(event_data.get("message") or "").strip()
            yield event

        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait(timeout=5)
            raise BridgeTimeoutError("AI agent bridge timed out.") from exc

        stderr = (process.stderr.read() if process.stderr is not None else "").strip()
        if return_code != 0:
            raise BridgeError(run_failed_message or stderr or "AI agent bridge failed.")
        if not completed_event_seen:
            raise BridgeProtocolError(run_failed_message or "AI agent bridge did not return a completion event.")
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()



def run_agent_bridge(
    payload: Dict[str, Any],
    timeout_seconds: int = DEFAULT_BRIDGE_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {}
    output = ""

    for event in run_agent_bridge_stream(payload, timeout_seconds=timeout_seconds):
        event_type = event.get("type")
        event_data = event.get("data") or {}
        if event_type == "run_completed":
            if isinstance(event_data, dict):
                result = event_data
                output = str(event_data.get("content") or event_data.get("output") or "")
            else:
                output = str(event_data)
                result = {"content": output}
            continue
        events.append(event)

    return {
        "output": output,
        "events": events,
        "result": result,
    }
