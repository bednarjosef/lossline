from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import lossline
import lossline.writer
from lossline import Reader
from lossline.names import is_slug, make_run_id, random_name, slugify
from lossline.upload import BucketSync
from lossline.writer import RunFiles

SPEC_KEYS = {
    "format", "project", "id", "name", "status", "created", "heartbeat", "ended",
    "flush_interval", "config", "summary", "system", "git", "tags", "notes", "segments", "rows",
}


def read_meta(run: lossline.Run) -> dict:
    return json.loads((run.local_dir / "meta.json").read_text())


def test_local_round_trip(tmp_path: Path):
    run = lossline.init(project="Seq Mem", name="baseline", config={"lr": 3e-4}, dir=tmp_path,
                        tags=["a"], notes="hello")
    assert run.project == "seq-mem"
    assert run.id.startswith("baseline-") and len(run.id) == len("baseline-") + 4
    assert lossline.run is run
    for step in range(5):
        lossline.log({"train": {"loss": 1.0 / (step + 1)}, "lr": 3e-4, "ok": True})
    lossline.log({"eval/acc": 0.5, "bad": float("nan")}, step=10)
    lossline.finish()
    assert lossline.run is None

    meta = read_meta(run)
    assert set(meta) == SPEC_KEYS
    assert meta["status"] == "finished" and meta["ended"].endswith("Z")
    assert meta["format"] == 1 and meta["config"] == {"lr": 3e-4}
    assert meta["rows"] == 6 and meta["segments"] == 1
    assert meta["summary"] == {"_step": 10, "train/loss": 0.2, "lr": 3e-4, "ok": 1,
                               "eval/acc": 0.5, "bad": None}
    assert meta["tags"] == ["a"] and meta["notes"] == "hello"
    assert meta["system"]["python"]

    reader = Reader(dir=tmp_path)
    rows = reader.history("seq-mem", run.id)
    assert [r["_step"] for r in rows] == [0, 1, 2, 3, 4, 10]
    assert all(isinstance(r["_time"], float) for r in rows)
    assert rows[-1] == {"_step": 10, "_time": rows[-1]["_time"], "eval/acc": 0.5, "bad": None}
    metrics = reader.metrics("seq-mem", run.id)
    assert metrics["train/loss"][:2] == [(0, 1.0), (1, 0.5)]
    assert metrics["eval/acc"] == [(10, 0.5)]
    lines = (run.local_dir / "metrics/000000.jsonl").read_text().splitlines()
    assert len(lines) == 6


def test_steps_and_skipped_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    with lossline.init(project="p", dir=tmp_path) as run:
        run.log({"a": 1}, step=5)
        run.log({"a": 2})  # auto step continues at 6
        run.log({"a": 3}, step=6)  # same step again is allowed
        run.log({"a": 4}, step=2)  # backwards: dropped
        run.log({"s": "text", "a": 5})
        run.log({"s": "again"})  # nothing numeric: no row, no step consumed
        run.log({"_step": 3, "a": 6})
    assert run.status == "finished"
    rows = Reader(dir=tmp_path).history("p", run.id)
    assert [(r["_step"], r["a"]) for r in rows] == [(5, 1), (6, 2), (6, 3), (7, 5), (8, 6)]
    err = capsys.readouterr().err
    assert err.count("non-numeric metric 's'") == 1
    assert "step went backwards" in err and "'_step' is reserved" in err


def test_context_manager_marks_failure(tmp_path: Path):
    with pytest.raises(ZeroDivisionError):
        with lossline.init(project="p", dir=tmp_path) as run:
            run.log({"x": 1})
            _ = 1 / 0
    assert read_meta(run)["status"] == "failed"


def test_init_finishes_previous_run(tmp_path: Path):
    first = lossline.init(project="p", dir=tmp_path)
    second = lossline.init(project="p", dir=tmp_path)
    assert read_meta(first)["status"] == "finished"
    assert lossline.run is second
    lossline.finish()


def test_segment_rotation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(lossline.writer, "SEGMENT_BYTES", 300)
    run = lossline.init(project="p", dir=tmp_path)
    for step in range(100):
        run.log({"train/loss": step * 0.01, "lr": 0.001})
    run.finish()
    meta = read_meta(run)
    files = sorted((run.local_dir / "metrics").iterdir())
    assert meta["segments"] == len(files) > 5
    assert [f.name for f in files] == [f"{i:06d}.jsonl" for i in range(len(files))]
    for sealed in files[:-1]:
        assert 300 <= sealed.stat().st_size < 300 + 100
    assert meta["rows"] == 100
    rows = Reader(dir=tmp_path).history("p", run.id)
    assert [r["_step"] for r in rows] == list(range(100))


def test_rotation_is_append_only_across_flushes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(lossline.writer, "SEGMENT_BYTES", 200)
    files = RunFiles(tmp_path, "p", "r")
    snapshots = []
    for step in range(30):
        files.append([{"_step": step, "_time": 0.0, "x": step}])
        snapshots.append([files.read_segment(i) for i in range(files.segments)])
    for before, after in zip(snapshots, snapshots[1:], strict=False):
        for i, old in enumerate(before):
            assert after[i].startswith(old)  # segments only grow
            if i < len(before) - 1:
                assert after[i] == old  # sealed segments never change


def sync(bucket: BucketSync, meta: bytes = b"{}", force: bool = False) -> bool:
    """What the upload thread does on each flush."""
    if not force and not bucket.due():
        return False
    return bucket.push(bucket.prepare(meta))


class FakeApi:
    def __init__(self) -> None:
        self.fail = False
        self.calls: list[dict[str, bytes]] = []

    def batch_bucket_files(self, bucket_id: str, add):
        if self.fail:
            raise ConnectionError("network down")
        self.calls.append({path: data for data, path in add})


def test_bucket_sync_retries_and_never_drops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(lossline.writer, "SEGMENT_BYTES", 100)
    files = RunFiles(tmp_path, "p", "r")
    bucket = BucketSync("me/b", files)
    api = FakeApi()
    bucket._api = api
    bucket._checked_bucket = True

    files.append([{"_step": 0, "_time": 0.0, "x": 1}])
    assert sync(bucket)
    assert set(api.calls[-1]) == {"p/r/metrics/000000.jsonl", "p/r/meta.json"}

    api.fail = True
    files.append([{"_step": i, "_time": 0.0, "x": i} for i in range(1, 12)])  # rotates
    assert not sync(bucket)
    assert bucket.failures == 1 and not sync(bucket)  # backing off: not even tried
    assert len(api.calls) == 1

    api.fail = False
    assert sync(bucket, force=True)
    uploaded = api.calls[-1]
    assert len(uploaded) == files.segments + 1  # every unconfirmed segment + meta
    for i in range(files.segments):
        assert uploaded[f"p/r/metrics/{i:06d}.jsonl"] == files.read_segment(i)

    files.append([{"_step": 99, "_time": 0.0, "x": 99}])
    assert sync(bucket)
    assert set(api.calls[-1]) == {f"p/r/metrics/{files.segments - 1:06d}.jsonl", "p/r/meta.json"}
    assert sync(bucket)
    assert set(api.calls[-1]) == {"p/r/meta.json"}  # nothing new: heartbeat only


def test_names():
    for _ in range(50):
        name = random_name()
        assert is_slug(name) and name.count("-") == 1
    assert slugify("  My Run #1!  ") == "my-run-1"
    assert slugify("__x") == "x"
    long_id = make_run_id("x" * 100)
    assert is_slug(long_id) and len(long_id) == 64
    assert make_run_id("!!!").startswith("run-")


def _run_script(tmp_path: Path, body: str, **kwargs) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "script.py"
    script.write_text(textwrap.dedent(body))
    env = {**os.environ, "LOSSLINE_DIR": str(tmp_path / "runs")}
    env["LOSSLINE_BUCKET"] = "none"
    return subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                          env=env, timeout=60, **kwargs)


def _only_meta(tmp_path: Path) -> dict:
    (meta,) = (tmp_path / "runs").glob("*/*/meta.json")
    return json.loads(meta.read_text())


def test_atexit_finishes_run(tmp_path: Path):
    proc = _run_script(tmp_path, """
        import lossline
        lossline.init(project="p")
        lossline.log({"x": 1})
    """)
    assert proc.returncode == 0, proc.stderr
    meta = _only_meta(tmp_path)
    assert meta["status"] == "finished" and meta["rows"] == 1


def test_uncaught_exception_marks_failed(tmp_path: Path):
    proc = _run_script(tmp_path, """
        import lossline
        lossline.init(project="p")
        lossline.log({"x": 1})
        raise SystemError("boom")
    """)
    assert proc.returncode == 1 and "boom" in proc.stderr
    meta = _only_meta(tmp_path)
    assert meta["status"] == "failed" and meta["rows"] == 1


def test_sigterm_marks_failed_and_still_dies(tmp_path: Path):
    proc = _run_script(tmp_path, """
        import os, signal, lossline
        lossline.init(project="p")
        lossline.log({"x": 1})
        os.kill(os.getpid(), signal.SIGTERM)
        import time; time.sleep(5)
        print("survived")
    """)
    assert proc.returncode == -signal.SIGTERM
    assert "survived" not in proc.stdout
    meta = _only_meta(tmp_path)
    assert meta["status"] == "failed" and meta["rows"] == 1


def test_bucket_sync_creates_missing_bucket(tmp_path: Path):
    from types import SimpleNamespace

    from huggingface_hub.errors import HfHubHTTPError

    class MissingBucketApi(FakeApi):
        created: list[str] = []

        def batch_bucket_files(self, bucket_id: str, add):
            if not self.created:
                raise ConnectionError("404 Not Found .../xet-write-token")
            super().batch_bucket_files(bucket_id, add)

        def bucket_info(self, bucket_id: str):
            response = SimpleNamespace(status_code=404, headers={}, request=None)
            raise HfHubHTTPError("404 Bucket Not Found", response=response)

        def create_bucket(self, bucket_id: str, private: bool, exist_ok: bool):
            assert private and exist_ok
            self.created.append(bucket_id)

    files = RunFiles(tmp_path, "p", "r")
    bucket = BucketSync("me/new", files)
    bucket._api = api = MissingBucketApi()
    assert sync(bucket)
    assert api.created == ["me/new"] and len(api.calls) == 1
