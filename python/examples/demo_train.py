"""A fake but believable training run, for populating lossline with demo data.

No ML dependencies: the curves come from a small analytic model of training
(power-law loss decay, lr warmup + cosine, noise, occasional loss spikes).
Config knobs change the curves visibly:

- higher --lr trains faster but noisier, and too high diverges into spikes
- bigger --width lowers the final loss, costs throughput and GPU memory
- bigger --batch-size smooths the noise, raises throughput and memory

    uv run python examples/demo_train.py --project demo --steps 3000
    uv run python examples/demo_train.py --project demo --lr 3e-3 --width 1024 --sleep 0.05
"""

from __future__ import annotations

import argparse
import math
import random
import time

import lossline


def lr_at(step: int, steps: int, peak: float, warmup: int) -> float:
    if step < warmup:
        return peak * (step + 1) / warmup
    progress = (step - warmup) / max(1, steps - warmup)
    return peak * (0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * progress)))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default="demo")
    p.add_argument("--name", default=None)
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--sleep", type=float, default=0.0, help="seconds per step (for live demos)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--warmup", type=int, default=None, help="warmup steps (default 5%% of steps)")
    p.add_argument("--eval-every", type=int, default=100)
    p.add_argument("--bucket", default=None)
    p.add_argument("--dir", default=None)
    p.add_argument("--fail-at", type=int, default=None, help="raise at this step (demo a failed run)")
    args = p.parse_args()

    rng = random.Random(args.seed)
    warmup = args.warmup if args.warmup is not None else max(1, args.steps // 20)
    tags = [f"w{args.width}", f"bs{args.batch_size}"]
    not_config = ("project", "name", "bucket", "dir", "sleep", "fail_at")
    config = {k: v for k, v in vars(args).items() if k not in not_config}
    run = lossline.init(project=args.project, name=args.name, config=config, bucket=args.bucket,
                        dir=args.dir, tags=tags, notes="synthetic run from examples/demo_train.py")

    # How the knobs shape the curves.
    capacity = math.log2(args.width / 64)                    # 0 at width 64, 4 at 1024
    floor = 1.9 - 0.22 * capacity                            # irreducible loss for this width
    lr_ratio = args.lr / 1e-3
    speed = 0.9 * min(lr_ratio, 3.0) ** 0.5                  # more lr trains faster ...
    instability = max(0.0, math.log(lr_ratio) - 0.7)         # ... until it gets unstable
    noise = 0.05 / math.sqrt(args.batch_size / 64)
    gen_gap = 0.04 + 0.03 * capacity                         # bigger models overfit a bit more
    base_tps = 2.2e5 * args.batch_size / 64 / (args.width / 512) ** 1.3
    mem_gb = 2.5 + 0.9 * args.batch_size / 64 * (args.width / 512) ** 1.5

    progress = 0.0  # "effective" training progress, accumulated with the lr
    spike = 0.0
    loss = 4.5
    for step in range(args.steps):
        if args.fail_at is not None and step == args.fail_at:
            raise RuntimeError(f"simulated crash at step {step}")
        lr = lr_at(step, args.steps, args.lr, warmup)
        progress += speed * lr / args.lr * (1.0 / 300)
        if rng.random() < 0.002 + 0.01 * instability:        # occasional loss spike
            spike = rng.uniform(0.3, 1.2) * (1 + instability)
        spike *= 0.93
        clean = floor + (4.6 - floor) / (1 + progress) ** 1.1
        loss = clean * (1 + rng.gauss(0, noise)) + spike
        grad_norm = (0.4 + 2.5 / (1 + progress) + 4 * spike + instability) * math.exp(rng.gauss(0, 0.25))
        metrics = {
            "train/loss": loss,
            "train/grad_norm": grad_norm,
            "lr": lr,
            "throughput/tokens_per_s": base_tps * (1 + rng.gauss(0, 0.03)),
            "sys/gpu_mem_gb": mem_gb * min(1.0, 0.6 + step / 50) + rng.uniform(0, 0.03),
        }
        if step % args.eval_every == 0 or step == args.steps - 1:
            eval_loss = clean + gen_gap * min(1.0, progress / 5) + rng.gauss(0, 0.01)
            metrics["eval/loss"] = eval_loss
            metrics["eval/acc"] = 1 / (1 + math.exp(2.2 * (eval_loss - 2.6))) + rng.gauss(0, 0.004)
        lossline.log(metrics)
        if args.sleep:
            time.sleep(args.sleep)

    run.summary["final/train_loss"] = loss
    lossline.finish()


if __name__ == "__main__":
    main()
