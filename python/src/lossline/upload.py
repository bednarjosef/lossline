"""Mirroring a local run folder to a Hugging Face bucket.

The Hugging Face calls run in a child process (see ``_upload_worker``) with a deadline per
call, so a hung upload is killed and retried instead of blocking the run's uploads forever.
"""

from __future__ import annotations

import contextlib
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from . import _upload_worker as wire
from .writer import RunFiles, segment_name

MIN_BACKOFF = 5.0
MAX_BACKOFF = 300.0
WARN_EVERY = 300.0  # seconds between repeated failure warnings
UPLOAD_TIMEOUT = 60.0  # seconds one upload call may take before its worker is killed
_OFF = {"0", "false", "no", "off"}

_progress_lock = threading.Lock()


@contextlib.contextmanager
def quiet_progress_bars() -> Iterator[None]:
    """Hide huggingface_hub's upload progress bars (they are global, so restore after)."""
    from huggingface_hub.utils import (
        are_progress_bars_disabled,
        disable_progress_bars,
        enable_progress_bars,
    )

    with _progress_lock:
        was_disabled = are_progress_bars_disabled()
        if not was_disabled:
            disable_progress_bars()
        try:
            yield
        finally:
            if not was_disabled:
                enable_progress_bars()


def reset_xet_session() -> None:
    """Start a fresh hf_xet session for the next upload.

    huggingface_hub shares one hf_xet session per process, and a failed upload leaves its
    error in it: every later upload fails with "Previous task error", even through a new
    HfApi. Dropping the session (without aborting it, so another thread's in-flight
    upload is untouched) makes the next call create a clean one.
    """
    try:
        from huggingface_hub.utils import _xet

        holder = _xet._GLOBAL_XET_HOLDER
        with holder._lock:
            holder._session = None
    except Exception:
        pass


def retry_after(exc: BaseException) -> float | None:
    """Seconds the server asked us to wait, from Retry-After or the RateLimit header."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    if value:
        with contextlib.suppress(ValueError):
            return float(value)
    match = re.search(r"\bt=(\d+)", headers.get("ratelimit") or "")
    if match and getattr(response, "status_code", None) == 429:
        return float(match.group(1))
    return None


def describe(exc: BaseException) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    name = getattr(exc, "remote_type", None) or type(exc).__name__
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else name
    return f"HTTP {status}: {text}" if status else f"{name}: {text}"


def ensure_bucket(api: Any, bucket_id: str) -> bool:
    """Create the bucket if it is missing. True if it was created."""
    from huggingface_hub.errors import HfHubHTTPError

    try:
        api.bucket_info(bucket_id)
        return False
    except HfHubHTTPError as exc:
        if getattr(exc.response, "status_code", None) != 404:
            return False
    api.create_bucket(bucket_id, private=True, exist_ok=True)
    return True


class UploadTimeout(Exception):
    """An upload call got no answer within its deadline; its worker was killed."""


class RemoteError(Exception):
    """An exception raised in the upload worker, with the HTTP status and rate-limit headers."""

    def __init__(self, remote_type: str, message: str, status: int | None, headers: dict[str, str]):
        super().__init__(message)
        self.remote_type = remote_type
        self.response = SimpleNamespace(status_code=status, headers=headers) if status or headers else None


def worker_command() -> list[str]:
    """How to start an upload worker (tests replace this with fake workers)."""
    return [sys.executable, "-m", "lossline._upload_worker"]


class WorkerTransport:
    """Runs upload calls in a child process that is killed when a call misses its deadline.

    One persistent worker (started on first use, restarted after a kill or crash). A
    reader thread turns the worker's replies into a queue so waits can time out on every
    platform. ``kill()`` may be called from another thread to abort the call in flight.
    """

    def __init__(self, token: str | None = None, cmd: list[str] | None = None) -> None:
        self.cmd = cmd  # None: worker_command(), looked up on every (re)start
        self.env = dict(os.environ)
        if token:
            self.env["HF_TOKEN"] = token
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._replies: queue.Queue[Any] | None = None

    def _start(self) -> tuple[subprocess.Popen[bytes], queue.Queue[Any]]:
        proc = subprocess.Popen(self.cmd or worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                env=self.env)
        replies: queue.Queue[Any] = queue.Queue()

        def pump() -> None:
            assert proc.stdout is not None
            try:
                while (message := wire.recv(proc.stdout)) is not None:
                    replies.put(message)
            except Exception:
                pass
            replies.put(None)  # end of stream: the worker exited or was killed

        threading.Thread(target=pump, name="lossline-upload-reader", daemon=True).start()
        return proc, replies

    def call(self, request: tuple[Any, ...], timeout: float) -> Any:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._proc, self._replies = self._start()
            proc, replies = self._proc, self._replies
        assert replies is not None and proc.stdin is not None
        try:
            wire.send(proc.stdin, request)
        except OSError as exc:
            self.kill(proc)
            raise ConnectionError(f"upload worker is gone ({exc})") from None
        try:
            reply = replies.get(timeout=timeout)
        except queue.Empty:
            self.kill(proc)
            raise UploadTimeout(f"no response within {timeout:.0f}s; upload worker restarted") from None
        if reply is None:
            self.kill(proc)
            raise ConnectionError("upload worker exited (aborted or crashed)")
        if reply[0] == "ok":
            return reply[1]
        _, remote_type, message, status, headers = reply
        raise RemoteError(remote_type, message, status, headers)

    def kill(self, proc: subprocess.Popen[bytes] | None = None) -> None:
        """Kill the worker (the given one, or the current one), aborting any call in flight."""
        with self._lock:
            target = proc or self._proc
            if target is None:
                return
            if target is self._proc:
                self._proc = None
        with contextlib.suppress(Exception):
            target.kill()
            target.wait(timeout=5)


@dataclass
class Batch:
    add: list[tuple[bytes, str]] = field(default_factory=list)  # (data, remote path)
    sizes: dict[int, int] = field(default_factory=dict)  # segment index -> bytes included


class BucketSync:
    """Uploads meta.json plus every segment with unconfirmed bytes, in one batch call.

    Tracks how many bytes of each segment the bucket is known to have, so a sealed
    segment stops being uploaded once it has landed, and nothing is lost when an
    upload fails: the next attempt simply includes it again.
    """

    def __init__(self, bucket_id: str, files: RunFiles, token: str | None = None,
                 timeout: float | None = None, transport: WorkerTransport | None = None) -> None:
        self.bucket_id = bucket_id
        self.files = files
        self.token = token
        self.timeout = float(timeout or os.environ.get("LOSSLINE_UPLOAD_TIMEOUT") or UPLOAD_TIMEOUT)
        self.confirmed: list[int] = []  # confirmed bytes per segment
        self.failures = 0
        self.next_attempt = 0.0
        self.in_flight_since: float | None = None  # monotonic start of the call in progress
        self._aborted = False
        self._last_warning = float("-inf")
        self._checked_bucket = False
        # In-process HfApi: used when the worker is disabled (LOSSLINE_UPLOAD_WORKER=0) or
        # cannot start, and injected by tests. Otherwise calls go through the worker.
        self._api: Any = None
        self._transport = transport
        if transport is None and os.environ.get("LOSSLINE_UPLOAD_WORKER", "1").strip().lower() not in _OFF:
            self._transport = WorkerTransport(token)

    def _call(self, request: tuple[Any, ...], timeout: float | None = None) -> Any:
        if self._api is None and self._transport is not None:
            try:
                return self._transport.call(request, timeout or self.timeout)
            except OSError as exc:
                if not isinstance(exc, ConnectionError):  # the worker could not even start
                    print(f"lossline: upload worker unavailable ({exc}); uploading in-process "
                          "without a timeout", file=sys.stderr)
                    self._transport = None
                else:
                    raise
        if self._api is None:
            from huggingface_hub import HfApi

            self._api = HfApi(token=self.token)
        if request[0] == "ensure":
            return ensure_bucket(self._api, request[1])
        with quiet_progress_bars():
            return self._api.batch_bucket_files(request[1], add=request[2])

    def abort(self) -> None:
        """Kill the upload in flight, if any (used by finish() so it need not wait for it)."""
        self._aborted = True
        if self._transport is not None:
            self._transport.kill()

    def close(self) -> None:
        self.abort()

    def pending_segments(self) -> list[int]:
        confirmed = self.confirmed + [0] * (self.files.segments - len(self.confirmed))
        return [i for i, size in enumerate(self.files.segment_sizes) if size > confirmed[i]]

    def due(self) -> bool:
        """False while backing off after a failure."""
        return time.monotonic() >= self.next_attempt

    def prepare(self, meta: bytes) -> Batch:
        """Snapshot what to upload. Call while the files are not being written."""
        batch = Batch()
        for index in self.pending_segments():
            data = self.files.read_segment(index)
            batch.sizes[index] = len(data)
            batch.add.append((data, f"{self.files.prefix}/{segment_name(index)}"))
        batch.add.append((meta, f"{self.files.prefix}/meta.json"))
        return batch

    def push(self, batch: Batch, timeout: float | None = None) -> bool:
        """Upload a prepared batch in one call; returns True on success. Never raises."""
        request = ("batch", self.bucket_id, batch.add)
        self.in_flight_since = time.monotonic()
        try:
            try:
                self._call(request, timeout)
            except UploadTimeout:
                raise
            except Exception:
                reset_xet_session()
                if not self._ensure_bucket():
                    raise
                self._call(request, timeout)
        except Exception as exc:
            reset_xet_session()
            self._failed(exc)
            return False
        finally:
            self.in_flight_since = None
        self.confirmed += [0] * (len(self.files.segment_sizes) - len(self.confirmed))
        for index, size in batch.sizes.items():
            self.confirmed[index] = max(self.confirmed[index], size)
        if self.failures:
            print(f"lossline: upload to {self.bucket_id} recovered", file=sys.stderr)
        self.failures = 0
        self.next_attempt = 0.0
        return True

    def _ensure_bucket(self) -> bool:
        """On the first failure, create the bucket if it is missing. True if created."""
        if self._checked_bucket:
            return False
        self._checked_bucket = True
        try:
            if not self._call(("ensure", self.bucket_id)):
                return False
        except Exception:
            return False
        print(f"lossline: created private bucket {self.bucket_id}", file=sys.stderr)
        return True

    def _failed(self, exc: BaseException) -> None:
        if self._aborted:  # killed on purpose by finish(); the final upload follows
            self._aborted = False
            return
        self.failures += 1
        delay = min(MIN_BACKOFF * 2 ** (self.failures - 1), MAX_BACKOFF)
        wait = retry_after(exc)
        if wait is not None:
            delay = max(delay, min(wait, 2 * MAX_BACKOFF))
        self.next_attempt = time.monotonic() + delay
        now = time.monotonic()
        if now - self._last_warning >= WARN_EVERY:
            self._last_warning = now
            print(
                f"lossline: upload to {self.bucket_id} failed ({describe(exc)}); "
                f"retrying in {delay:.0f}s, data is safe in {self.files.dir}",
                file=sys.stderr,
            )
