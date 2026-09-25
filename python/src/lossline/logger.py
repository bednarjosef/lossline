"""The logger: ``init`` / ``log`` / ``finish`` and the background flush thread."""

from __future__ import annotations

import atexit
import os
import signal
import sys
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any

from . import names, sysinfo
from .defaults import resolve_bucket
from .upload import BucketSync
from .values import NOT_A_NUMBER, Warner, config_to_dict, flatten, to_number
from .writer import RunFiles

FORMAT_VERSION = 1
DEFAULT_FLUSH_INTERVAL = 30.0
FINAL_UPLOAD_TIMEOUT = 60.0
ABORT_AFTER = 5.0  # on finish(), an upload already running this long is killed and redone
RESERVED_KEYS = ("_step", "_time")


def utc_now() -> str:
    """ISO 8601 UTC with milliseconds and a ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Run:
    """One experiment run. Create it with :func:`lossline.init`."""

    def __init__(
        self,
        project: str | None = None,
        name: str | None = None,
        config: Any = None,
        bucket: str | bool | None = None,
        dir: str | os.PathLike[str] | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        flush_interval: float | None = None,
    ) -> None:
        project = project or os.environ.get("LOSSLINE_PROJECT") or "default"
        self.project = names.slugify(project)
        if not self.project:
            raise ValueError(f"invalid project name {project!r}")
        self.name = name or names.random_name()
        self.id = names.make_run_id(self.name)
        self.config = config_to_dict(config)
        self.tags = [str(t) for t in tags or []]
        self.notes = notes or ""
        self.bucket = resolve_bucket(bucket)
        self.dir = Path(dir or os.environ.get("LOSSLINE_DIR") or "lossline").resolve()
        if flush_interval is None:
            flush_interval = float(
                os.environ.get("LOSSLINE_FLUSH_INTERVAL") or DEFAULT_FLUSH_INTERVAL
            )
        self.flush_interval = float(flush_interval)
        self.summary: dict[str, Any] = {}

        self.status = "running"
        self._created = utc_now()
        self._ended: str | None = None
        self._system = sysinfo.system_info()
        self._git = sysinfo.git_info()
        self._pid = os.getpid()

        self._buffer: list[dict[str, Any]] = []
        self._next_step = 0
        self._last_step: int | None = None
        # Re-entrant: a SIGTERM handler may call finish() while log() holds the lock.
        self._lock = threading.RLock()
        self._flush_lock = threading.RLock()
        self._finished = False
        self._warn = Warner()

        self._files = RunFiles(self.dir, self.project, self.id)
        self._sync = BucketSync(self.bucket, self._files) if self.bucket else None
        self._meta_bytes = self._files.write_meta(self._meta(dict(self.summary)))

        # Two daemon threads: one writes local files every flush_interval, the other
        # uploads after each local flush, so a slow network never delays local writes.
        self._stop = threading.Event()
        self._flushed = threading.Event()
        self._final_deadline: float | None = None
        self._threads = [threading.Thread(target=self._flush_loop, name="lossline-flush",
                                          daemon=True)]
        if self._sync is not None:
            self._threads.append(threading.Thread(target=self._upload_loop,
                                                  name="lossline-upload", daemon=True))
        for thread in self._threads:
            thread.start()

        where = f"{self.bucket}/{self._files.prefix}" if self.bucket else "local only"
        print(f"lossline: run {self.project}/{self.id} ({where}, {self._files.dir})",
              file=sys.stderr)

    # -- public API ---------------------------------------------------------

    def log(self, data: Mapping[str, Any], step: int | None = None) -> None:
        """Record metrics. Cheap: only appends to an in-memory buffer."""
        if self._finished:
            self._warn.once("finished", f"run {self.id} is finished; ignoring log()")
            return
        if not isinstance(data, Mapping):
            self._warn.once("type", f"log() expects a dict, got {type(data).__name__}")
            return
        metrics: dict[str, Any] = {}
        for key, value in flatten(data).items():
            if key in RESERVED_KEYS:
                self._warn.once(f"key:{key}", f"{key!r} is reserved; use the step argument")
                continue
            number = to_number(value)
            if number is NOT_A_NUMBER:
                self._warn.once(
                    f"key:{key}", f"skipping non-numeric metric {key!r} ({type(value).__name__})"
                )
                continue
            metrics[key] = number
        if not metrics:
            return
        with self._lock:
            if step is None:
                step = self._next_step
            else:
                step = int(step)
                if self._last_step is not None and step < self._last_step:
                    self._warn.once(
                        "step", f"step went backwards ({step} < {self._last_step}); dropping row"
                    )
                    return
            self._buffer.append({"_step": step, "_time": round(time.time(), 3), **metrics})
            self._last_step = step
            self._next_step = step + 1
            self.summary.update(metrics)

    def finish(self, status: str = "finished", timeout: float = FINAL_UPLOAD_TIMEOUT) -> None:
        """Flush everything, mark the run ``finished`` or ``failed`` and upload."""
        if status not in ("finished", "failed"):
            raise ValueError("status must be 'finished' or 'failed'")
        with self._lock:
            if self._finished or os.getpid() != self._pid:
                return
            self._finished = True
            self.status = status
            self._ended = utc_now()
        deadline = time.monotonic() + timeout
        self._final_deadline = deadline
        # Local files first: they are complete before any network wait.
        try:
            self._flush_local()
        finally:
            self._stop.set()  # the upload thread does one last upload and exits
            self._flushed.set()
        # Don't queue the final upload behind a slow or hung one: kill it; the final upload
        # includes everything it carried.
        started = self._sync.in_flight_since if self._sync is not None else None
        if started is not None and time.monotonic() - started > ABORT_AFTER:
            self._sync.abort()
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self._threads):
            print(f"lossline: final upload did not finish within {timeout:.0f}s; the run is "
                  f"complete in {self._files.dir} (upload it later with: lossline push "
                  f"{self._files.dir})", file=sys.stderr)
        if self._sync is not None:
            self._sync.close()
        _forget(self)

    @property
    def local_dir(self) -> Path:
        return self._files.dir

    def __enter__(self) -> Run:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.finish("failed" if exc_type else "finished")

    def __repr__(self) -> str:
        return f"<lossline.Run {self.project}/{self.id} {self.status}>"

    # -- internals ----------------------------------------------------------

    def _meta(self, summary: dict[str, Any]) -> dict[str, Any]:
        if self._last_step is not None:
            summary["_step"] = self._last_step
        return {
            "format": FORMAT_VERSION,
            "project": self.project,
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "created": self._created,
            "heartbeat": utc_now(),
            "ended": self._ended,
            "flush_interval": self.flush_interval,
            "config": self.config,
            "summary": summary,
            "system": self._system,
            "git": self._git,
            "tags": self.tags,
            "notes": self.notes,
            "segments": self._files.segments,
            "rows": self._files.rows,
        }

    def _flush_local(self) -> None:
        """Append buffered rows to the active segment and rewrite meta.json."""
        with self._flush_lock:
            with self._lock:
                rows, self._buffer = self._buffer, []
                summary = dict(self.summary)
            self._files.append(rows)
            with self._lock:
                meta = self._meta(summary)
            self._meta_bytes = self._files.write_meta(meta)

    def _upload(self) -> None:
        assert self._sync is not None
        with self._flush_lock:  # a consistent snapshot of segments + meta
            batch = self._sync.prepare(self._meta_bytes)
        timeout = None
        if self._final_deadline is not None:  # the final upload gets what is left of finish()'s budget
            timeout = max(1.0, self._final_deadline - time.monotonic())
        self._sync.push(batch, timeout)  # slow; local flushes may continue meanwhile

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            self._guard(self._flush_local)
            self._flushed.set()
            self._stop.wait(self.flush_interval)

    def _upload_loop(self) -> None:
        """Upload after each local flush unless backing off. Once finish() has set the
        stop event, do a final upload (with the final status) and exit."""
        assert self._sync is not None
        while True:
            self._flushed.wait()
            self._flushed.clear()
            stopping = self._stop.is_set()
            if stopping or self._sync.due():
                self._guard(self._upload)
            if stopping:
                return

    def _guard(self, step: Any) -> None:
        try:
            step()
        except Exception as exc:  # never let the thread die
            self._warn.once(f"{step.__name__}", f"{step.__name__.strip('_')} failed: {exc!r}")


# -- module-level current run -----------------------------------------------

_current: Run | None = None
_crashed = False
_hooks_installed = False
_prev_excepthook = sys.excepthook
_prev_sigterm: Any = None


def init(
    project: str | None = None,
    name: str | None = None,
    config: Any = None,
    bucket: str | bool | None = None,
    dir: str | os.PathLike[str] | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
    flush_interval: float | None = None,
) -> Run:
    """Start a run and make it current. Finishes the previous current run, if any.

    Runs go to ``bucket``, else ``$LOSSLINE_BUCKET``, else ``<your hf user>/lossline``
    when logged in to Hugging Face (created on first upload). ``bucket=False`` or
    ``LOSSLINE_BUCKET=none`` keeps files local only.
    """
    global _current
    if _current is not None:
        _current.finish()
    run = Run(project, name, config, bucket, dir, tags, notes, flush_interval)
    _current = run
    _install_hooks()
    return run


def log(data: Mapping[str, Any], step: int | None = None) -> None:
    if _current is None:
        raise RuntimeError("no active run; call lossline.init() first")
    _current.log(data, step=step)


def finish(status: str = "finished") -> None:
    if _current is not None:
        _current.finish(status)


def current() -> Run | None:
    return _current


def _forget(run: Run) -> None:
    global _current
    if _current is run:
        _current = None


def _install_hooks() -> None:
    global _hooks_installed, _prev_excepthook, _prev_sigterm
    if _hooks_installed:
        return
    _hooks_installed = True
    atexit.register(_at_exit)
    _prev_excepthook = sys.excepthook
    sys.excepthook = _excepthook
    if threading.current_thread() is threading.main_thread():
        try:
            previous = signal.getsignal(signal.SIGTERM)
            if previous is not signal.SIG_IGN:
                _prev_sigterm = previous
                signal.signal(signal.SIGTERM, _on_sigterm)
        except (ValueError, OSError):
            pass


def _excepthook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    global _crashed
    _crashed = True
    _prev_excepthook(exc_type, exc, tb)


def _at_exit() -> None:
    if _current is not None:
        _current.finish("failed" if _crashed else "finished")


def _on_sigterm(signum: int, frame: Any) -> None:
    if _current is not None:
        _current.finish("failed")
    if callable(_prev_sigterm):
        _prev_sigterm(signum, frame)
        return
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
