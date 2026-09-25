"""Reading runs back: projects, run metadata and metric history."""

from __future__ import annotations

import fnmatch
import json
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .defaults import OFF, default_bucket
from .source import BucketSource, LocalSource, Source, SourceError, _parse_time
from .writer import segment_name

Point = tuple[int, "float | None"]


def run_status(meta: dict[str, Any], now: float | None = None) -> str:
    """``running``/``finished``/``failed``, or ``stalled`` for a running run whose
    heartbeat is older than ``3 * flush_interval + 60`` seconds."""
    status = str(meta.get("status") or "running")
    if status != "running":
        return status
    now = time.time() if now is None else now
    heartbeat = _parse_time(meta.get("heartbeat") or meta.get("created"))
    interval = float(meta.get("flush_interval") or 15)
    return "stalled" if now - heartbeat > 3 * interval + 60 else "running"


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    runs: int
    last_activity: float  # unix seconds


class Reader:
    """Read runs from a bucket (``bucket="owner/name"``) or a local directory (``dir=``).

    With neither given, uses ``LOSSLINE_BUCKET``, then ``LOSSLINE_DIR``, then the user's
    default bucket ``<hf user>/lossline`` when logged in to Hugging Face, then ``./lossline``.
    """

    def __init__(
        self,
        bucket: str | None = None,
        dir: str | os.PathLike[str] | None = None,
        token: str | None = None,
    ) -> None:
        self.source: Source
        env_bucket = os.environ.get("LOSSLINE_BUCKET", "").strip()
        if dir is not None:
            self.source = LocalSource(dir)
        elif bucket or (env_bucket and env_bucket.lower() not in OFF):
            self.source = BucketSource(bucket or env_bucket, token=token)
        elif os.environ.get("LOSSLINE_DIR"):
            self.source = LocalSource(os.environ["LOSSLINE_DIR"])
        elif not env_bucket and (default := default_bucket()):
            self.source = BucketSource(default, token=token)
        else:
            self.source = LocalSource("lossline")

    # -- listing -------------------------------------------------------------

    def projects(self) -> list[ProjectInfo]:
        """Projects with their run counts and last activity, most recent first."""
        runs: dict[str, set[str]] = {}
        last: dict[str, float] = {}
        for entry in self.source.list("", recursive=True):
            parts = entry.path.split("/")
            if len(parts) < 3:
                continue
            project = parts[0]
            last[project] = max(last.get(project, 0.0), entry.mtime)
            if len(parts) == 3 and parts[2] == "meta.json":
                runs.setdefault(project, set()).add(parts[1])
        infos = [ProjectInfo(p, len(r), last.get(p, 0.0)) for p, r in runs.items()]
        return sorted(infos, key=lambda i: -i.last_activity)

    def run_ids(self, project: str) -> list[str]:
        return [e.path.split("/")[1] for e in self.source.list(project) if e.is_dir]

    def runs(self, project: str) -> list[dict[str, Any]]:
        """meta.json of every run in ``project``, newest first."""
        ids = self.run_ids(project)
        with ThreadPoolExecutor(max_workers=8) as pool:
            metas = list(pool.map(lambda r: self._try_meta(project, r), ids))
        found = [m for m in metas if m is not None]
        return sorted(found, key=lambda m: m.get("created") or "", reverse=True)

    def _try_meta(self, project: str, run: str) -> dict[str, Any] | None:
        try:
            return self.meta(project, run)
        except (FileNotFoundError, ValueError):
            return None

    def meta(self, project: str, run: str) -> dict[str, Any]:
        return json.loads(self.source.read(f"{project}/{run}/meta.json"))

    def resolve(self, project: str, run: str) -> str:
        """Accept a unique prefix of a run id (e.g. the run name) and return the full id."""
        try:
            self.source.read(f"{project}/{run}/meta.json", 0)
            return run
        except FileNotFoundError:
            pass
        ids = self.run_ids(project)
        matches = [r for r in ids if r.startswith(run)] or [
            r for r in ids if fnmatch.fnmatch(r, run)
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise SourceError(f"no run {run!r} in project {project!r}")
        raise SourceError(f"{run!r} is ambiguous: {', '.join(sorted(matches)[:10])}")

    # -- metrics -------------------------------------------------------------

    def rows(
        self, project: str, run: str, meta: dict[str, Any] | None = None, start_segment: int = 0
    ) -> Iterator[dict[str, Any]]:
        """Every logged row, in order. Skips missing segments and a partial last line."""
        meta = meta or self.meta(project, run)
        for index in range(start_segment, int(meta.get("segments") or 0)):
            try:
                data = self.source.read(f"{project}/{run}/{segment_name(index)}")
            except FileNotFoundError:
                continue
            yield from parse_lines(data)[0]

    def history(self, project: str, run: str) -> list[dict[str, Any]]:
        return list(self.rows(project, run))

    def metrics(self, project: str, run: str) -> dict[str, list[Point]]:
        """``{metric: [(step, value), ...]}``; value is ``None`` where it was non-finite."""
        return rows_to_metrics(self.rows(project, run))

    def follow(
        self, project: str, run: str, poll: float = 5.0, segment: int = 0, offset: int = 0
    ) -> Iterator[dict[str, Any]]:
        """Yield rows appended after byte ``offset`` of ``segment``, polling every ``poll``
        seconds; stops once the run is no longer running.

        Only new bytes of the last segment are fetched (an HTTP Range request on buckets).
        """
        pending = b""
        ended = False
        while True:
            try:
                data = self.source.read(f"{project}/{run}/{segment_name(segment)}", offset)
            except FileNotFoundError:
                data = b""
            offset += len(data)
            rows, pending = parse_lines(pending + data)
            yield from rows
            if data:
                time.sleep(poll)
                continue
            if ended:
                return
            meta = self.meta(project, run)
            if int(meta.get("segments") or 0) > segment + 1:
                segment, offset, pending = segment + 1, 0, b""
            elif run_status(meta) != "running":
                ended = True  # one more read: the final flush may have landed meanwhile
            else:
                time.sleep(poll)


def parse_lines(data: bytes) -> tuple[list[dict[str, Any]], bytes]:
    """Parse complete lines; return the rows and the unterminated tail."""
    body, sep, tail = data.rpartition(b"\n")
    if not sep:
        return [], data
    rows = []
    for line in body.split(b"\n"):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows, tail


def rows_to_metrics(rows: Iterator[dict[str, Any]] | list[dict[str, Any]]) -> dict[str, list[Point]]:
    out: dict[str, list[Point]] = {}
    for row in rows:
        step = row.get("_step", 0)
        for key, value in row.items():
            if key not in ("_step", "_time"):
                out.setdefault(key, []).append((step, value))
    return out
