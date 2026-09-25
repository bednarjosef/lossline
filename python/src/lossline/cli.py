"""``lossline`` command line: compact, plain-text views of runs for people and agents."""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .reader import Reader, parse_lines, run_status
from .source import SourceError, _parse_time
from .stats import direction, fmt, metric_stats, sparkline, trend_arrow
from .writer import segment_name

KEY_METRICS = 3


# -- formatting helpers ---------------------------------------------------------


def table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    rows = [list(map(str, r)) for r in rows]
    widths = [max(len(str(h)), *(len(r[i]) for r in rows)) for i, h in enumerate(header)]
    lines = ["  ".join(str(c).ljust(w) for c, w in zip(line, widths, strict=True)).rstrip()
             for line in [list(header), *rows]]
    return "\n".join(lines)


def span(seconds: float) -> str:
    """45s, 12m, 3h05m, 2d04h."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{s % 3600 // 60:02d}m"
    return f"{s // 86400}d{s % 86400 // 3600:02d}h"


def ago(ts: float, now: float) -> str:
    return f"{span(now - ts)} ago" if ts else "-"


def run_times(meta: dict[str, Any]) -> tuple[float, float]:
    """(created, last activity) as unix seconds."""
    created = _parse_time(meta.get("created"))
    last = _parse_time(meta.get("ended") or meta.get("heartbeat")) or created
    return created, last


def matches(name: str, globs: list[str] | None) -> bool:
    return not globs or any(fnmatch.fnmatchcase(name, g) for g in globs)


def split_globs(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    return [g.strip() for v in values for g in v.split(",") if g.strip()]


def flat_config(config: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(config, dict):
        return {prefix: config}
    out: dict[str, Any] = {}
    for key, value in config.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            out.update(flat_config(value, name))
        else:
            out[name] = value
    return out


def fmt_config_value(value: Any) -> str:
    if isinstance(value, float):
        return fmt(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), default=str)


def wrap_pairs(label: str, pairs: list[str], width: int = 100) -> list[str]:
    lines, line = [], label
    for pair in pairs:
        if len(line) + 1 + len(pair) > width and line != label:
            lines.append(line)
            line = " " * len(label)
        line += " " + pair
    lines.append(line)
    return lines


def pick_key_metrics(summaries: list[dict[str, Any]], limit: int = KEY_METRICS) -> list[str]:
    """Guess the few metrics worth a column: frequent ones, losses/accuracies first."""
    counts = Counter(k for s in summaries for k in s if not k.startswith("_"))

    def rank(name: str) -> tuple[bool, int, int, int, str]:
        leaf = name.rsplit("/", 1)[-1].lower()
        noisy = name.startswith(("sys/", "system/")) or leaf in ("lr", "learning_rate", "epoch")
        exact = leaf in ("loss", "acc", "accuracy", "reward", "return", "score")
        kind = (0 if "loss" in leaf else 1 if direction(name) else 4) + (0 if exact else 2)
        group = 0 if name.startswith(("eval", "val", "test")) else 1
        return (noisy, -counts[name], kind, group, name)

    return sorted(counts, key=rank)[:limit]


def parse_ref(ref: str) -> tuple[str, str]:
    project, sep, run = ref.strip("/").partition("/")
    if not sep or not run:
        raise SourceError(f"expected <project>/<run>, got {ref!r}")
    return project, run


# -- commands -----------------------------------------------------------------


def cmd_ls(reader: Reader, args: argparse.Namespace) -> None:
    now = time.time()
    if not args.project:
        projects = reader.projects()
        if args.json:
            print(json.dumps([{"project": p.name, "runs": p.runs,
                               "last_activity": _iso(p.last_activity)} for p in projects]))
            return
        if not projects:
            print(f"no projects in {reader.source.label}")
            return
        print(reader.source.label)
        print(table(["project", "runs", "last activity"],
                    [[p.name, str(p.runs), ago(p.last_activity, now)] for p in projects]))
        return

    metas = reader.runs(args.project)
    if args.limit:
        metas = metas[: args.limit]
    globs = split_globs(args.metric)
    summaries = [m.get("summary") or {} for m in metas]
    if globs:
        keys = sorted({k for s in summaries for k in s if not k.startswith("_") and matches(k, globs)})
    else:
        keys = pick_key_metrics(summaries)
    if args.json:
        out = []
        for meta in metas:
            created, last = run_times(meta)
            summary = meta.get("summary") or {}
            out.append({
                "id": meta.get("id"), "name": meta.get("name"), "status": run_status(meta, now),
                "step": summary.get("_step"), "created": meta.get("created"),
                "last_activity": _iso(last), "duration_s": round(last - created, 1),
                "tags": meta.get("tags") or [],
                "summary": {k: v for k, v in summary.items() if not globs or matches(k, globs)},
            })
        print(json.dumps(out))
        return
    if not metas:
        print(f"no runs in project {args.project!r} ({reader.source.label})")
        return
    statuses = Counter(run_status(m, now) for m in metas)
    print(f"{args.project}: {len(metas)} runs ("
          + ", ".join(f"{n} {s}" for s, n in statuses.most_common()) + ")")
    rows = []
    for meta in metas:
        created, last = run_times(meta)
        summary = meta.get("summary") or {}
        rows.append([meta.get("id", "?"), run_status(meta, now), fmt(summary.get("_step")),
                     ago(last, now), span(last - created), *(fmt(summary.get(k)) for k in keys)])
    print(table(["run", "status", "step", "updated", "duration", *keys], rows))


def cmd_show(reader: Reader, args: argparse.Namespace) -> None:
    project, run = parse_ref(args.run)
    run = reader.resolve(project, run)
    meta = reader.meta(project, run)
    history = reader.metrics(project, run)
    globs = split_globs(args.metric)
    stats = {k: metric_stats(v) for k, v in sorted(history.items()) if matches(k, globs)}
    now = time.time()
    status = run_status(meta, now)
    if args.json:
        for name, s in stats.items():
            s["sparkline"] = sparkline(history[name])
        print(json.dumps({"project": project, "run": run, "status": status, "meta": meta,
                          "metrics": stats}))
        return

    created, last = run_times(meta)
    summary = meta.get("summary") or {}
    when = f"ended {ago(last, now)}" if meta.get("ended") else f"updated {ago(last, now)}"
    print(f"{project}/{run}  {status}  step {fmt(summary.get('_step'))}  "
          f"rows {meta.get('rows', 0)}  ran {span(last - created)}  {when}")
    system, git = meta.get("system") or {}, meta.get("git") or {}
    facts = [f"created {meta.get('created', '?')[:16]}Z"]
    facts += [str(system[k]) for k in ("host", "gpu", "platform") if system.get(k)]
    if system.get("gpu_count"):
        facts[-1] += f" x{system['gpu_count']}"
    if system.get("python"):
        facts.append(f"py{system['python']}")
    if git:
        facts.append(f"git {git.get('commit')} {git.get('branch') or ''}"
                     f"{' dirty' if git.get('dirty') else ''}".rstrip())
    print(" | ".join(facts))
    if meta.get("tags"):
        print("tags: " + ", ".join(map(str, meta["tags"])))
    if meta.get("notes"):
        print("notes: " + " ".join(str(meta["notes"]).split()))
    config = flat_config(meta.get("config") or {})
    if config:
        print("\n".join(wrap_pairs("config:", [f"{k}={fmt_config_value(v)}" for k, v in config.items()])))
    extra = {k: v for k, v in summary.items() if k != "_step" and k not in history}
    if extra:
        print("\n".join(wrap_pairs("summary:", [f"{k}={fmt_config_value(v)}" for k, v in extra.items()])))
    if not stats:
        print("no metrics" + (" match" if globs else " logged yet"))
        return
    rows = []
    for name, s in stats.items():
        rows.append([
            name, fmt(s["last"]),
            f"{fmt(s.get('min'))} @{s['min_step']}" if "min" in s else "-",
            f"{fmt(s.get('max'))} @{s['max_step']}" if "max" in s else "-",
            fmt(s.get("mean_last10")), trend_arrow(s.get("trend_last20")),
            sparkline(history[name]),
        ])
    print()
    print(table(["metric", "last", "min", "max", "mean10%", "trend20%", "history"], rows))
    hidden = len(history) - len(stats)
    if hidden:
        print(f"({hidden} more metrics; use --metric to select)")


def cmd_compare(reader: Reader, args: argparse.Namespace) -> None:
    refs = [parse_ref(r) for r in args.runs]
    refs = [(p, reader.resolve(p, r)) for p, r in refs]
    metas = [reader.meta(p, r) for p, r in refs]
    labels = [r if len({p for p, _ in refs}) == 1 else f"{p}/{r}" for p, r in refs]
    summaries = [m.get("summary") or {} for m in metas]
    globs = split_globs(args.metric)
    names = sorted({k for s in summaries for k in s if not k.startswith("_") and matches(k, globs)})
    configs = [flat_config(m.get("config") or {}) for m in metas]
    config_keys = sorted({k for c in configs for k in c})
    differing = [k for k in config_keys if len({json.dumps(c.get(k)) for c in configs}) > 1]
    best: dict[str, int | None] = {}
    for name in names:
        sign = direction(name)
        vals = [(s.get(name), i) for i, s in enumerate(summaries)]
        vals = [(v, i) for v, i in vals if isinstance(v, (int, float))]
        best[name] = None
        if sign and len(vals) > 1:
            best[name] = (min(vals) if sign < 0 else max(vals))[1]
    if args.json:
        print(json.dumps({
            "runs": [{"project": p, "id": r, "status": run_status(m), "step": s.get("_step")}
                     for (p, r), m, s in zip(refs, metas, summaries, strict=True)],
            "config": {k: [c.get(k) for c in configs] for k in differing},
            "metrics": {n: [s.get(n) for s in summaries] for n in names},
            "best": {n: labels[i] for n, i in best.items() if i is not None},
        }))
        return
    rows = [["status", *(run_status(m) for m in metas)],
            ["step", *(fmt(s.get("_step")) for s in summaries)]]
    rows += [[f"config.{k}", *(fmt_config_value(c.get(k, "-")) for c in configs)] for k in differing]
    for name in names:
        cells = [fmt(s.get(name)) + ("*" if best[name] == i else "")
                 for i, s in enumerate(summaries)]
        rows.append([name, *cells])
    print(table(["", *labels], rows))
    print("(last values; * = best among runs where the metric name implies a direction; "
          "config shows differing keys only)")


def cmd_tail(reader: Reader, args: argparse.Namespace) -> None:
    project, run = parse_ref(args.run)
    run = reader.resolve(project, run)
    meta = reader.meta(project, run)
    segments = int(meta.get("segments") or 0)
    last_rows: list[dict[str, Any]] = []
    index, offset = max(segments - 1, 0), 0
    for i in range(segments - 1, -1, -1):
        try:
            data = reader.source.read(f"{project}/{run}/{segment_name(i)}")
        except FileNotFoundError:
            continue
        if i == segments - 1:
            offset = data.rfind(b"\n") + 1  # follow from the last complete line
        last_rows = parse_lines(data)[0] + last_rows
        if len(last_rows) >= args.n:
            break
    for row in last_rows[-args.n:] if args.n else []:
        print(format_row(row))
    if args.follow:
        sys.stdout.flush()
        for row in reader.follow(project, run, poll=args.poll, segment=index, offset=offset):
            print(format_row(row), flush=True)
        final = reader.meta(project, run)
        print(f"-- run {run_status(final)} --")


WAIT_EXIT = {"done": 0, "finished": 0, "failed": 2, "stalled": 3, "timeout": 4}
# with --new, a run created this long before `wait` started still counts as new, so
# launching the job first and starting `wait` a moment later doesn't miss it
NEW_RUN_GRACE = 120.0


def wait_for_new_run(reader: Reader, project: str, ref: str, since: float,
                     deadline: float | None, poll: float) -> str | None:
    """The id of the first run created after ``since`` whose id starts with ``ref``
    (any run for ``latest``). Runs appear once their first meta.json upload lands."""
    old: set[str] = set()
    while True:
        try:
            ids = reader.run_ids(project)
        except (SourceError, FileNotFoundError):
            ids = []  # the project (or the whole bucket) doesn't exist yet
        for rid in sorted(set(ids) - old):
            if ref != "latest" and not rid.startswith(ref):
                continue
            try:
                meta = reader.meta(project, rid)
            except (FileNotFoundError, ValueError):
                continue  # listed before its meta.json landed; look again next round
            if _parse_time(meta.get("created")) >= since:
                return rid
            old.add(rid)
        if deadline and time.time() >= deadline:
            return None
        time.sleep(poll)


def parse_condition(text: str) -> tuple[str, str, float]:
    """``'eval/acc>=0.9'`` -> ``('eval/acc', '>=', 0.9)``."""
    for op in (">=", "<=", ">", "<"):
        name, sep, value = text.partition(op)
        if sep and name.strip() and value.strip():
            try:
                return name.strip(), op, float(value)
            except ValueError:
                break
    raise SourceError(f"expected a condition like 'eval/acc>=0.9', got {text!r}")


def holds(value: Any, op: str, target: float) -> bool:
    if not isinstance(value, (int, float)):
        return False
    return {">=": value >= target, "<=": value <= target, ">": value > target,
            "<": value < target}[op]


def cmd_wait(reader: Reader, args: argparse.Namespace) -> int:
    """Block until the run ends, stalls, or reaches --step / --until; one line, then exit.

    Exit codes: 0 finished or condition met, 2 failed, 3 stalled, 4 timed out (1 = error).
    Made for agents: start it in the background and get woken up when something happens.
    """
    project, ref = parse_ref(args.run)
    conditions = [parse_condition(c) for c in args.until or []]
    started = time.time()
    deadline = started + args.timeout if args.timeout else None
    if args.new:
        found = wait_for_new_run(reader, project, ref, started - NEW_RUN_GRACE, deadline,
                                 min(args.poll, 10.0))
        if found is None:
            print(f"no new run matching {project}/{ref} appeared (timed out waiting)")
            return WAIT_EXIT["timeout"]
        run = found
        print(f"waiting on {project}/{run}", flush=True)
    else:
        run = reader.resolve(project, ref)
    while True:
        meta = reader.meta(project, run)
        status = run_status(meta)
        summary = meta.get("summary") or {}
        step = summary.get("_step")
        reached = (args.step is not None and isinstance(step, int) and step >= args.step) or any(
            holds(summary.get(name), op, target) for name, op, target in conditions
        )
        outcome = ("done" if reached else status if status != "running"
                   else "timeout" if deadline and time.time() >= deadline else None)
        if outcome:
            break
        time.sleep(args.poll)
    keys = [c[0] for c in conditions] or pick_key_metrics([summary])
    values = " ".join(f"{k}={fmt(summary.get(k))}" for k in keys if k in summary)
    what = {"done": "reached the target", "timeout": "still running (timed out waiting)"}
    print(f"{project}/{run} {what.get(outcome, outcome)} at step {step}  {values}".rstrip())
    return WAIT_EXIT[outcome]


def format_row(row: dict[str, Any]) -> str:
    stamp = datetime.fromtimestamp(row.get("_time", 0), timezone.utc).strftime("%H:%M:%SZ")
    metrics = " ".join(f"{k}={fmt(v)}" for k, v in row.items() if k not in ("_step", "_time"))
    return f"step={row.get('_step')} {stamp} {metrics}"


def cmd_export(reader: Reader, args: argparse.Namespace) -> None:
    project, run = parse_ref(args.run)
    run = reader.resolve(project, run)
    rows = (r for r in reader.rows(project, run)
            if (args.start is None or r.get("_step", 0) >= args.start)
            and (args.end is None or r.get("_step", 0) <= args.end))
    if args.format == "jsonl":
        for row in rows:
            sys.stdout.write(json.dumps(row, separators=(",", ":")) + "\n")
        return
    all_rows = list(rows)
    columns = list(dict.fromkeys(k for row in all_rows for k in row))
    columns = ["_step", "_time", *(c for c in columns if c not in ("_step", "_time"))]
    writer = csv.DictWriter(sys.stdout, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(all_rows)


def _iso(ts: float) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- entry point --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bucket", help="HF bucket 'owner/name' (default: $LOSSLINE_BUCKET, else <your hf user>/lossline)")
    common.add_argument("--dir", help="local runs directory (default: $LOSSLINE_DIR or ./lossline)")
    as_json = argparse.ArgumentParser(add_help=False)
    as_json.add_argument("--json", action="store_true", help="machine-readable output")
    metric = argparse.ArgumentParser(add_help=False)
    metric.add_argument("-m", "--metric", action="append",
                        help="metric glob(s), repeatable or comma-separated, e.g. 'eval/*'")

    parser = argparse.ArgumentParser(
        prog="lossline", description="Inspect lossline runs stored in a HF bucket or local dir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Runs are referred to as <project>/<run>; a unique prefix of the run id works,
and "latest" means the newest run in the project.

examples:
  lossline ls                                  projects
  lossline ls seqmem                           runs with status and key metrics
  lossline show seqmem/bold-heron -m 'eval/*'  stats + sparklines for matching metrics
  lossline compare seqmem/bold-heron seqmem/calm-otter
  lossline tail seqmem/bold-heron -f           follow a live run
  lossline wait seqmem/latest --until 'eval/acc>=0.9' --timeout 3600
                                               block until done, failed, stalled or target
  lossline wait seqmem/wide-lr3e-4 --new       the run just launched with that name
  lossline export seqmem/bold-heron --from 2400 --to 2600    rows around an event
  lossline export seqmem/bold-heron --format jsonl > run.jsonl""")
    parser.add_argument("--version", action="version", version=f"lossline {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ls", parents=[common, as_json, metric],
                       help="list projects, or the runs of one project")
    p.add_argument("project", nargs="?")
    p.add_argument("--limit", type=int, default=0, help="show only the newest N runs")
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("show", parents=[common, as_json, metric],
                       help="config, system and per-metric stats of a run")
    p.add_argument("run", metavar="project/run")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("compare", parents=[common, as_json, metric],
                       help="last value of each metric, one column per run")
    p.add_argument("runs", nargs="+", metavar="project/run")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("tail", parents=[common], help="print the last rows of a run")
    p.add_argument("run", metavar="project/run")
    p.add_argument("-n", type=int, default=10, help="number of rows (default 10)")
    p.add_argument("-f", "--follow", action="store_true", help="keep printing new rows")
    p.add_argument("--poll", type=float, default=5.0, help="seconds between polls with -f")
    p.set_defaults(func=cmd_tail)

    p = sub.add_parser(
        "wait", parents=[common],
        help="block until a run ends, stalls, or reaches a step/metric target",
        description="Exit codes: 0 finished or target reached, 2 failed, 3 stalled, "
                    "4 timed out, 1 error.",
    )
    p.add_argument("run", metavar="project/run")
    p.add_argument("--step", type=int, help="return once the run reaches this step")
    p.add_argument("--until", action="append", metavar="COND",
                   help="return once a metric's latest value meets COND, e.g. 'eval/acc>=0.9' "
                        "(repeatable; any one is enough)")
    p.add_argument("--new", action="store_true",
                   help="wait for a run that starts now: the next run whose id starts with RUN "
                        "(the name given to init) or, for 'latest', any new run. Use right after "
                        "launching a job; runs created up to 2 minutes earlier count")
    p.add_argument("--timeout", type=float, help="give up after this many seconds")
    p.add_argument("--poll", type=float, default=30.0,
                   help="seconds between checks (default 30; runs flush every 15)")
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("export", parents=[common], help="write rows to stdout (all, or --from/--to a step range)")
    p.add_argument("run", metavar="project/run")
    p.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    p.add_argument("--from", dest="start", type=int, metavar="STEP", help="first step to include")
    p.add_argument("--to", dest="end", type=int, metavar="STEP", help="last step to include")
    p.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        reader = Reader(bucket=args.bucket, dir=args.dir)
        code = args.func(reader, args)
    except (SourceError, FileNotFoundError) as exc:
        message = str(exc)
        if isinstance(exc, FileNotFoundError):
            message = f"not found: {exc.filename or message}"
        print(f"lossline: error: {message}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # stdout closed early (e.g. piped into head); exit quietly
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    return code or 0
