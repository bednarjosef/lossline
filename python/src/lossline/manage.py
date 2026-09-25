"""Moving and deleting runs. Both work on whole run folders in one storage operation."""

from __future__ import annotations

import fnmatch
import json

from .reader import Reader, run_status
from .source import SourceError


def select_runs(reader: Reader, project: str, pattern: str) -> list[str]:
    """Run ids matching ``pattern``: a glob (``*``, ``lr-*``), ``latest``, or an id prefix."""
    if any(c in pattern for c in "*?["):
        ids = sorted(r for r in reader.run_ids(project) if fnmatch.fnmatch(r, pattern))
        if not ids:
            raise SourceError(f"no runs match {project}/{pattern}")
        return ids
    return [reader.resolve(project, pattern)]


def _files(reader: Reader, project: str, run: str) -> list[str]:
    prefix = f"{project}/{run}"
    return [e.path for e in reader.source.list(prefix, recursive=True) if not e.is_dir]


def check_not_live(reader: Reader, project: str, run: str) -> None:
    status = run_status(reader.meta(project, run))
    if status == "running":
        raise SourceError(f"{project}/{run} is still running; its logger keeps writing to "
                          "the current path. Wait for it to end (lossline wait) first")


def move_run(reader: Reader, project: str, run: str, dest: str) -> None:
    """Move a run to project ``dest``, keeping its id and updating meta.json's project."""
    if dest == project:
        raise SourceError(f"{project}/{run} is already in {dest}")
    if _files(reader, dest, run):
        raise SourceError(f"{dest}/{run} already exists")
    check_not_live(reader, project, run)
    old = _files(reader, project, run)
    add: dict[str, bytes] = {}
    for path in old:
        data = reader.source.read(path)
        if path.endswith("/meta.json"):
            meta = json.loads(data)
            meta["project"] = dest
            data = json.dumps(meta, separators=(",", ":")).encode()
        add[dest + path[len(project):]] = data
    reader.source.apply(add, delete=old)


def remove_run(reader: Reader, project: str, run: str) -> int:
    """Delete every file of a run. Returns how many files were removed."""
    check_not_live(reader, project, run)
    old = _files(reader, project, run)
    reader.source.apply({}, delete=old)
    return len(old)
