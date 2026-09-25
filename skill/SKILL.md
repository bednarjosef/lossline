---
name: lossline
description: "Log and monitor ML training runs with lossline: serverless experiment tracking whose runs live in the user's own Hugging Face bucket, with live charts in a web app and a compact CLI for agents. Use when adding metric logging to a training script, launching training (especially on a remote or rented GPU box), checking on a run (is it still going, how is the loss, did it crash or stall), waiting for a run to finish, comparing runs or hyperparameters, or analysing training curves. Also use when the user mentions lossline, experiment tracking, training curves, or replacing wandb / W&B / TensorBoard. Triggers: /lossline, \"how's my run\", \"is training still going\", \"log metrics\", \"compare runs\", \"wait for training\"."
---

# lossline

lossline tracks training runs with no server. The logger writes each run as plain files
to a private Hugging Face bucket, `<hf user>/lossline`, created on the first run, with
runs grouped by project. The user watches live charts at
https://bednarjosef.github.io/lossline/, and you read the same runs with the `lossline`
CLI, which prints compact text made for agents. A local copy is always kept in
`./lossline/`, so no data is lost if the network drops.

## The CLI

Use `lossline` if it is on PATH. Otherwise run it without installing (`-q` hides uv's
install messages):

```bash
uvx -q --from "git+https://github.com/bednarjosef/lossline#subdirectory=python" lossline ...
```

Every command reads the user's default bucket through their Hugging Face login
(`hf auth login` or `HF_TOKEN`). `--bucket owner/name` picks another bucket, and
`--dir path` reads local run files instead, for example on a box without a token.
Runs are named `<project>/<run>`. A unique prefix of the run id works (`seqmem/wide`),
and `latest` means the newest run in the project.

| Command | Use it to |
|---|---|
| `lossline ls` | list projects |
| `lossline ls <project>` | list runs: status, step, time since the last upload, wall-clock duration, key metrics |
| `lossline show <project>/<run>` | config, machine, and per-metric last / min / max / trend / sparkline |
| `lossline compare <p>/<a> <p>/<b> ...` | put runs side by side: differing config keys, last value of each metric, `*` on the best (check each run's `step` first: a run that crashed early has an incomparable "last" value) |
| `lossline wait <project>/<run>` | block until the run ends, stalls, or hits a target |
| `lossline tail <project>/<run> [-n N] [-f]` | show the last rows, `-f` to follow |
| `lossline export <project>/<run> [--from S] [--to S] [--format csv\|jsonl]` | dump rows, or just the rows around an event |
| `lossline mv <project>/<run> <project>` | move runs to another project (a glob like `seqmem/'lr-*'` moves several) |
| `lossline rm <project>/<run> [--yes]` | delete runs; without `--yes` it only lists what it would delete |

`ls`, `show` and `compare` take `-m 'eval/*'` to filter metrics (repeatable, globs) and
`--json` for machine-readable output, though the plain text is usually easier to read.

A run's status is `running`, `finished`, `failed` (uncaught exception or SIGTERM), or
`stalled`. Stalled means the run says it is running but hasn't written anything for about
two minutes: the process was probably killed hard (OOM killer, `kill -9`, a destroyed
box) or the machine lost its network. Treat it as a crash to investigate, not as
progress.

## Checking on a run

1. `lossline ls <project>` to find the run and its status.
2. `lossline show <project>/<run>` for the numbers. Use `-m` when there are many metrics.
3. Report what matters, not the whole table: status, step (out of the planned total if
   the config has one), the headline metric's latest and best value, its trend, and
   anything abnormal. See [reference/diagnosing.md](reference/diagnosing.md) for how to
   read the stats and spot divergence, plateaus, overfitting, NaNs and stalls.

Don't guess at a run you haven't looked at, and don't tail training logs or `nohup.out`
when the run is in lossline: the CLI is shorter and covers the whole history.

## Organising runs

Move runs with `lossline mv`, for example `lossline mv seqmem/'lr-*' seqmem-lr-sweep`
to split a sweep into its own project. It keeps each run's id and history, updates its
`meta.json`, and refuses runs that are still running (their logger would keep writing to
the old path).

Deleting is permanent: buckets have no history. Run `lossline rm <ref>` without `--yes`
first, show the user the list it prints, and only add `--yes` once they've agreed to
that exact list. Never delete runs on your own initiative.

## Waiting for a run

Don't poll in a loop with `sleep`. Start `lossline wait` as a background command so
you're notified when it exits:

```bash
lossline wait seqmem/wide-lr3e-4-k2x9                    # until it finishes, fails or stalls
lossline wait seqmem/wide --step 20000                   # until it reaches a step
lossline wait seqmem/wide --until 'eval/acc>=0.9' --until 'train/loss<0.5'   # any target
lossline wait seqmem/wide --timeout 3600                 # give up after an hour
```

**Right after launching a job, add `--new`** and use the `name` you passed to `init`:
`lossline wait seqmem/wide-lr3e-4 --new --timeout 7200`. A freshly launched run doesn't
exist in the bucket until the script reaches `init` and uploads once (imports, data
loading and package installs can take minutes). Without `--new`, `wait` fails with "no
run", and `latest` would still point at the previous run. With `--new` it waits for the
next run with that name (runs created up to 2 minutes before `wait` started count), prints
`waiting on <project>/<id>`, then waits on that run.

It prints one summary line and exits with **0** when finished or the target is reached,
**2** failed, **3** stalled, **4** timed out, **1** on an error (for example, a run name
that doesn't match). It checks every 30 seconds by default. Runs upload every 15
seconds, so checking more often gains nothing.

## Adding logging to a training script

```python
import lossline

run = lossline.init(project="seqmem", name="wide-lr3e-4", config=cfg)  # cfg: dict, argparse.Namespace, dataclass, or object
for step in range(num_steps):
    ...
    if step % 10 == 0 or step == num_steps - 1:   # include the last step, or the run looks cut short
        lossline.log({"train/loss": loss.item(), "optim/lr": sched.get_last_lr()[0]}, step=step)
    if step % eval_every == 0:
        lossline.log({"eval/loss": eval_loss, "eval/acc": eval_acc}, step=step)
```

That's all that's required: the run finishes itself at exit, and is marked failed on an
uncaught exception or SIGTERM. Rules that matter:

- **Always pass `step=`.** Without it every `log()` call adds 1, so logging training and
  eval metrics in separate calls puts them on different steps. Steps must never go
  backwards; a row with a smaller step is dropped with a warning.
- **Name metrics `group/name`**: `train/loss`, `eval/acc`, `optim/lr`,
  `throughput/tokens_per_s`, `sys/gpu_mem_gb`. The web app groups charts by prefix and
  picks `train/loss` (or the first `*loss*`) as the headline chart.
- **Log every N steps in fast loops**, typically every 10 to 100. `log()` itself takes
  microseconds, but `.item()` on a CUDA tensor forces a GPU sync. Averaging over the
  interval gives a cleaner curve than one sample.
- **Only rank 0 logs** under DDP, FSDP or DeepSpeed: guard both `init` and `log`.
- **Choose a short, meaningful `name`** (`wide-lr3e-4`, `baseline`) and put everything
  else in `config`. The run id adds a random suffix, so names can repeat.
- **One project per research question**, never one project per run.
- Values can be Python numbers, numpy scalars, or 0-d tensors. NaN and inf are stored
  as null, and non-numeric values are skipped with a warning.
- The local copy goes to `./lossline/`. In a git repo, add `lossline/` to `.gitignore`.

Recipes for PyTorch, Hugging Face Trainer, Lightning, notebooks, sweeps and resumed
jobs are in [reference/instrumenting.md](reference/instrumenting.md).

## Running on a remote or rented box

1. Install on the box: `pip install "git+https://github.com/bednarjosef/lossline#subdirectory=python"`.
2. Give it a Hugging Face token with write access through the environment, never in code:
   `HF_TOKEN=... python train.py`. If the box already has `hf auth login`, nothing is needed.
   If the token is limited to an organization, also set `LOSSLINE_BUCKET=<org>/lossline`.
3. Right after launching, start `lossline wait <project>/<name> --new` in the background
   (see above). The logger also prints `lossline: run <project>/<id> (...)` to stderr at
   start, which is the exact reference once it appears.
4. Check and wait from wherever you are, including the user's laptop. You don't need SSH
   to see progress.

Never print, echo, commit or log a token. If you need to check that one is set, test
for it (`[ -n "$HF_TOKEN" ]`) instead of displaying it.

Environment variables: `LOSSLINE_BUCKET` (`owner/name`, or `none` for local only),
`LOSSLINE_DIR` (local copy, default `./lossline`), `LOSSLINE_PROJECT` (default project),
`LOSSLINE_FLUSH_INTERVAL` (seconds, default 15). Each flush costs 2 of the 1,000
Hugging Face API calls a free account gets per 5 minutes. With more than about 10 runs
at once, raise the interval to 30 or 60.

## Reading runs from Python

For analysis beyond the CLI, such as fitting a curve, plotting, or aggregating a sweep:

```python
from lossline import Reader

r = Reader()                                   # default bucket; Reader(dir="lossline") for local files
metas = r.runs("seqmem")                       # meta.json of every run, newest first
pts = r.metrics("seqmem", r.resolve("seqmem", "wide"))  # {"train/loss": [(step, value), ...], ...}
rows = r.history("seqmem", run_id)             # every logged row as a dict
```

The storage format is documented in `docs/format.md` in the repo: `meta.json` plus
append-only JSONL segments per run.
