from __future__ import annotations

import subprocess
import sys
from functools import lru_cache
from typing import List, Optional, Sequence


def _is_working_semgrep_command(command: Sequence[str]) -> bool:
    try:
        result = subprocess.run(
            [*command, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


@lru_cache(maxsize=1)
def get_semgrep_command() -> Optional[List[str]]:
    candidates = [
        ["semgrep"],
        [sys.executable, "-m", "semgrep"],
    ]

    for candidate in candidates:
        if _is_working_semgrep_command(candidate):
            return list(candidate)

    return None


def is_semgrep_available() -> bool:
    return get_semgrep_command() is not None


def semgrep_install_hint() -> str:
    return (
        "Install dependencies with `pip install -r requirements.txt` "
        "to include Semgrep."
    )
