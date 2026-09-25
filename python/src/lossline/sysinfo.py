"""Cheap, best-effort facts about the machine and the code being run."""

from __future__ import annotations

import os
import platform
import socket
import subprocess
from typing import Any


def _run(cmd: list[str], timeout: float = 2.0, cwd: str | None = None) -> str | None:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, check=True,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def system_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "host": socket.gethostname(),
        "platform": f"{platform.system()}-{platform.release()}",
        "python": platform.python_version(),
    }
    gpus = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if gpus:
        names = [line.strip() for line in gpus.splitlines() if line.strip()]
        info["gpu"] = names[0]
        if len(names) > 1:
            info["gpu_count"] = len(names)
    return info


def git_info(cwd: str | None = None) -> dict[str, Any] | None:
    cwd = cwd or os.getcwd()
    commit = _run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd)
    if not commit:
        return None
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    status = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=cwd)
    return {"commit": commit, "branch": branch, "dirty": bool(status)}
