<script lang="ts">
  import { store } from '../lib/store.svelte'
  import { color, projectPath, ui } from '../lib/ui.svelte'
  import { ago, fmt } from '../lib/format'
  import type { Project } from '../lib/types'
  import Spark from './Spark.svelte'

  const lead = (p: Project) => p.runs.find((r) => r.status === 'running') ?? p.runs[0]

  $effect(() => {
    for (const p of store.projects) {
      const r = lead(p)
      if (r && !store.previews[r.key]) store.preview(r.key)
    }
  })
</script>

<main class="home">
  <header>
    <h1>Projects</h1>
    {#if store.state === 'ready'}
      <span class="count">{store.projects.length}</span>
    {/if}
  </header>

  {#if store.state === 'loading'}
    <div class="grid">
      {#each [0, 1, 2] as i (i)}
        <div class="tile ghost" style:animation-delay="{i * 120}ms"></div>
      {/each}
    </div>
  {:else if store.projects.length === 0}
    <div class="empty">
      <h2>No runs in {store.source?.name} yet.</h2>
      <pre><code>import lossline
lossline.init(project="my-model", config=cfg)
lossline.log(&#123;"train/loss": loss&#125;)</code></pre>
      <p class="mono">LOSSLINE_BUCKET={store.source?.name} python train.py</p>
    </div>
  {:else}
    <div class="grid">
      {#each store.projects as p, i (p.name)}
        {@const r = lead(p)}
        {@const pv = store.previews[r.key]}
        {@const slot = ui.shown(p.name, p.runs).get(r.key)}
        <a class="tile" href={projectPath(p.name)} style:animation-delay="{i * 50}ms">
          <div class="head">
            <h2>{p.name}</h2>
            {#if p.live}
              <span class="live"><span class="pulse"></span>{p.live} live</span>
            {:else}
              <span class="when">{ago(p.updated, store.now)}</span>
            {/if}
          </div>
          <div class="spark">
            {#if pv}
              <Spark values={pv.values} color={slot !== undefined ? color(slot) : 'var(--ink-2)'} height={64} />
            {/if}
          </div>
          <div class="foot">
            <span class="metric mono">{pv?.metric ?? ''}</span>
            <span class="val mono">{pv ? fmt(pv.values.at(-1)) : ''}</span>
            <span class="runs">{p.runs.length} {p.runs.length === 1 ? 'run' : 'runs'}</span>
          </div>
        </a>
      {/each}
    </div>
  {/if}
</main>

<style>
  .home {
    max-width: 1180px;
    margin: 0 auto;
    padding: 40px var(--gutter) 80px;
  }
  header {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 26px;
  }
  h1 {
    font-size: 34px;
    letter-spacing: -0.04em;
  }
  .count {
    font-family: var(--mono);
    font-size: 13px;
    color: var(--ink-3);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(300px, 100%), 1fr));
    gap: 14px;
  }
  .tile {
    display: grid;
    gap: 14px;
    padding: 18px 18px 16px;
    border-radius: var(--r-lg);
    background: var(--raised);
    box-shadow: 0 0 0 1px var(--line);
    transition:
      box-shadow 0.25s,
      transform 0.25s var(--ease);
    animation: rise 0.6s var(--ease) both;
  }
  .tile:hover {
    transform: translateY(-2px);
    box-shadow:
      0 0 0 1px var(--line-2),
      var(--shadow);
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(10px);
    }
  }
  .ghost {
    height: 168px;
    background: linear-gradient(100deg, var(--raised) 30%, var(--sunken) 50%, var(--raised) 70%) 0 0 / 300% 100%;
    animation:
      rise 0.6s var(--ease) both,
      shimmer 1.6s linear infinite;
  }
  @keyframes shimmer {
    to {
      background-position: -150% 0;
    }
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }
  h2 {
    font-size: 19px;
    letter-spacing: -0.025em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .live {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 12.5px;
    font-weight: 550;
    color: var(--ink-2);
  }
  .when {
    font-size: 12.5px;
    color: var(--ink-3);
  }
  .spark {
    height: 64px;
  }
  .foot {
    display: grid;
    grid-template-columns: auto auto 1fr;
    align-items: baseline;
    gap: 10px;
    font-size: 12.5px;
  }
  .metric {
    color: var(--ink-3);
    font-size: 10.5px;
  }
  .val {
    color: var(--ink);
    font-size: 11.5px;
  }
  .runs {
    justify-self: end;
    color: var(--ink-3);
  }
  .empty {
    display: grid;
    gap: 16px;
    max-width: 560px;
  }
  .empty h2 {
    font-size: 22px;
    white-space: normal;
  }
  .empty pre {
    margin: 0;
    padding: 18px 20px;
    border-radius: 14px;
    background: var(--raised);
    box-shadow: 0 0 0 1px var(--line);
    overflow-x: auto;
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.75;
  }
  .empty p {
    color: var(--ink-2);
    font-size: 12px;
  }
</style>
