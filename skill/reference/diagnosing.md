# Reading runs and spotting problems

## What `lossline show` prints

```
seqmem/live-demo-3apn  running  step 2395  rows 2396  ran 10m  updated 16s ago
created 2026-09-25T19:10Z | laptop | Linux-7.2.3-arch1-3 | py3.13.15 | git e0c18b3 main
config: steps=6000 seed=7 lr=0.0005 batch_size=64 width=1024 warmup=null eval_every=100

metric                   last      min           max           mean10%   trend20%  history
eval/acc                 0.8679    0.01559 @100  0.8679 @2300  0.8627    → flat    ▁▁▁▃▄▅▆▇▇███████
train/grad_norm          0.8111    0.4263 @1741  7.745 @136    0.9955    ↑9.4%     █▆▅▃▄▂▂▂▃▃▁▁▁▁▁▁
train/loss               1.679     1.348 @2241   5.354 @128    1.64      ↓3.2%     █▇▅▄▃▂▂▂▂▁▁▁▁▁▁▁
```

- **Header:** status, last step, total rows, wall-clock time from start to the last
  upload (`ran`), and time since the last upload. Progress is `step` against the config's planned total (`steps=6000` above: 40%).
- **last:** the most recent value, which can be noisy.
- **min / max `@step`:** the extremes and where they happened. For a loss, `min @` shows
  where the best checkpoint probably is.
- **mean10%:** mean of the last 10% of rows. It's steadier than `last`, so quote it for
  noisy metrics.
- **trend20%:** relative change across the last 20% of the run (`↓`, `↑`, or `→ flat`).
  Whether that's good depends on the metric: falling loss is good, falling accuracy isn't.
- **history:** the whole run squeezed into 16 bars. It shows the shape: a smooth decay,
  a spike, or a rise at the end.

`lossline tail <run> -n 20` shows the raw latest rows when you need exact values, and
`lossline export <run> --from 2400 --to 2600 --format jsonl` shows the rows around an
event anywhere in the run.

## Patterns

**Healthy.** The loss falls steeply, then flattens. Eval loss follows train loss with a
small, stable gap. The gradient norm falls early and then holds roughly steady. The
learning-rate history has the shape the schedule promises (a warmup ramp, then a decay).

**Divergence.** The loss trend turns `↑` and `last` climbs well above `min`. The
gradient norm's `max` is many times its `mean10%`, often shortly before the loss jumps.
A `-` in place of a value, or gaps in the chart, mean NaN or inf was logged. Usual causes: learning rate
too high, missing warmup, or fp16 overflow. Say which step it started at: find it with
`export --from/--to` around the gradient-norm `max @` step.

**Spikes that recover.** The gradient-norm `max` is far above its `mean10%`, but the loss
trend is still `↓` and `last` is near `min`. This is common at a high learning rate, and
mostly harmless unless the spikes get more frequent.

**Plateau.** `→ flat` early, with the loss still near its starting value. Usual causes:
learning rate too low, or a bug (frozen parameters, wrong labels, loss on padding). A
plateau near chance accuracy right from the start points to a data or label bug more
than to tuning.

**Overfitting.** Train loss keeps falling while eval loss has `min @` well before the
latest step and a `↑` trend. Report the step of the best eval value: that's the
checkpoint to keep.

**Slowdowns and leaks.** Throughput `↓` over the run, or `sys/gpu_mem_gb` climbing
steadily. This usually comes from growing Python lists of tensors, per-step logging that
forces GPU syncs, or data-loader starvation.

## Status problems

**stalled.** The process stopped uploading about two minutes ago without saying it
ended. Either it was killed hard (OOM killer, `kill -9`, a box destroyed or preempted)
or the machine lost network while still training. If you can reach the box, check the
process (`ps`, `nvidia-smi`) and the local copy in `./lossline/<project>/<run>/`: if the
local files are newer than the bucket, training is alive and only uploads are failing.
The logger also printed an `upload ... failed` line to stderr.

**failed.** The script raised an uncaught exception or got SIGTERM. lossline doesn't
store tracebacks; read the job's own output or log file on the box. `show` tells you the
last step and values before the failure.

**Missing run.** Check the project name with `lossline ls` and check that the job's
stderr has a `lossline: run ...` line. If the script ran with `LOSSLINE_BUCKET=none` or
without a Hugging Face token, the run exists only in the box's `./lossline/` folder:
read it there with `--dir`.

## Comparing runs fairly

`lossline compare` lists the config keys that differ and the **last** value of each
metric, with `*` marking the best where the name implies a direction. Last values mislead
when runs have different lengths: a run that crashed at step 2,600 has a different
"last" from one that finished at 6,000. Check `step` in the output first. To compare at
the same step, use Python:

```python
from lossline import Reader
r = Reader()
def at(run, metric, step):
    pts = r.metrics("seqmem", r.resolve("seqmem", run))[metric]
    return min(pts, key=lambda p: abs(p[0] - step))[1]
{name: at(name, "eval/loss", 2500) for name in ("baseline", "wide", "hot-lr")}
```

Remember that one run per configuration is one seed. Small differences between runs are
often noise, so say so instead of declaring a winner.

## Reporting to the user

Lead with the answer, in two to four lines. For example: *"`wide-lr3e-4` is at step
12.4k of 20k (62%), still running. Train loss 1.28 (best 1.26 at 12.1k), falling ~3%
over the last fifth. Eval accuracy 0.73 and still rising. No spikes or NaNs."* Add the
diagnosis only when something is wrong, and point to the chart they can open:
https://bednarjosef.github.io/lossline/.
