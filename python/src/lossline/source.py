"""Access to where runs live: a local directory or a Hugging Face bucket."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

def _user_agent() -> str:
    try:
        from importlib.metadata import version

        return f"lossline/{version('lossline')}"
    except Exception:
        return "lossline"


USER_AGENT = _user_agent()


class SourceError(Exception):
    """A storage problem worth showing to the user as one line."""


@dataclass(frozen=True)
class Entry:
    path: str  # relative to the source root, "/"-separated
    is_dir: bool
    size: int
    mtime: float  # unix seconds; for directories the newest activity inside


class Source(Protocol):
    label: str

    def list(self, prefix: str = "", recursive: bool = False) -> list[Entry]:
        """Entries under directory ``prefix`` ("" for the root)."""
        ...

    def read(self, path: str, start: int = 0) -> bytes:
        """Bytes of ``path`` from offset ``start``; b"" if there are none yet.

        Raises FileNotFoundError if the file does not exist.
        """
        ...

    def apply(self, add: dict[str, bytes], delete: list[str]) -> None:
        """Write ``add`` (path -> bytes) and remove ``delete`` in one operation."""
        ...


class LocalSource:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.label = str(self.root)

    def list(self, prefix: str = "", recursive: bool = False) -> list[Entry]:
        base = self.root / prefix if prefix else self.root
        if not base.is_dir():
            return []
        entries: list[Entry] = []
        for child in sorted(base.iterdir()):
            rel = child.relative_to(self.root).as_posix()
            if child.is_dir():
                files = [p for p in child.rglob("*") if p.is_file()]
                newest = max((p.stat().st_mtime for p in files), default=child.stat().st_mtime)
                if recursive:
                    entries += [self._file_entry(p) for p in sorted(files) if _visible(p)]
                else:
                    entries.append(Entry(rel, True, 0, newest))
            elif _visible(child):
                entries.append(self._file_entry(child))
        return entries

    def _file_entry(self, path: Path) -> Entry:
        st = path.stat()
        return Entry(path.relative_to(self.root).as_posix(), False, st.st_size, st.st_mtime)

    def read(self, path: str, start: int = 0) -> bytes:
        with open(self.root / path, "rb") as f:
            f.seek(start)
            return f.read()

    def apply(self, add: dict[str, bytes], delete: list[str]) -> None:
        for path, data in add.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for path in delete:
            (self.root / path).unlink(missing_ok=True)
        # drop directories the deletes emptied (run folders, then empty projects)
        for path in delete:
            parent = (self.root / path).parent
            while parent != self.root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent


def _visible(path: Path) -> bool:
    return not path.name.endswith(".tmp")


class BucketSource:
    """Reads a bucket over plain HTTP: the tree API and the resolve endpoint."""

    def __init__(self, bucket_id: str, token: str | None = None, endpoint: str | None = None):
        if bucket_id.count("/") != 1:
            raise SourceError(f"bucket must look like 'owner/name', got {bucket_id!r}")
        self.bucket_id = bucket_id
        self.label = f"hf://buckets/{bucket_id}"
        if token is None or endpoint is None:
            from huggingface_hub import constants, get_token

            token = token if token is not None else get_token()
            endpoint = endpoint or constants.ENDPOINT
        self.token = token
        self.endpoint = endpoint.rstrip("/")

    def list(self, prefix: str = "", recursive: bool = False) -> list[Entry]:
        prefix = prefix.strip("/")
        path = f"/tree/{urllib.parse.quote(prefix)}" if prefix else "/tree"
        url: str | None = (
            f"{self.endpoint}/api/buckets/{self.bucket_id}{path}?recursive={str(recursive).lower()}"
        )
        entries: list[Entry] = []
        while url:
            body, headers = self._get(url)
            for item in json.loads(body):
                # The tree prefix is a string prefix ("seq" matches "seqmem/..."), so filter.
                if prefix and not item["path"].startswith(prefix + "/"):
                    continue
                entries.append(Entry(
                    path=item["path"],
                    is_dir=item.get("type") == "directory",
                    size=int(item.get("size") or 0),
                    mtime=_parse_time(item.get("uploadedAt") or item.get("mtime")),
                ))
            url = _next_link(headers.get("link"))
        return entries

    def read(self, path: str, start: int = 0) -> bytes:
        url = f"{self.endpoint}/buckets/{self.bucket_id}/resolve/{urllib.parse.quote(path)}"
        headers = {"Range": f"bytes={start}-"} if start > 0 else {}
        try:
            body, _ = self._get(url, headers)
        except urllib.error.HTTPError as exc:
            if exc.code == 416:  # nothing past `start` yet
                return b""
            raise
        return body

    def apply(self, add: dict[str, bytes], delete: list[str]) -> None:
        from huggingface_hub import HfApi

        from .upload import reset_xet_session

        api = HfApi(token=self.token, endpoint=self.endpoint)
        try:
            api.batch_bucket_files(self.bucket_id, add=[(data, path) for path, data in add.items()],
                                   delete=delete)
        except Exception as exc:
            reset_xet_session()
            raise SourceError(f"could not update {self.label}: {exc}") from exc

    def _get(self, url: str, extra: dict[str, str] | None = None) -> tuple[bytes, dict[str, str]]:
        headers = {"User-Agent": USER_AGENT, **(extra or {})}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                    return r.read(), {k.lower(): v for k, v in r.headers.items()}
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise FileNotFoundError(url) from None
                if exc.code in (401, 403):
                    raise SourceError(
                        f"HTTP {exc.code} for {self.label}: no access (is your HF token set?)"
                    ) from None
                wait = _wait_seconds(exc)
                if exc.code == 429 or exc.code >= 500:
                    if attempt < 2 and wait <= 15:
                        time.sleep(wait)
                        continue
                    if exc.code == 429:
                        raise SourceError(
                            f"rate limited by the Hub; try again in {wait:.0f}s"
                        ) from None
                raise
            except urllib.error.URLError as exc:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                raise SourceError(f"cannot reach {self.endpoint}: {exc.reason}") from None
        raise AssertionError("unreachable")


def _wait_seconds(exc: urllib.error.HTTPError) -> float:
    value = exc.headers.get("retry-after") if exc.headers else None
    if value and value.replace(".", "", 1).isdigit():
        return float(value)
    match = re.search(r"\bt=(\d+)", (exc.headers.get("ratelimit") if exc.headers else "") or "")
    return float(match.group(1)) if match else 2.0


def _next_link(link: str | None) -> str | None:
    if not link:
        return None
    match = re.search(r'<([^>]+)>\s*;\s*rel="?next"?', link)
    return match.group(1) if match else None


def _parse_time(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
