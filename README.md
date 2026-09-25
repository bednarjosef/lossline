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
hf buckets create lossline --private     # once
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

```bash
LOSSLINE_BUCKET=<you>/lossline python train.py
```

Then open the web app and sign in with Hugging Face.

On a rented GPU box, give the script its own
[fine-grained token](https://huggingface.co/settings/tokens) and delete it when the box
is gone. To limit what a leaked token could touch, keep the logs bucket in a separate
Hugging Face organization and scope the token to that organization only.

Without `LOSSLINE_BUCKET`, runs are written to `./lossline/` only.

## Reading runs from the terminal

```bash
lossline ls                         # projects
lossline ls my-model                # runs, with status and latest values
lossline show my-model/<run>        # config, machine, per-metric stats and trends
lossline compare my-model/<a> my-model/<b>
lossline tail my-model/<run> -f     # follow a live run
lossline export my-model/<run> --format csv
```

Every command takes `--bucket` (default `$LOSSLINE_BUCKET`) or `--dir` for local runs,
and `ls`, `show` and `compare` take `--json`.

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
