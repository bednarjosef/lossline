# Storage format (v1)

lossline has no server. A run is a folder of plain files in a Hugging Face bucket
(or on local disk, with the same layout). The Python logger writes it, and the web
app and the CLI read it. Anything that can read files can read your runs.

## Layout

```
<bucket>/<project>/<run>/meta.json
<bucket>/<project>/<run>/metrics/000000.jsonl
<bucket>/<project>/<run>/metrics/000001.jsonl
...
```

- `<project>` and `<run>` are path-safe slugs: `[a-z0-9][a-z0-9._-]*`, at most 64 characters.
- `<run>` is the run id, unique within the project. The logger makes it from the
  run name plus a 4-character random suffix, e.g. `bold-heron-7f3a`.

## `meta.json`

Rewritten on every flush. Readers treat unknown keys as optional.

```json
{
  "format": 1,
  "project": "seqmem",
  "id": "bold-heron-7f3a",
  "name": "bold-heron",
  "status": "running",
  "created": "2026-09-25T18:40:12.113Z",
  "heartbeat": "2026-09-25T19:02:47.901Z",
  "ended": null,
  "flush_interval": 15,
  "config": {"lr": 0.0003, "batch_size": 64},
  "summary": {"_step": 12400, "train/loss": 1.284, "eval/acc": 0.731},
  "system": {"host": "C.2581173", "gpu": "NVIDIA GeForce RTX 3090", "python": "3.12.4", "platform": "Linux-6.8"},
  "git": {"commit": "3f9c2e1", "branch": "main", "dirty": false},
  "tags": [],
  "notes": "",
  "segments": 2,
  "rows": 12400
}
```

| key | meaning |
|---|---|
| `status` | `running`, `finished` or `failed` |
| `heartbeat` | last time the logger flushed. A `running` run whose heartbeat is older than `3 × flush_interval + 60` seconds is shown as **stalled** (the process probably died without saying so) |
| `ended` | set when status becomes `finished` or `failed` |
| `summary` | last logged value of every metric, plus `_step` |
| `segments` | number of metric segment files |
| `rows` | total rows across all segments |

Times are ISO 8601 UTC with a `Z` suffix.

## Metric segments

`metrics/NNNNNN.jsonl`, numbered from `000000`. One JSON object per line:

```json
{"_step": 0, "_time": 1790361612.41, "train/loss": 2.914, "lr": 0.0003}
{"_step": 1, "_time": 1790361612.93, "train/loss": 2.771}
```

- `_step` (int, non-decreasing) and `_time` (Unix seconds, float) are always present.
- Every other key is a metric: a finite number. Non-finite values are written as `null`.
  A row holds only the metrics logged at that step, so metrics may be sparse.
- Metric names may contain `/`. The part before the first `/` is the metric's group
  (`train/loss` is in group `train`).

### Append-only rule

Only the **last** segment ever changes, and it only grows: each flush uploads it with
the new lines appended. Once a segment passes 4 MB the logger starts the next one and
never touches the old one again.

This lets a reader follow a live run cheaply: remember how many bytes of the last
segment it has seen, and fetch only the rest with an HTTP `Range` request. A reader
must only parse complete lines (ending in `\n`) and keep any partial tail for later.
