from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import lossline
from lossline import Reader, run_status
from lossline.cli import main
from lossline.stats import fmt, metric_stats, sparkline, trend_pct


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def test_stalled_rule():
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    meta = {"status": "running", "flush_interval": 15}
    # threshold is 3 * 15 + 60 = 105 s
    assert run_status({**meta, "heartbeat": iso(now - timedelta(seconds=100))}, now.timestamp()) == "running"
    assert run_status({**meta, "heartbeat": iso(now - timedelta(seconds=106))}, now.timestamp()) == "stalled"
    slow = {**meta, "flush_interval": 60, "heartbeat": iso(now - timedelta(seconds=200))}
    assert run_status(slow, now.timestamp()) == "running"  # 3 * 60 + 60 = 240 s
    old = iso(now - timedelta(days=3))
    assert run_status({"status": "finished", "heartbeat": old}, now.timestamp()) == "finished"
    assert run_status({"status": "failed", "heartbeat": old}, now.timestamp()) == "failed"


def test_stats():
    points = [(i, 10.0 - i) for i in range(100)]
    s = metric_stats(points)
    assert (s["last"], s["min"], s["min_step"], s["max"], s["max_step"]) == (-89.0, -89.0, 99, 10.0, 0)
    assert s["mean_last10"] == pytest.approx(sum(10.0 - i for i in range(90, 100)) / 10)
    assert trend_pct([(0, 2.0), (1, 1.5), (2, 1.0)]) == pytest.approx(-50.0)
    assert trend_pct([(0, 1.0), (1, 1.0), (2, 1.0)]) == 0
    assert sparkline([(i, float(i)) for i in range(8)], width=8) == "▁▂▃▄▅▆▇█"
    assert sparkline([(0, None), (1, 2.0)]) == "▄"
    assert metric_stats([(0, None)]) == {"n": 1, "last": None, "last_step": 0}
    assert [fmt(v) for v in (None, 3, 0.000123, 1.23456, 12345.6, 2e9, 3.0)] == [
        "-", "3", "0.000123", "1.235", "12346", "2e+09", "3"]


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    for name, lr, scale in (("good", 1e-3, 1.0), ("bad", 1e-2, 2.0)):
        with lossline.init(project="demo", name=name, config={"lr": lr, "width": 64}, dir=root) as run:
            for step in range(50):
                run.log({"train/loss": scale * (3 - step / 50), "lr": lr})
                if step % 10 == 0:
                    run.log({"eval/acc": 0.5 / scale + step / 1000}, step=step)
    return root


def test_reader_lists(runs_dir: Path):
    reader = Reader(dir=runs_dir)
    (project,) = reader.projects()
    assert (project.name, project.runs) == ("demo", 2)
    assert {m["name"] for m in reader.runs("demo")} == {"good", "bad"}
    assert reader.resolve("demo", "good").startswith("good-")


def test_cli_ls(runs_dir: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["ls", "--dir", str(runs_dir)]) == 0
    out = capsys.readouterr().out
    assert "demo" in out and "2" in out

    assert main(["ls", "demo", "--dir", str(runs_dir)]) == 0
    out = capsys.readouterr().out
    assert "demo: 2 runs (2 finished)" in out
    assert "train/loss" in out and "eval/acc" in out and "good-" in out and "bad-" in out

    assert main(["ls", "demo", "--dir", str(runs_dir), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {r["status"] for r in data} == {"finished"} and data[0]["step"] == 49


def test_cli_show(runs_dir: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["show", "demo/good", "--dir", str(runs_dir)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("demo/good-") and "finished" in out
    assert "config: lr=0.001 width=64" in out
    loss_line = next(line for line in out.splitlines() if line.startswith("train/loss"))
    assert "@49" in loss_line and "↓" in loss_line and "█" in loss_line

    assert main(["show", "demo/good", "--dir", str(runs_dir), "-m", "eval/*"]) == 0
    out = capsys.readouterr().out
    assert "eval/acc" in out and "train/loss" not in out and "2 more metrics" in out

    assert main(["show", "demo/good", "--dir", str(runs_dir), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["metrics"]["train/loss"]["min_step"] == 49 and data["status"] == "finished"


def test_cli_compare(runs_dir: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["compare", "demo/good", "demo/bad", "--dir", str(runs_dir)]) == 0
    lines = capsys.readouterr().out.splitlines()
    loss = next(line for line in lines if line.startswith("train/loss")).split()
    acc = next(line for line in lines if line.startswith("eval/acc")).split()
    assert loss[1].endswith("*") and not loss[2].endswith("*")
    assert acc[1].endswith("*")
    assert any(line.startswith("config.lr") for line in lines)
    assert not any(line.startswith("config.width") for line in lines)  # same in both runs

    assert main(["compare", "demo/good", "demo/bad", "--dir", str(runs_dir), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["best"]["train/loss"].startswith("good-") and list(data["config"]) == ["lr"]


def test_cli_tail_and_export(runs_dir: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["tail", "demo/good", "-n", "3", "--dir", str(runs_dir)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3 and lines[-1].startswith("step=49 ")

    assert main(["export", "demo/good", "--dir", str(runs_dir)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "_step,_time,train/loss,lr,eval/acc" and len(lines) == 1 + 55

    assert main(["export", "demo/good", "--format", "jsonl", "--dir", str(runs_dir)]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 55 and rows[0]["_step"] == 0


def test_cli_errors(runs_dir: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["show", "demo/nope", "--dir", str(runs_dir)]) == 1
    assert "no run 'nope'" in capsys.readouterr().err
    assert main(["show", "demo", "--dir", str(runs_dir)]) == 1
    assert "expected <project>/<run>" in capsys.readouterr().err


def test_follow_live_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import threading
    import time

    import lossline.writer

    monkeypatch.setattr(lossline.writer, "SEGMENT_BYTES", 500)  # follow across rotations
    run = lossline.init(project="p", dir=tmp_path, flush_interval=0.02)

    def train() -> None:
        for step in range(200):
            run.log({"x": step})
            time.sleep(0.001)
        run.finish()

    worker = threading.Thread(target=train)
    worker.start()
    rows = list(Reader(dir=tmp_path).follow("p", run.id, poll=0.02))
    worker.join()
    assert [r["x"] for r in rows] == list(range(200))
    assert run_status(Reader(dir=tmp_path).meta("p", run.id)) == "finished"


def test_wait_and_latest(tmp_path, capsys):
    import lossline
    from lossline.cli import main

    first = lossline.init(project="p", name="old", dir=tmp_path, flush_interval=0.05)
    first.log({"eval/acc": 0.5})
    first.finish()
    run = lossline.init(project="p", name="new", dir=tmp_path, flush_interval=0.05)
    for i in range(5):
        run.log({"eval/acc": 0.2 * i})
    run.finish(status="failed")
    capsys.readouterr()

    assert main(["wait", "p/latest", "--dir", str(tmp_path), "--poll", "0.01"]) == 2
    assert f"p/{run.id} failed at step 4" in capsys.readouterr().out
    assert main(["wait", "p/latest", "--dir", str(tmp_path), "--until", "eval/acc>=0.7"]) == 0
    assert "reached the target" in capsys.readouterr().out
    assert main(["wait", "p/old", "--dir", str(tmp_path), "--step", "0"]) == 0
    assert main(["wait", "p/old", "--dir", str(tmp_path), "--until", "nonsense"]) == 1


def test_wait_new_ignores_older_runs(tmp_path, capsys, monkeypatch):
    import threading
    import time as _time

    import lossline
    from lossline import cli

    monkeypatch.setattr(cli, "NEW_RUN_GRACE", 0.0)
    old = lossline.init(project="p", name="job", dir=tmp_path, flush_interval=0.05)
    old.log({"loss": 1.0})
    old.finish()
    _time.sleep(0.05)

    def launch():
        _time.sleep(0.3)
        run = lossline.Run(project="p", name="job", dir=tmp_path, flush_interval=0.05)
        run.log({"loss": 0.5}, step=7)
        run.finish(status="failed")

    t = threading.Thread(target=launch)
    t.start()
    code = cli.main(["wait", "p/job", "--new", "--dir", str(tmp_path), "--poll", "0.05",
                     "--timeout", "20"])
    t.join()
    out = capsys.readouterr().out
    assert code == 2 and old.id not in out and "failed at step 7" in out


def test_export_step_range(tmp_path, capsys):
    import lossline
    from lossline.cli import main

    run = lossline.init(project="p", dir=tmp_path, flush_interval=0.05)
    for i in range(10):
        run.log({"loss": i}, step=i)
    run.finish()
    capsys.readouterr()
    main(["export", f"p/{run.id}", "--dir", str(tmp_path), "--from", "3", "--to", "5",
          "--format", "jsonl"])
    steps = [json.loads(line)["_step"] for line in capsys.readouterr().out.splitlines()]
    assert steps == [3, 4, 5]
