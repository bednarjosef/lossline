"""The upload worker process: deadlines, kills, error replies, and finish() not hanging.

Fake workers speak the real wire protocol (lossline._upload_worker.send/recv) but never
touch the network.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

import lossline
import lossline.upload
from lossline.upload import BucketSync, WorkerTransport
from lossline.writer import RunFiles

HANG = "import sys, time\nsys.stdin.buffer.read(8)\ntime.sleep(600)\n"

RECORD = """
import json, sys
from lossline._upload_worker import recv, send
log = open(sys.argv[1], "a")
while (req := recv(sys.stdin.buffer)) is not None:
    if req[0] == "batch":
        log.write(json.dumps(sorted(path for _, path in req[2])) + "\\n"); log.flush()
    send(sys.stdout.buffer, ("ok", False))
"""

RATE_LIMITED = """
import sys
from lossline._upload_worker import recv, send
while (req := recv(sys.stdin.buffer)) is not None:
    send(sys.stdout.buffer, ("err", "HfHubHTTPError", "429 Too Many Requests", 429, {"retry-after": "42"}))
"""


def cmd(code: str, *args: str) -> list[str]:
    return [sys.executable, "-c", code, *args]


def one_row_bucket(tmp_path: Path, transport: WorkerTransport, timeout: float = 2.0) -> BucketSync:
    files = RunFiles(tmp_path, "p", "r")
    files.append([{"_step": 0, "_time": 0.0, "x": 1}])
    bucket = BucketSync("me/b", files, timeout=timeout, transport=transport)
    bucket._checked_bucket = True
    return bucket


def test_worker_uploads(tmp_path: Path):
    log = tmp_path / "calls.jsonl"
    bucket = one_row_bucket(tmp_path, WorkerTransport(cmd=cmd(RECORD, str(log))))
    assert bucket.push(bucket.prepare(b"{}"))
    assert json.loads(log.read_text()) == ["p/r/meta.json", "p/r/metrics/000000.jsonl"]
    assert bucket.pending_segments() == []
    bucket.close()


def test_hung_upload_times_out_and_is_retried(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    transport = WorkerTransport(cmd=cmd(HANG))
    bucket = one_row_bucket(tmp_path, transport, timeout=1.0)
    t0 = time.monotonic()
    assert not bucket.push(bucket.prepare(b"{}"))
    assert time.monotonic() - t0 < 10
    assert bucket.failures == 1 and bucket.pending_segments() == [0]  # nothing lost
    assert "no response within 1s" in capsys.readouterr().err
    assert transport._proc is None  # the hung worker was killed

    log = tmp_path / "calls.jsonl"
    transport.cmd = cmd(RECORD, str(log))  # the next attempt starts a fresh worker
    assert bucket.push(bucket.prepare(b"{}"))
    assert bucket.failures == 0 and log.exists()
    bucket.close()


def test_remote_error_keeps_status_and_retry_after(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    bucket = one_row_bucket(tmp_path, WorkerTransport(cmd=cmd(RATE_LIMITED)))
    now = time.monotonic()
    assert not bucket.push(bucket.prepare(b"{}"))
    assert bucket.next_attempt - now >= 41  # honoured the server's Retry-After
    assert "HTTP 429" in capsys.readouterr().err
    bucket.close()


def test_worker_that_cannot_start_falls_back_in_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                        capsys: pytest.CaptureFixture[str]):
    calls = []

    class FakeApi:
        def __init__(self, token=None):
            pass

        def batch_bucket_files(self, bucket_id, add):
            calls.append(bucket_id)

    monkeypatch.setattr("huggingface_hub.HfApi", FakeApi)
    bucket = one_row_bucket(tmp_path, WorkerTransport(cmd=["/nonexistent/python"]))
    assert bucket.push(bucket.prepare(b"{}"))
    assert calls == ["me/b"] and "upload worker unavailable" in capsys.readouterr().err


def test_finish_does_not_wait_behind_a_hung_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]):
    monkeypatch.setenv("LOSSLINE_BUCKET", "me/b")
    log = tmp_path / "calls.jsonl"
    commands = [cmd(HANG), cmd(RECORD, str(log))]  # first upload hangs, the final one works
    monkeypatch.setattr(lossline.upload, "worker_command", lambda: commands.pop(0))
    run = lossline.init(project="p", name="r", dir=tmp_path / "ll", flush_interval=0.2)
    run._sync._checked_bucket = True
    run.log({"x": 1.0}, step=0)
    time.sleep(6.5)  # the first upload is in flight, hung, past ABORT_AFTER
    t0 = time.monotonic()
    run.finish(timeout=20)
    assert time.monotonic() - t0 < 10
    uploads = [json.loads(line) for line in log.read_text().splitlines()]
    assert uploads and f"p/{run.id}/meta.json" in uploads[-1]
    meta = json.loads((tmp_path / "ll" / "p" / run.id / "meta.json").read_text())
    assert meta["status"] == "finished" and meta["rows"] == 1
    assert "failed" not in capsys.readouterr().err  # the abort is not reported as a failure


def test_push_uploads_a_local_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    from lossline.cli import main

    run = lossline.init(project="p", name="r", dir=tmp_path / "box")
    run.log({"x": 1.0}, step=0)
    run.finish()
    target = tmp_path / "bucket"
    assert main(["push", str(run.local_dir), "--dir", str(target)]) == 0
    assert "pushed p/" in capsys.readouterr().out
    assert main(["ls", "p", "--dir", str(target)]) == 0
    assert "finished" in capsys.readouterr().out


def test_push_marks_a_killed_run_and_refuses_live_ones(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    from lossline.cli import main

    run = lossline.init(project="p", name="r", dir=tmp_path / "box")
    run.log({"x": 1.0}, step=0)
    run._flush_local()  # live: recent heartbeat, status running
    target = tmp_path / "bucket"
    assert main(["push", str(run.local_dir), "--dir", str(target)]) == 1
    assert "looks live" in capsys.readouterr().err
    assert main(["push", str(run.local_dir), "--dir", str(target), "--mark", "failed", "--force"]) == 0
    meta = json.loads((target / "p" / run.id / "meta.json").read_text())
    assert meta["status"] == "failed" and meta["ended"]
    run.finish()
