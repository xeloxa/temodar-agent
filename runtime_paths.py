from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


CANONICAL_RUNTIME_ROOT = Path("/home/appuser/.temodar-agent")


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    db_file: Path
    logs_dir: Path
    plugins_dir: Path
    semgrep_dir: Path
    semgrep_outputs_dir: Path
    approvals_dir: Path


@lru_cache(maxsize=1)
def resolve_runtime_paths() -> RuntimePaths:
    root = CANONICAL_RUNTIME_ROOT
    return RuntimePaths(
        root=root,
        db_file=root / "temodar_agent.db",
        logs_dir=root / "logs",
        plugins_dir=root / "plugins",
        semgrep_dir=root / "semgrep",
        semgrep_outputs_dir=root / "semgrep-results",
        approvals_dir=root / "approvals",
    )
