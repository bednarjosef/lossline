<script lang="ts">
  import { onMount } from 'svelte'
  import { fade, fly } from 'svelte/transition'
  import { store } from '../lib/store.svelte'
  import { color, ui } from '../lib/ui.svelte'
  import { configValue, duration, fmt, fmtStep, when } from '../lib/format'
  import { groups, splitName } from '../lib/metrics'
  import type { Run } from '../lib/types'
  import Icon from './Icon.svelte'

  let { run, slot, onclose }: { run: Run; slot: number | undefined; onclose: () => void } = $props()

  const narrow = matchMedia('(max-width: 700px)').matches
  const meta = $derived(run.meta)
  const shownNow = $derived(slot !== undefined)

  const runtime = $derived.by(() => {
    if (!meta) return null
    const start = Date.parse(meta.created)
    const end = meta.ended ? Date.parse(meta.ended) : run.status === 'running' ? store.now : Date.parse(meta.heartbeat)
    return (end - start) / 1000
  })

  const summary = $derived.by(() => {
    const s = meta?.summary ?? {}
    return groups(Object.keys(s).filter((k) => k[0] !== '_')).map((g) => ({
      group: g.group,
      rows: g.metrics.map((m) => ({ name: splitName(m).leaf, v: s[m] })),
    }))
  })

  const config = $derived(Object.entries(meta?.config ?? {}))
  const system = $derived(
    [
      ['GPU', meta?.system?.gpu],
      ['Host', meta?.system?.host],
      ['Python', meta?.system?.python],
      ['Platform', meta?.system?.platform],
      ['Commit', meta?.git?.commit ? `${meta.git.commit}${meta.git.dirty ? ' (modified)' : ''}` : undefined],
      ['Branch', meta?.git?.branch],
    ].filter(([, v]) => v) as [string, string][],
  )

  let copied = $state(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(`${run.project}/${run.id}`)
      copied = true
      setTimeout(() => (copied = false), 1400)
    } catch {
      // clipboard unavailable; the id is selectable text in the header
    }
  }

  onMount(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onclose()
    addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  })
</script>

<div class="scrim" transition:fade={{ duration: 200 }} onclick={onclose} aria-hidden="true"></div>
<aside class="sheet" transition:fly={narrow ? { y: 500, duration: 340, opacity: 1 } : { x: 460, duration: 340, opacity: 1 }} aria-label="Run details">
  <header>
    <div class="id">
      <i style:--k={shownNow ? color(slot!) : 'var(--line-2)'} class:off={!shownNow}></i>
      <h2>{run.id}</h2>
    </div>
    <button class="icon-btn" onclick={onclose} aria-label="Close"><Icon name="x" /></button>
  </header>

  <div class="status">
    {#if run.status === 'running'}
      <span class="pill live"><span class="pulse"></span>Live</span>
    {:else if run.status === 'finished'}
      <span class="pill">Finished</span>
    {:else if run.status === 'failed'}
      <span class="pill failed">Failed</span>
    {:else}
      <span class="pill stalled">No signal</span>
    {/if}
    {#if meta?.tags?.length}
      {#each meta.tags as t (t)}<span class="pill tag">{t}</span>{/each}
    {/if}
  </div>

  <dl class="stats">
    <div><dt>Steps</dt><dd>{fmtStep(meta?.summary?._step ?? 0)}</dd></div>
    <div><dt>Runtime</dt><dd>{runtime != null ? duration(runtime) : '—'}</dd></div>
    <div><dt>Started</dt><dd>{meta ? when(Date.parse(meta.created)) : '—'}</dd></div>
  </dl>

  <div class="actions">
    <button class="btn btn-line" onclick={() => ui.solo(run.project, run.id)}><Icon name="solo" size={15} />Show only this</button>
    <button class="btn btn-ghost" onclick={() => ui.toggleRun(run.project, run.id)}>{shownNow ? 'Hide' : 'Show'}</button>
    <button class="btn btn-ghost" onclick={copy}><Icon name={copied ? 'check' : 'copy'} size={15} />{copied ? 'Copied' : 'Copy ID'}</button>
  </div>

  {#if meta?.notes}
    <p class="notes">{meta.notes}</p>
  {/if}

  {#if summary.length}
    <section>
      <h3 class="label">Latest values</h3>
      {#each summary as g (g.group)}
        <dl class="kv">
          {#each g.rows as r (r.name)}
            <div><dt>{#if g.group}<span class="grp">{g.group}/</span>{/if}{r.name}</dt><dd class="mono">{fmt(r.v, 5)}</dd></div>
          {/each}
        </dl>
      {/each}
    </section>
  {/if}

  {#if config.length}
    <section>
      <h3 class="label">Config</h3>
      <dl class="kv">
        {#each config as [k, v] (k)}
          <div><dt>{k}</dt><dd class="mono">{configValue(v)}</dd></div>
        {/each}
      </dl>
    </section>
  {/if}

  {#if system.length}
    <section>
      <h3 class="label">Machine</h3>
      <dl class="kv">
        {#each system as [k, v] (k)}
          <div><dt>{k}</dt><dd class="mono">{v}</dd></div>
        {/each}
      </dl>
    </section>
  {/if}
</aside>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 50;
    background: var(--scrim);
  }
  .sheet {
    position: fixed;
    z-index: 51;
    top: 10px;
    right: 10px;
    bottom: 10px;
    width: min(440px, calc(100vw - 20px));
    overflow-y: auto;
    padding: 20px 22px 32px;
    border-radius: 20px;
    background: var(--raised);
    box-shadow:
      0 0 0 1px var(--line),
      var(--shadow-lg);
    display: grid;
    gap: 22px;
    align-content: start;
  }
  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }
  .id {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }
  .id i {
    flex: none;
    width: 14px;
    height: 14px;
    border-radius: 5px;
    background: var(--k);
    border: 2px solid var(--k);
  }
  .id i.off {
    background: transparent;
  }
  h2 {
    font-size: 21px;
    letter-spacing: -0.03em;
    overflow-wrap: anywhere;
    user-select: all;
  }
  .status {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: -10px;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    height: 24px;
    padding-inline: 10px;
    border-radius: 99px;
    font-size: 12px;
    font-weight: 600;
    background: var(--wash);
    color: var(--ink-2);
  }
  .pill .pulse {
    width: 6px;
    height: 6px;
  }
  .pill.failed {
    color: var(--failed);
    background: color-mix(in srgb, var(--failed) 12%, transparent);
  }
  .pill.stalled {
    color: var(--stalled);
    background: color-mix(in srgb, var(--stalled) 14%, transparent);
  }
  .pill.tag {
    font-weight: 500;
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin: 0;
    padding: 14px 0;
    border-block: 1px solid var(--line);
  }
  .stats div {
    display: grid;
    gap: 3px;
  }
  .stats dt {
    font-size: 12px;
    color: var(--ink-3);
  }
  .stats dd {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.02em;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: -8px;
  }
  .actions .btn {
    height: 32px;
    font-size: 12.5px;
    padding-inline: 11px;
  }
  .notes {
    color: var(--ink-2);
    white-space: pre-wrap;
  }
  section {
    display: grid;
    gap: 8px;
  }
  .kv {
    margin: 0;
    display: grid;
  }
  .kv div {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 16px;
    padding: 7px 0;
    border-bottom: 1px solid var(--line);
    font-size: 13px;
  }
  .kv dt {
    color: var(--ink-2);
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .grp {
    color: var(--ink-3);
  }
  .kv dd {
    margin: 0;
    font-size: 11.5px;
    text-align: right;
    overflow-wrap: anywhere;
    font-variant-numeric: tabular-nums;
  }
  @media (max-width: 700px) {
    .sheet {
      top: auto;
      left: 0;
      right: 0;
      bottom: 0;
      width: 100%;
      max-height: 86dvh;
      border-radius: 22px 22px 0 0;
      padding-bottom: calc(32px + env(safe-area-inset-bottom, 0px));
    }
  }
</style>
