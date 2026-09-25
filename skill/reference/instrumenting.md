# Instrumenting training code

Recipes for common setups. They all follow the same rules as the main skill file: pass
`step=`, name metrics `group/name`, log every N steps, and log from rank 0 only.

## Contents

- Plain PyTorch loop (with averaging and DDP)
- Hugging Face `Trainer`
- PyTorch Lightning
- Code that already uses wandb
- Sweeps
- Resuming from a checkpoint
- Notebooks
- What to log

## Plain PyTorch loop

```python
import os
import torch
import lossline

rank0 = int(os.environ.get("RANK", 0)) == 0
if rank0:
    lossline.init(project="seqmem", name=args.name, config=vars(args))

log_every, running, n = 20, 0.0, 0
for step, batch in enumerate(loader):
    loss = model(batch).loss
    loss.backward()
    grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    opt.step(); sched.step(); opt.zero_grad(set_to_none=True)

    running += loss.detach(); n += 1          # stays on the GPU: no sync per step
    if rank0 and step % log_every == 0:
        lossline.log({
            "train/loss": (running / n).item(),  # one sync per log_every steps
            "train/grad_norm": grad_norm.item(),
            "optim/lr": sched.get_last_lr()[0],
            "sys/gpu_mem_gb": torch.cuda.max_memory_allocated() / 1e9,
        }, step=step)
        running, n = 0.0, 0

    if rank0 and step % args.eval_every == 0:
        lossline.log({"eval/loss": evaluate(model)}, step=step)
```

Evaluation that all ranks take part in still runs on every rank; only the `log` call is
guarded.

## Hugging Face Trainer

Turn off other reporters with `report_to="none"` and add a callback:

```python
import lossline
from transformers import TrainerCallback

class LosslineCallback(TrainerCallback):
    def __init__(self, project, name=None):
        self.project, self.name = project, name

    def on_train_begin(self, args, state, control, **kwargs):
        if state.is_world_process_zero:
            lossline.init(project=self.project, name=self.name, config=args.to_dict())

    def on_log(self, args, state, control, logs=None, **kwargs):
        if not (state.is_world_process_zero and logs):
            return
        out = {}
        for key, value in logs.items():
            if key.startswith("eval_"):
                out[f"eval/{key[5:]}"] = value
            elif key == "learning_rate":
                out["optim/lr"] = value
            elif key in ("loss", "grad_norm", "epoch"):
                out[f"train/{key}"] = value
        if out:
            lossline.log(out, step=state.global_step)

    def on_train_end(self, args, state, control, **kwargs):
        if state.is_world_process_zero:
            lossline.finish()

trainer = Trainer(..., args=TrainingArguments(..., report_to="none", logging_steps=10),
                  callbacks=[LosslineCallback("my-model", name="lora-r16")])
```

`logging_steps` sets how often `on_log` fires. Evaluation metrics arrive through the same
hook with an `eval_` prefix.

## PyTorch Lightning

Keep using `self.log(...)` in the module and forward what Lightning collects:

```python
import lightning as L
import lossline

class LosslineCallback(L.Callback):
    def __init__(self, project, name=None, every=10):
        self.project, self.name, self.every = project, name, every

    def on_train_start(self, trainer, module):
        if trainer.is_global_zero:
            lossline.init(project=self.project, name=self.name, config=dict(module.hparams))

    def _send(self, trainer, prefixes):
        metrics = {k: v for k, v in trainer.callback_metrics.items() if k.startswith(prefixes)}
        if metrics:
            lossline.log(metrics, step=trainer.global_step)

    def on_train_batch_end(self, trainer, module, outputs, batch, batch_idx):
        if trainer.is_global_zero and trainer.global_step % self.every == 0:
            self._send(trainer, ("train",))

    def on_validation_epoch_end(self, trainer, module):
        if trainer.is_global_zero and not trainer.sanity_checking:
            self._send(trainer, ("val", "eval"))

    def on_train_end(self, trainer, module):
        if trainer.is_global_zero:
            lossline.finish()
```

Log from the module as `self.log("train/loss", loss)` and `self.log("val/loss", ...)` so
the prefixes match. `callback_metrics` holds 0-d tensors, which lossline accepts.

## Code that already uses wandb

`init(project=, name=, config=)`, `log(dict, step=)` and `finish()` match wandb, so
often this is enough:

```python
import lossline as wandb
```

Then remove what lossline doesn't have: `wandb.watch`, `wandb.Image`, `wandb.Table`,
`wandb.Artifact`, `wandb.define_metric`, `wandb.config.x` attribute access (keep your own
config object instead), and `entity=` / `mode=` arguments. `wandb.run.summary` works as
`lossline.run.summary`. Search for every `wandb.` call rather than assuming.

## Sweeps

One run per configuration, all in one project, with the swept values in `config` so
`lossline compare` shows exactly what differs:

```python
for lr in (1e-4, 3e-4, 1e-3):
    with lossline.init(project="seqmem", name=f"lr{lr:g}", config={**base, "lr": lr}, tags=["lr-sweep"]):
        train(lr)
```

The `with` block finishes the run, marking it failed if the body raises.

## Resuming from a checkpoint

A resumed job is a new run; lossline never appends to a finished run. Keep the curve
continuous by continuing the step count and saying where it came from:

```python
lossline.init(project="seqmem", name="wide-lr3e-4", config={**cfg, "resumed_from": ckpt_path},
              tags=["resumed"])
lossline.log({...}, step=global_step)  # global_step restored from the checkpoint
```

## Notebooks

The run finishes automatically when the kernel exits, which in a notebook may be much
later. Call `lossline.finish()` at the end of the training cell. Calling `lossline.init`
again finishes the previous run first.

## What to log

- **Always:** the training loss, learning rate, and gradient norm (before clipping).
  Divergence shows up in the gradient norm first.
- **Evaluation:** loss plus the task metric (accuracy, BLEU, reward, pass@k) at the same
  `step` as training.
- **Health:** `throughput/samples_per_s` or `tokens_per_s`, and
  `sys/gpu_mem_gb = torch.cuda.max_memory_allocated() / 1e9`. A drop in throughput or
  creeping memory explains many "why is it slow" and OOM questions.
- **RL:** `rollout/ep_return`, `rollout/ep_len`, `train/policy_loss`, `train/value_loss`,
  `train/entropy`, `train/approx_kl`.

Only scalars. Keep large outputs (samples, images, checkpoints) in files next to the run
and put their paths in `notes` or `config`.
