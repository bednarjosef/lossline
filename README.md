# lossline

Experiment tracking with no server. Your training script writes runs to your own
Hugging Face bucket, and a static web page reads them straight from there, live.

- **Nothing to host or pay for.** Runs are plain files in a bucket you own. The web app is
  static files; use the hosted copy or serve your own.
- **Nothing sees your data.** The web app signs you in with Hugging Face and talks to
  Hugging Face directly from your browser. There is no lossline backend.
- **Live.** Charts update a few seconds after your script logs, on desktop or phone.
- **Agent-friendly.** Runs are JSON lines, and the `lossline` CLI prints compact text
  summaries an agent can read without screenshots.

## Quick start

```bash
pip install lossline
```

```python
import lossline

lossline.init(project="my-model", config={"lr": 3e-4, "batch_size": 64})
for step in range(10_000):
    loss = train_step()
    lossline.log({"train/loss": loss})
lossline.finish()
```

Runs go to one private bucket per user, `<your hf user>/lossline`. The first run creates
it, and the [web app](https://bednarjosef.github.io/lossline/) finds it on its own after
you sign in with Hugging Face. Inside the bucket, runs are grouped by project.

The logger uses your Hugging Face login (`hf auth login` or `HF_TOKEN`). On a machine
that isn't logged in, pass a token:

```bash
HF_TOKEN=hf_... python train.py
```

On a rented GPU box, give the script its own
[fine-grained token](https://huggingface.co/settings/tokens) and delete it when the box
is gone. To limit what a leaked token could touch, keep the logs bucket in a separate
Hugging Face organization and scope the token to that organization only.

Runs are always written to `./lossline/` as well. To use a different bucket, pass
`bucket="owner/name"` or set `LOSSLINE_BUCKET`. To keep runs local only, pass
`bucket=False` or set `LOSSLINE_BUCKET=none`.

## Reading runs from the terminal

```bash
lossline ls                         # projects
lossline ls my-model                # runs, with status and latest values
lossline show my-model/<run>        # config, machine, per-metric stats and trends
lossline compare my-model/<a> my-model/<b>
lossline tail my-model/<run> -f     # follow a live run
lossline wait my-model/latest --until 'eval/acc>=0.9'   # block until done, failed, stalled or target
lossline export my-model/<run> --format csv
lossline mv my-model/'lr-*' my-model-lr-sweep   # move runs to another project
lossline rm scratch/'*'             # lists what would be deleted; add --yes to delete
```

Commands read your default bucket unless given `--bucket` or `--dir` (for local runs).
`ls`, `show` and `compare` take `--json` and `-m 'eval/*'` to filter metrics.

## For coding agents

`skill/` is a Claude Code skill that teaches an agent to add lossline logging to training
code, run it on remote boxes, check on runs, wait for them, and read the curves (spotting
divergence, plateaus, overfitting and stalled runs). Install it with:

```bash
git clone https://github.com/bednarjosef/lossline
ln -s "$PWD/lossline/skill" ~/.claude/skills/lossline
```

`lossline wait` is made for agents: start it in the background and it exits when the
run finishes (0), fails (2), stalls (3) or times out (4), or when a target like
`--until 'eval/acc>=0.9'` or `--step 20000` is reached (0).

## How it works

A run is a folder in the bucket:

```
<project>/<run>/meta.json             status, config, latest values, machine
<project>/<run>/metrics/000000.jsonl  one JSON object per logged step
```

The logger buffers in memory and flushes every 15 seconds from a background thread:
it appends to the local files, then uploads `meta.json` and the growing segment in one
request. Only the last segment ever changes, and it only grows, so the web app follows
a live run with HTTP range requests for the new bytes, triggered by the bucket's change
stream. The full format is in [docs/format.md](docs/format.md).

## Web app

`web/` is a Svelte app built to static files.

```bash
cd web
npm install
npm run dev                         # http://localhost:5190, "Explore an example" works offline
LOSSLINE_SITE_URL=https://you.github.io/lossline/ npm run build
```

`LOSSLINE_SITE_URL` is the URL the app will be served from. The build then emits
`oauth-client.json`, a client metadata document whose own URL is the OAuth client ID,
so "Sign in with Hugging Face" works without registering an app. Without it, the app
offers token sign-in only.

The included GitHub Actions workflow builds and deploys to GitHub Pages on every push
to `main`. To self-host from a fork, enable Pages (source: GitHub Actions) and push.

Sign-in asks for the `read-repos` scope, which lets the page read your repositories
and buckets. The token stays in your browser and is only ever sent to huggingface.co.

## License

MIT
