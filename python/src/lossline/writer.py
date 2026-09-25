"""The local copy of a run: append-only metric segments plus meta.json.

The local folder is the source of truth. The bucket is a mirror of it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SEGMENT_BYTES = 4 * 1024 * 1024  # a segment is sealed once it passes this size


def segment_name(index: int) -> str:
    return f"metrics/{index:06d}.jsonl"


class RunFiles:
    """Writes one run folder: ``<root>/<project>/<run>/``. Not thread-safe; one writer."""

    def __init__(self, root: Path, project: str, run_id: str) -> None:
        self.prefix = f"{project}/{run_id}"
        self.dir = Path(root) / project / run_id
        (self.dir / "metrics").mkdir(parents=True, exist_ok=True)
        self.segment_sizes: list[int] = []  # bytes written to each segment
        self.rows = 0

    @property
    def segments(self) -> int:
        return len(self.segment_sizes)

    def segment_path(self, index: int) -> Path:
        return self.dir / segment_name(index)

    def append(self, rows: list[dict[str, Any]]) -> None:
        """Append rows to the active segment, starting a new one when it gets too big."""
        chunk: list[bytes] = []
        chunk_bytes = 0
        for row in rows:
            line = (json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode()
            if not self.segment_sizes or self.segment_sizes[-1] + chunk_bytes >= SEGMENT_BYTES:
                self._write(chunk)
                chunk, chunk_bytes = [], 0
                self.segment_sizes.append(0)
            chunk.append(line)
            chunk_bytes += len(line)
        self._write(chunk)
        self.rows += len(rows)

    def _write(self, lines: list[bytes]) -> None:
        if not lines:
            return
        data = b"".join(lines)
        index = len(self.segment_sizes) - 1
        with open(self.segment_path(index), "ab") as f:
            f.write(data)
            f.flush()
        self.segment_sizes[index] += len(data)

    def read_segment(self, index: int) -> bytes:
        """The bytes of a segment as far as this writer has written them."""
        with open(self.segment_path(index), "rb") as f:
            return f.read(self.segment_sizes[index])

    def write_meta(self, meta: dict[str, Any]) -> bytes:
        """Atomically replace meta.json; returns the bytes written."""
        data = (json.dumps(meta, indent=2, allow_nan=False) + "\n").encode()
        tmp = self.dir / "meta.json.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, self.dir / "meta.json")
        return data
