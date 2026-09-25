<script lang="ts">
  import { onMount } from 'svelte'
  import { slide } from 'svelte/transition'
  import { oauthAvailable, startSignIn } from '../lib/auth'
  import { cssVar, ui } from '../lib/ui.svelte'
  import Wordmark from './Wordmark.svelte'
  import Icon from './Icon.svelte'

  let { error, ondemo, ontoken }: { error: string; ondemo: () => void; ontoken: (t: string) => void } = $props()

  let tokenMode = $state(!oauthAvailable)
  let token = $state('')
  let canvas: HTMLCanvasElement

  // Background: a handful of runs training forever, drawn the way the app draws them.
  onMount(() => {
    const ctx = canvas.getContext('2d')!
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches
    let raf = 0
    let colors: string[] = []
    let grid = ''
    const readColors = () => {
      colors = [1, 2, 3, 7, 5].map((i) => cssVar(`--c${i}`))
      grid = cssVar('--line')
    }
    readColors()

    const runs = colors.map((_, i) => ({
      floor: 0.16 + i * 0.07 + Math.random() * 0.04,
      speed: 0.7 + Math.random() * 0.9,
      noise: 0.012 + Math.random() * 0.01,
      phase: -i * 0.18,
      seed: Math.random() * 1000,
    }))

    const draw = (t: number) => {
      const dpr = devicePixelRatio || 1
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr
        canvas.height = h * dpr
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      ctx.strokeStyle = grid
      ctx.lineWidth = 1
      const step = Math.max(64, Math.round(h / 9))
      for (let y = h % step; y < h; y += step) {
        ctx.beginPath()
        ctx.moveTo(0, y + 0.5)
        ctx.lineTo(w, y + 0.5)
        ctx.stroke()
      }

      const cycle = 14000
      runs.forEach((r, i) => {
        const p = still ? 0.85 : Math.min(1, Math.max(0, ((t / cycle + r.phase + 1) % 1.25) / 1))
        const n = Math.floor(p * 260)
        if (n < 2) return
        ctx.beginPath()
        let last = [0, 0]
        for (let k = 0; k <= n; k++) {
          const s = k / 260
          const base = r.floor + (0.78 - r.floor) * Math.pow(1 + s * 40 * r.speed, -0.55)
          const wob = (Math.sin(k * 0.19 + r.seed) * 0.55 + Math.sin(k * 0.53 + r.seed * 2) * 0.3 + Math.sin(k * 1.31 + r.seed * 3) * 0.15) * r.noise * (0.5 + base)
          const x = s * w * 1.02
          const y = h * (1.02 - base * 1.05) + wob * h
          last = [x, y]
          if (k) ctx.lineTo(x, y)
          else ctx.moveTo(x, y)
        }
        ctx.strokeStyle = colors[i]
        ctx.globalAlpha = 0.8
        ctx.lineWidth = 2
        ctx.lineJoin = 'round'
        ctx.stroke()
        ctx.globalAlpha = 1
        if (p < 1) {
          ctx.beginPath()
          ctx.arc(last[0], last[1], 4, 0, Math.PI * 2)
          ctx.fillStyle = colors[i]
          ctx.fill()
        }
      })
      if (!still) raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    const un = $effect.root(() => {
      $effect(() => {
        void ui.dark
        readColors()
      })
    })
    return () => {
      cancelAnimationFrame(raf)
      un()
    }
  })

  function submit(e: SubmitEvent) {
    e.preventDefault()
    if (token.trim()) ontoken(token)
  }
</script>

<main class="signin">
  <canvas bind:this={canvas} aria-hidden="true"></canvas>
  <div class="veil"></div>

  <button class="icon-btn theme" onclick={() => ui.toggleTheme()} aria-label="Switch theme">
    <Icon name={ui.dark ? 'sun' : 'moon'} />
  </button>

  <section class="panel">
    <Wordmark size={22} />
    <h1>Watch your runs train.</h1>
    <p class="lede">Live charts straight from your own Hugging Face bucket. No servers, no API keys to hand out.</p>

    <div class="actions">
      {#if oauthAvailable}
        <button class="btn btn-primary btn-lg" onclick={startSignIn}>
          Continue with Hugging Face
          <Icon name="arrow" size={17} />
        </button>
      {/if}

      {#if tokenMode}
        <form class="token" onsubmit={submit} transition:slide={{ duration: 260 }}>
          <label class="sr-only" for="token">Hugging Face access token</label>
          <input id="token" class="field" type="password" placeholder="hf_…" autocomplete="off" spellcheck="false" bind:value={token} />
          <button class="btn {oauthAvailable ? 'btn-line' : 'btn-primary'}" type="submit" disabled={!token.trim()}>Open</button>
        </form>
        <a class="hint" href="https://huggingface.co/settings/tokens/new?tokenType=read" target="_blank" rel="noreferrer">Create a read token</a>
      {:else}
        <button class="btn btn-ghost" onclick={() => (tokenMode = true)}>Use an access token</button>
      {/if}
    </div>

    {#if error}
      <p class="error" role="alert">{error}</p>
    {/if}

    <button class="demo" onclick={ondemo}>
      Explore an example
      <Icon name="arrow" size={15} />
    </button>
  </section>
</main>

<style>
  .signin {
    position: relative;
    min-height: 100dvh;
    display: grid;
    align-items: end;
    padding: var(--gutter);
    padding-bottom: max(var(--gutter), 8vh);
    overflow: hidden;
    background: var(--ground);
  }
  canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }
  .veil {
    position: absolute;
    inset: 0;
    background:
      linear-gradient(to right, var(--ground) 0%, color-mix(in srgb, var(--ground) 55%, transparent) 38%, transparent 70%),
      linear-gradient(to top, var(--ground) 6%, transparent 45%);
  }
  @media (max-width: 700px) {
    canvas {
      height: 56%;
    }
    .veil {
      background: linear-gradient(to top, var(--ground) 46%, transparent 64%);
    }
  }
  .theme {
    position: absolute;
    top: calc(env(safe-area-inset-top, 0px) + 14px);
    right: var(--gutter);
    z-index: 2;
  }
  .panel {
    position: relative;
    z-index: 1;
    display: grid;
    gap: 18px;
    max-width: 520px;
    animation: rise 0.9s var(--ease) both;
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(14px);
    }
  }
  h1 {
    font-size: clamp(38px, 6.2vw, 64px);
    line-height: 0.98;
    letter-spacing: -0.045em;
    font-weight: 650;
    margin-top: 10px;
  }
  .lede {
    font-size: 17px;
    color: var(--ink-2);
    max-width: 42ch;
  }
  .actions {
    display: grid;
    justify-items: start;
    gap: 10px;
    margin-top: 8px;
  }
  .token {
    display: flex;
    gap: 8px;
    width: min(420px, 100%);
  }
  .token .field {
    font-family: var(--mono);
    font-size: 12.5px;
    height: 40px;
  }
  .token .btn {
    height: 40px;
  }
  .token .btn:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .hint {
    font-size: 13px;
    color: var(--ink-3);
    text-decoration: underline;
    text-decoration-color: var(--line-2);
    text-underline-offset: 3px;
  }
  .hint:hover {
    color: var(--ink);
  }
  .error {
    color: var(--failed);
    font-size: 13.5px;
  }
  .demo {
    justify-self: start;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 12px;
    font-size: 13.5px;
    font-weight: 550;
    color: var(--ink-2);
    transition:
      color 0.2s,
      gap 0.25s var(--ease);
  }
  .demo:hover {
    color: var(--ink);
    gap: 10px;
  }
</style>
