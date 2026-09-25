"""Integration test against the real Hub. Run with ``pytest -m hf``.

Writes under ``pytest-<random>/`` in LOSSLINE_TEST_BUCKET (default josefbednar/tracker-spike)
and deletes everything it wrote afterwards.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import lossline
from lossline import Reader
from lossline.cli import main

BUCKET = os.environ.get("LOSSLINE_TEST_BUCKET", "josefbednar/tracker-spike")

pytestmark = pytest.mark.hf


@pytest.fixture
def project():
    from huggingface_hub import HfApi

    name = f"pytest-{secrets.token_hex(3)}"
    yield name
    api = HfApi()
    paths = [f.path for f in api.list_bucket_tree(BUCKET, prefix=name + "/", recursive=True)
             if f.path.startswith(name + "/") and getattr(f, "type", "file") == "file"]
    if paths:
        api.batch_bucket_files(BUCKET, delete=paths)


def test_bucket_round_trip(project: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    run = lossline.init(project=project, name="hf", config={"lr": 1e-3}, bucket=BUCKET,
                        dir=tmp_path, flush_interval=2)
    for step in range(50):
        run.log({"train/loss": 2.0 - step / 50, "lr": 1e-3})
    reader = Reader(bucket=BUCKET)
    deadline = time.time() + 60
    meta = None
    while time.time() < deadline:  # the first flush happens in the background
        try:
            meta = reader.meta(project, run.id)
            if meta["rows"] == 50:
                break
        except FileNotFoundError:
            pass
        time.sleep(2)
    assert meta is not None and meta["status"] == "running" and meta["rows"] == 50

    for _ in range(50, 60):
        run.log({"train/loss": 1.0, "eval/acc": 0.9})
    run.finish()

    meta = reader.meta(project, run.id)
    assert meta["status"] == "finished" and meta["rows"] == 60 and meta["summary"]["_step"] == 59
    rows = reader.history(project, run.id)
    assert [r["_step"] for r in rows] == list(range(60))
    local = (tmp_path / project / run.id / "metrics" / "000000.jsonl").read_bytes()
    assert reader.source.read(f"{project}/{run.id}/metrics/000000.jsonl") == local
    # Range reads: only the bytes after an offset; nothing past the end
    assert reader.source.read(f"{project}/{run.id}/metrics/000000.jsonl", 100) == local[100:]
    assert reader.source.read(f"{project}/{run.id}/metrics/000000.jsonl", len(local)) == b""
    assert [p.name for p in reader.projects() if p.name == project] == [project]

    assert main(["ls", project, "--bucket", BUCKET]) == 0
    assert run.id in capsys.readouterr().out
    assert main(["show", f"{project}/hf", "--bucket", BUCKET]) == 0
    out = capsys.readouterr().out
    assert "finished" in out and "train/loss" in out and "eval/acc" in out


def test_exit_without_finish_uploads(project: str, tmp_path: Path):
    """The atexit hook must still upload during interpreter shutdown."""
    script = tmp_path / "train.py"
    script.write_text(textwrap.dedent(f"""
        import lossline
        run = lossline.init(project={project!r}, name="atexit", bucket={BUCKET!r})
        for i in range(10):
            lossline.log({{"x": i}})
        print(run.id)
    """))
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                          timeout=120, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    run_id = proc.stdout.strip()
    meta = Reader(bucket=BUCKET).meta(project, run_id)
    assert meta["status"] == "finished" and meta["rows"] == 10


def test_creates_missing_bucket(tmp_path):
    """The first upload to a bucket that doesn't exist yet creates it and still lands.

    Regression: the failed first attempt used to poison hf_xet's process-wide session,
    so every later upload failed with "Previous task error" and nothing ever arrived.
    """
    from huggingface_hub import HfApi

    owner = BUCKET.split("/")[0]
    bucket = f"{owner}/lossline-pytest-{secrets.token_hex(3)}"
    api = HfApi()
    try:
        run = lossline.init(project="p", bucket=bucket, dir=tmp_path, flush_interval=0.2)
        for i in range(20):
            run.log({"loss": 1 / (i + 1)})
        run.finish()
        meta = Reader(bucket=bucket).meta("p", run.id)
        assert meta["status"] == "finished" and meta["rows"] == 20
    finally:
        try:
            api.delete_bucket(bucket)
        except Exception:
            pass
