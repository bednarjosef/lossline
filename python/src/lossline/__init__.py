"""lossline: a serverless experiment tracker.

Runs are plain files (``meta.json`` + JSONL metric segments) in a Hugging Face
Storage Bucket or a local directory. See ``docs/format.md`` for the layout.
"""

from __future__ import annotations

from typing import Any

from .logger import Run, current, finish, init, log
from .reader import Reader, run_status

__version__ = "0.2.0"
__all__ = ["Reader", "Run", "current", "finish", "init", "log", "run_status"]


def __getattr__(name: str) -> Any:
    if name == "run":  # like wandb.run: the current run or None
        return current()
    raise AttributeError(f"module 'lossline' has no attribute {name!r}")
