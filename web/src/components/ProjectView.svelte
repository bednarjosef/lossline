<script lang="ts">
  import { onMount } from 'svelte'
  import { fade, fly } from 'svelte/transition'
  import { store } from '../lib/store.svelte'
  import { color, projectPath, router, ui } from '../lib/ui.svelte'
  import { direction, groups, pickHero, splitName } from '../lib/metrics'
  import { fmt, fmtStep } from '../lib/format'
  import type { Line } from '../lib/series'
  import Chart from './Chart.svelte'
  import RunList from './RunList.svelte'
  import RunSheet from './RunSheet.svelte'
  import Icon from './Icon.svelte'

  let { project, runId }: { project: string; runId: string | null } = $props()

  const runs = $derived(store.runs.filter((r) => r.project === project))
  const shown = $derived(ui.shown(project, runs))
  const names = $derived(new Map(runs.map((r) => [r.key, r.id])))
  const live = $derived(runs.filter((r) => r.status === 'running').length)

  $effect(() => ui.syncSelection(project, runs))
  $effect(() => {
    for (const key of shown.keys()) store.ensure(key)
  })

  onMount(() => () => (ui.hoverRun = null))

  // a zoom range means nothing on the other axis
  $effect(() => {
    void ui.x
    ui.zoom = null
  })

  const metricNames = $derived.by(() => {
    void store.tick
    const set = new Set<string>()
    for (const key of shown.keys()) {
      const d = store.metrics(key)
      if (d) for (const m of d.metrics.keys()) set.add(m)
      else for (const m of Object.keys(store.run(key)?.meta?.summary ?? {})) if (m[0] !== '_') set.add(m)
    }
    return [...set]
  })

  const hero = $derived(ui.hero[project] && metricNames.includes(ui.hero[project]) ? ui.hero[project] : pickHero(metricNames))
  const others = $derived(groups(metricNames.filter((m) => m !== hero)).flatMap((g) => g.metrics))

  // the run the headline number describes: the newest live run shown, else the newest shown
  const focus = $derived.by(() => {
    const vis = runs.filter((r) => shown.has(r.key))
    return vis.find((r) => r.status === 'running') ?? vis[0] ?? null
  })

  function lines(metric: string): Line[] {
    void store.tick
    const out: Line[] = []
    for (const [key, slot] of shown) {
      const d = store.metrics(key)
      const s = d?.metrics.get(metric)
      if (d && s) out.push({ key, slot, series: s, t0: d.t0 })
    }
    return out.sort((a, b) => a.slot - b.slot)
  }

  function last(key: string | undefined, metric: string | null) {
    if (!key || !metric) return null
    void store.tick
    const s = store.metrics(key)?.metrics.get(metric)
    if (!s) return null
    for (let i = s.value.length - 1; i >= 0; i--) if (s.value[i] != null) return { v: s.value[i]!, step: s.step[i] }
    return null
  }

  function best(key: string | undefined, metric: string | null) {
    if (!key || !metric) return null
    const dir = direction(metric)
    if (!dir) return null
    void store.tick
    const s = store.metrics(key)?.metrics.get(metric)
    if (!s) return null
    let bi = -1
    for (let i = 0; i < s.value.length; i++) {
      const v = s.value[i]
      if (v == null) continue
      if (bi < 0 || (dir < 0 ? v < s.value[bi]! : v > s.value[bi]!)) bi = i
    }
    return bi < 0 ? null : { v: s.value[bi]!, step: s.step[bi] }
  }

  const heroNow = $derived(last(focus?.key, hero))
  const heroBest = $derived(best(focus?.key, hero))
  const loaded = $derived.by(() => {
    void store.tick
    return [...shown.keys()].some((k) => store.metrics(k))
  })

  function promote(metric: string) {
    ui.hero[project] = metric
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function positive(metric: string) {
    return lines(metric).every((l) => l.series.value.every((v) => v == null || v > 0))
  }

  function toggleLog(metric: string) {
    ui.logY[metric] = !ui.logY[metric]
  }

  let runsOpen = $state(false)
  let metricMenu = $state(false)
  let metricQuery = $state('')
  const allMetrics = $derived(groups(metricNames))

  let heroH = $state(360)
  onMount(() => {
    const size = () => (heroH = Math.round(Math.max(240, Math.min(440, innerHeight * 0.42))))
    size()
    addEventListener('resize', size)
    return () => removeEventListener('resize', size)
  })

  function outside(node: HTMLElement, close: () => void) {
    const h = (e: PointerEvent) => !node.contains(e.target as Node) && close()
    const k = (e: KeyboardEvent) => e.key === 'Escape' && close()
    document.addEventListener('pointerdown', h)
    document.addEventListener('keydown', k)
    return { destroy: () => (document.removeEventListener('pointerdown', h), document.removeEventListener('keydown', k)) }
  }
</script>

<div class="project">
  <aside class="rail">
    <RunList {project} {runs} {shown} {hero} />
  </aside>

  <main>
    <div class="bar">
      <div class="title">
        <h1>{project}</h1>
        <p>
          {runs.length} {runs.length === 1 ? 'run' : 'runs'}
          {#if live}<span class="dot">·</span><span class="pulse"></span> {live} live{/if}
        </p>
      </div>
      <div class="controls">
        {#if ui.zoom}
          <button class="chip" onclick={() => (ui.zoom = null)} transition:fly={{ x: 8, duration: 200 }}>
            <Icon name="reset" size={14} />Reset zoom
          </button>
        {/if}
        <div class="seg" role="radiogroup" aria-label="Horizontal axis">
          <button role="radio" aria-checked={ui.x === 'step'} class:on={ui.x === 'step'} onclick={() => (ui.x = 'step')}>Step</button>
          <button role="radio" aria-checked={ui.x === 'time'} class:on={ui.x === 'time'} onclick={() => (ui.x = 'time')}>Time</button>
          <span class="thumb" class:right={ui.x === 'time'}></span>
        </div>
        <label class="smooth">
          <span>Smoothing</span>
          <input type="range" min="0" max="0.99" step="0.01" bind:value={ui.smoothing} style:--p="{(ui.smoothing / 0.99) * 100}%" />
          <span class="mono num">{ui.smoothing.toFixed(2)}</span>
        </label>
        <button class="btn btn-line runs-btn" onclick={() => (runsOpen = true)}><Icon name="runs" size={16} />Runs</button>
      </div>
    </div>

    {#if hero}
      <section class="hero">
        <header>
          <div class="pick" use:outside={() => (metricMenu = false)}>
            <button class="metric" onclick={() => (metricMenu = !metricMenu)} aria-expanded={metricMenu}>
              <span>{#if splitName(hero).group}<span class="grp">{splitName(hero).group}/</span>{/if}{splitName(hero).leaf}</span>
              <Icon name="chevron" size={16} />
            </button>
            {#if metricMenu}
              <div class="menu" transition:fly={{ y: -6, duration: 180 }}>
                <input class="field" placeholder="Find a metric" bind:value={metricQuery} autocomplete="off" spellcheck="false" />
                <div class="menu-list">
                  {#each allMetrics as g (g.group)}
                    {@const ms = g.metrics.filter((m) => m.toLowerCase().includes(metricQuery.toLowerCase()))}
                    {#if ms.length}
                      {#if g.group}<div class="label">{g.group}</div>{/if}
                      {#each ms as m (m)}
                        <button class:on={m === hero} onclick={() => ((metricMenu = false), (metricQuery = ''), promote(m))}>
                          {splitName(m).leaf}
                          {#if m === hero}<Icon name="check" size={15} />{/if}
                        </button>
                      {/each}
                    {/if}
                  {/each}
                </div>
              </div>
            {/if}
          </div>

          <div class="readout">
            {#if heroNow && focus}
              {#key focus.key}
                <div class="now" in:fade={{ duration: 200 }}>
                  <span class="big">{fmt(heroNow.v, 5)}</span>
                  <span class="at">
                    <i style:background={color(shown.get(focus.key) ?? 0)}></i>{focus.id}
                    <span class="mono">· step {fmtStep(heroNow.step)}</span>
                  </span>
                </div>
              {/key}
              {#if heroBest && heroBest.step !== heroNow.step}
                <div class="best">
                  <span class="label">Best</span>
                  <span class="mono">{fmt(heroBest.v, 5)}</span>
                  <span class="mono at-step">step {fmtStep(heroBest.step)}</span>
                </div>
              {/if}
            {/if}
          </div>

          {#if positive(hero)}
            <button class="toggle" class:on={ui.logY[hero]} onclick={() => toggleLog(hero)} aria-pressed={!!ui.logY[hero]}>
              <Icon name="log" size={15} />Log
            </button>
          {/if}
        </header>

        {#key hero}
          <div in:fade={{ duration: 260 }}>
            <Chart lines={lines(hero)} height={heroH} big log={!!ui.logY[hero] && positive(hero)} {names} />
          </div>
        {/key}

        <div class="legend">
          {#each runs.filter((r) => shown.has(r.key)) as r (r.key)}
            <span><i style:background={color(shown.get(r.key)!)}></i>{r.id}</span>
          {/each}
        </div>
      </section>
    {:else if store.state === 'ready' && !loaded && shown.size}
      <section class="hero wait"></section>
    {:else if store.state === 'ready' && runs.length === 0}
      <div class="none">
        <h2>No runs here.</h2>
        <a class="btn btn-line" href="#/">All projects</a>
      </div>
    {/if}

    {#if others.length}
      <div class="cards">
        {#each others as m, i (m)}
          {@const cur = last(focus?.key, m)}
          {@const n = splitName(m)}
          <article class="card" style:animation-delay="{Math.min(i, 12) * 35}ms">
            <header>
              <button class="name" onclick={() => promote(m)}>{#if n.group}<span class="grp">{n.group}/</span>{/if}{n.leaf}</button>
              {#if positive(m)}
                <button class="toggle small" class:on={ui.logY[m]} onclick={() => toggleLog(m)} aria-pressed={!!ui.logY[m]} aria-label="Log scale">
                  <Icon name="log" size={14} />
                </button>
              {/if}
              <span class="val mono">{cur ? fmt(cur.v) : ''}</span>
            </header>
            <Chart lines={lines(m)} height={168} log={!!ui.logY[m] && positive(m)} {names} onpick={() => promote(m)} />
          </article>
        {/each}
      </div>
    {/if}
  </main>
</div>

{#if runsOpen}
  <div class="sheet-scrim" transition:fade={{ duration: 200 }} onclick={() => (runsOpen = false)} aria-hidden="true"></div>
  <div class="runs-sheet" transition:fly={{ y: 400, duration: 320, opacity: 1 }}>
    <div class="grab"></div>
    <RunList {project} {runs} {shown} {hero} onnavigate={() => (runsOpen = false)} />
  </div>
{/if}

{#if runId}
  {@const run = runs.find((r) => r.id === runId)}
  {#if run}
    <RunSheet {run} slot={shown.get(run.key)} onclose={() => router.go(projectPath(project))} />
  {/if}
{/if}

<style>
  .project {
    display: grid;
    grid-template-columns: 290px minmax(0, 1fr);
    min-height: calc(100dvh - var(--top));
  }
  .rail {
    position: sticky;
    top: var(--top);
    height: calc(100dvh - var(--top));
    overflow-y: auto;
    padding: 22px 12px 40px var(--gutter);
    border-right: 1px solid var(--line);
  }
  main {
    padding: 22px var(--gutter) 90px;
    display: grid;
    gap: 22px;
    align-content: start;
    min-width: 0;
  }

  /* ---- top row */
  .bar {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px 24px;
  }
  .title h1 {
    font-size: 30px;
    letter-spacing: -0.04em;
    line-height: 1.1;
  }
  .title p {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 4px;
    color: var(--ink-3);
    font-size: 13px;
  }
  .title .pulse {
    width: 6px;
    height: 6px;
  }
  .dot {
    color: var(--line-2);
  }
  .controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding-inline: 11px;
    border-radius: 99px;
    background: var(--ink);
    color: var(--ground);
    font-size: 12.5px;
    font-weight: 550;
  }
  .seg {
    position: relative;
    display: grid;
    grid-template-columns: 1fr 1fr;
    padding: 3px;
    border-radius: 11px;
    background: var(--wash);
  }
  .seg button {
    position: relative;
    z-index: 1;
    height: 28px;
    padding-inline: 14px;
    font-size: 12.5px;
    font-weight: 550;
    color: var(--ink-3);
    transition: color 0.2s;
  }
  .seg button.on {
    color: var(--ink);
  }
  .thumb {
    position: absolute;
    top: 3px;
    bottom: 3px;
    left: 3px;
    width: calc(50% - 3px);
    border-radius: 8px;
    background: var(--raised);
    box-shadow:
      0 0 0 1px var(--line),
      0 1px 3px rgba(0, 0, 0, 0.06);
    transition: transform 0.3s var(--ease);
  }
  .thumb.right {
    transform: translateX(100%);
  }
  .smooth {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 34px;
    padding-inline: 12px;
    border-radius: 11px;
    background: var(--wash);
    font-size: 12.5px;
    font-weight: 550;
    color: var(--ink-3);
  }
  .smooth .mono {
    width: 3.2em;
    color: var(--ink);
    font-size: 11px;
  }
  input[type='range'] {
    appearance: none;
    width: 110px;
    height: 4px;
    border-radius: 4px;
    background: linear-gradient(to right, var(--ink) var(--p), var(--line-2) var(--p));
    cursor: pointer;
  }
  input[type='range']::-webkit-slider-thumb {
    appearance: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--raised);
    box-shadow:
      0 0 0 1.5px var(--ink),
      0 1px 3px rgba(0, 0, 0, 0.2);
    transition: transform 0.15s;
  }
  input[type='range']::-moz-range-thumb {
    width: 14px;
    height: 14px;
    border: 0;
    border-radius: 50%;
    background: var(--raised);
    box-shadow:
      0 0 0 1.5px var(--ink),
      0 1px 3px rgba(0, 0, 0, 0.2);
  }
  input[type='range']:active::-webkit-slider-thumb {
    transform: scale(1.2);
  }
  .runs-btn {
    display: none;
  }

  /* ---- hero */
  .hero {
    position: relative;
    padding: 18px 18px 14px 12px;
    border-radius: 20px;
    background: var(--raised);
    box-shadow: 0 0 0 1px var(--line);
    animation: rise 0.6s var(--ease) both;
  }
  .hero.wait {
    height: 460px;
    background: linear-gradient(100deg, var(--raised) 30%, var(--sunken) 50%, var(--raised) 70%) 0 0 / 300% 100%;
    animation: shimmer 1.6s linear infinite;
  }
  @keyframes shimmer {
    to {
      background-position: -150% 0;
    }
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
  }
  .hero > header {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: start;
    gap: 8px 24px;
    padding: 0 0 12px 8px;
  }
  .pick {
    position: relative;
    grid-row: 1;
  }
  .metric {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 15px;
    font-weight: 600;
    padding: 5px 8px 5px 10px;
    margin-left: -10px;
    border-radius: 9px;
    color: var(--ink);
    transition: background 0.15s;
  }
  .metric:hover,
  .metric[aria-expanded='true'] {
    background: var(--wash);
  }
  .grp {
    color: var(--ink-3);
    font-weight: 500;
  }
  .menu {
    position: absolute;
    z-index: 20;
    top: calc(100% + 6px);
    left: -10px;
    width: 280px;
    padding: 8px;
    border-radius: 14px;
    background: var(--raised);
    box-shadow:
      0 0 0 1px var(--line),
      var(--shadow-lg);
  }
  .menu-list {
    max-height: 340px;
    overflow-y: auto;
    display: grid;
    margin-top: 6px;
  }
  .menu-list .label {
    padding: 10px 10px 4px;
  }
  .menu-list button {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 7px 10px;
    border-radius: 8px;
    text-align: left;
    color: var(--ink-2);
  }
  .menu-list button:hover {
    background: var(--wash);
    color: var(--ink);
  }
  .menu-list button.on {
    color: var(--ink);
    font-weight: 600;
  }
  .readout {
    grid-row: 2;
    grid-column: 1 / 3;
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 10px 36px;
  }
  .now {
    display: grid;
    gap: 6px;
  }
  .big {
    font-size: clamp(36px, 4.6vw, 52px);
    font-weight: 600;
    letter-spacing: -0.045em;
    line-height: 0.95;
  }
  .at {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12.5px;
    color: var(--ink-2);
  }
  .at i,
  .legend i {
    width: 12px;
    height: 3px;
    border-radius: 2px;
  }
  .at .mono {
    color: var(--ink-3);
    font-size: 10.5px;
  }
  .best {
    display: grid;
    gap: 5px;
    padding-bottom: 1px;
  }
  .best .mono {
    font-size: 13px;
  }
  .best .at-step {
    font-size: 10.5px;
    color: var(--ink-3);
  }
  .toggle {
    grid-row: 1;
    grid-column: 3;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding-inline: 10px;
    border-radius: 9px;
    font-size: 12.5px;
    font-weight: 550;
    color: var(--ink-3);
    transition:
      background 0.15s,
      color 0.15s;
  }
  .toggle:hover {
    background: var(--wash);
    color: var(--ink);
  }
  .toggle.on {
    background: var(--ink);
    color: var(--ground);
  }
  .legend {
    display: none;
    flex-wrap: wrap;
    gap: 6px 14px;
    padding: 10px 8px 0;
    font-size: 12px;
    color: var(--ink-2);
  }
  .legend span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  /* ---- the other metrics */
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr));
    gap: 12px;
  }
  .card {
    padding: 12px 12px 8px 6px;
    border-radius: var(--r-lg);
    background: var(--raised);
    box-shadow: 0 0 0 1px var(--line);
    transition: box-shadow 0.2s;
    animation: rise 0.6s var(--ease) both;
  }
  .card:hover {
    box-shadow: 0 0 0 1px var(--line-2);
  }
  .card header {
    display: grid;
    grid-template-columns: 1fr auto auto;
    align-items: center;
    gap: 6px;
    padding: 0 4px 6px 10px;
    min-height: 28px;
  }
  .card .name {
    justify-self: start;
    font-weight: 600;
    font-size: 13.5px;
    text-align: left;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }
  .card .grp {
    font-weight: 500;
  }
  .card .name:hover {
    text-decoration: underline;
    text-decoration-color: var(--line-2);
    text-underline-offset: 3px;
  }
  .card .val {
    font-size: 11px;
    color: var(--ink-2);
  }
  .toggle.small {
    height: 26px;
    width: 26px;
    padding: 0;
    justify-content: center;
    opacity: 0;
  }
  .card:hover .toggle.small,
  .toggle.small.on,
  .toggle.small:focus-visible {
    opacity: 1;
  }

  .none {
    display: grid;
    justify-items: start;
    gap: 14px;
    padding-top: 10vh;
  }

  /* ---- runs as a bottom sheet on narrow screens */
  .sheet-scrim {
    position: fixed;
    inset: 0;
    z-index: 40;
    background: var(--scrim);
  }
  .runs-sheet {
    position: fixed;
    z-index: 41;
    left: 0;
    right: 0;
    bottom: 0;
    max-height: 78dvh;
    overflow-y: auto;
    padding: 10px 16px calc(24px + env(safe-area-inset-bottom, 0px));
    border-radius: 22px 22px 0 0;
    background: var(--raised);
    box-shadow: var(--shadow-lg);
  }
  .grab {
    width: 40px;
    height: 4px;
    border-radius: 4px;
    background: var(--line-2);
    margin: 0 auto 14px;
  }

  @media (max-width: 900px) {
    .project {
      grid-template-columns: minmax(0, 1fr);
    }
    .rail {
      display: none;
    }
    .runs-btn {
      display: inline-flex;
    }
    .legend {
      display: flex;
    }
  }
  @media (max-width: 560px) {
    .controls {
      width: 100%;
    }
    .smooth {
      order: 3;
      flex: 1 1 100%;
    }
    .runs-btn {
      margin-left: auto;
    }
    .smooth input {
      flex: 1;
      width: auto;
    }
    .hero {
      padding: 14px 10px 12px 4px;
      border-radius: 16px;
    }
    .hero > header {
      padding-left: 10px;
    }
  }
</style>
