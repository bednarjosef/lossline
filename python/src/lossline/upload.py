"""Mirroring a local run folder to a Hugging Face bucket."""

from __future__ import annotations

import contextlib
import re
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .writer import RunFiles, segment_name

MIN_BACKOFF = 5.0
MAX_BACKOFF = 300.0
WARN_EVERY = 300.0  # seconds between repeated failure warnings

_progress_lock = threading.Lock()


@contextlib.contextmanager
def _quiet_progress_bars() -> Iterator[None]:
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
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return f"HTTP {status}: {text}" if status else f"{type(exc).__name__}: {text}"


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

    def __init__(self, bucket_id: str, files: RunFiles, token: str | None = None) -> None:
        self.bucket_id = bucket_id
        self.files = files
        self.token = token
        self.confirmed: list[int] = []  # confirmed bytes per segment
        self.failures = 0
        self.next_attempt = 0.0
        self._last_warning = float("-inf")
        self._checked_bucket = False
        self._api: Any = None  # huggingface_hub.HfApi, created on first use

    def _batch(self, add: list[tuple[bytes, str]]) -> None:
        if self._api is None:
            from huggingface_hub import HfApi

            self._api = HfApi(token=self.token)
        with _quiet_progress_bars():
            self._api.batch_bucket_files(self.bucket_id, add=add)

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

    def push(self, batch: Batch) -> bool:
        """Upload a prepared batch in one call; returns True on success. Never raises."""
        try:
            try:
                self._batch(batch.add)
            except Exception:
                reset_xet_session()
                if not self._ensure_bucket():
                    raise
                self._batch(batch.add)
        except Exception as exc:
            reset_xet_session()
            self._failed(exc)
            return False
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
            from huggingface_hub.errors import HfHubHTTPError

            assert self._api is not None
            try:
                self._api.bucket_info(self.bucket_id)
                return False
            except HfHubHTTPError as exc:
                if getattr(exc.response, "status_code", None) != 404:
                    return False
            self._api.create_bucket(self.bucket_id, private=True, exist_ok=True)
        except Exception:
            return False
        print(f"lossline: created private bucket {self.bucket_id}", file=sys.stderr)
        return True

    def _failed(self, exc: BaseException) -> None:
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
