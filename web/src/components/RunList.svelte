<script lang="ts">
  import { flip } from 'svelte/animate'
  import { store } from '../lib/store.svelte'
  import { color, runPath, ui } from '../lib/ui.svelte'
  import { ago, fmt } from '../lib/format'
  import type { Run } from '../lib/types'
  import Icon from './Icon.svelte'

  let {
    project,
    runs,
    shown,
    hero,
    onnavigate,
  }: { project: string; runs: Run[]; shown: Map<string, number>; hero: string | null; onnavigate?: () => void } = $props()

  let query = $state('')
  let refused = $state<string | null>(null)

  const filtered = $derived.by(() => {
    const q = query.trim().toLowerCase()
    if (!q) return runs
    return runs.filter((r) => {
      if (r.id.includes(q)) return true
      const cfg = r.meta?.config ?? {}
      return Object.entries(cfg).some(([k, v]) => `${k}=${v}`.toLowerCase().includes(q))
    })
  })

  function toggle(r: Run) {
    if (!ui.toggleRun(project, r.id)) {
      refused = r.key
      setTimeout(() => (refused = null), 450)
    }
  }

  function value(r: Run) {
    if (!hero) return null
    void store.tick
    const d = store.metrics(r.key)?.metrics.get(hero)
    const v = d ? d.value.findLast((x) => x != null) : r.meta?.summary?.[hero]
    return v ?? null
  }
</script>

<div class="runs">
  <div class="search">
    <Icon name="search" size={15} />
    <label class="sr-only" for="run-q">Filter runs</label>
    <input id="run-q" placeholder="Filter" bind:value={query} autocomplete="off" spellcheck="false" />
  </div>

  <ul>
    {#each filtered as r (r.key)}
      {@const slot = shown.get(r.key)}
      {@const on = slot !== undefined}
      <li
        animate:flip={{ duration: 300 }}
        class:on
        onpointerenter={() => on && (ui.hoverRun = r.key)}
        onpointerleave={() => ui.hoverRun === r.key && (ui.hoverRun = null)}
      >
        <button
          class="key"
          class:refused={refused === r.key}
          style:--k={on ? color(slot) : 'var(--line-2)'}
          onclick={() => toggle(r)}
          aria-label={on ? `Hide ${r.id}` : `Show ${r.id}`}
          aria-pressed={on}
        ><i></i></button>
        <a class="row" href={runPath(project, r.id)} onclick={onnavigate}>
          <span class="name">{r.id}</span>
          <span class="sub">
            {#if r.status === 'running'}
              <span class="pulse"></span><span>live</span>
            {:else if r.status === 'failed'}
              <span class="badge failed">failed</span>
            {:else if r.status === 'stalled'}
              <span class="badge stalled">no signal</span>
            {/if}
            <span>{ago(r.created, store.now)}</span>
          </span>
          <span class="v mono">{fmt(value(r))}</span>
        </a>
      </li>
    {/each}
  </ul>
</div>

<style>
  .runs {
    display: grid;
    gap: 10px;
    align-content: start;
  }
  .search {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 34px;
    padding-inline: 10px;
    border-radius: var(--r);
    background: var(--wash);
    color: var(--ink-3);
    transition:
      background 0.2s,
      color 0.2s;
  }
  .search:hover,
  .search:focus-within {
    background: var(--wash-2);
  }
  .search:focus-within {
    color: var(--ink-2);
  }
  .search input {
    flex: 1;
    min-width: 0;
    border: 0;
    background: none;
    outline: none;
    font-size: 13px;
    caret-color: var(--c1);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 1px;
  }
  li {
    display: grid;
    grid-template-columns: 30px 1fr;
    align-items: center;
    border-radius: var(--r);
    transition: background 0.15s;
  }
  li:hover {
    background: var(--wash);
  }
  .key {
    display: grid;
    place-items: center;
    height: 100%;
    min-height: 44px;
    border-radius: var(--r) 0 0 var(--r);
  }
  .key i {
    width: 14px;
    height: 14px;
    border-radius: 5px;
    border: 2px solid var(--k);
    background: transparent;
    transition:
      background 0.2s,
      border-color 0.2s,
      transform 0.2s var(--ease);
  }
  li.on .key i {
    background: var(--k);
  }
  .key:hover i {
    transform: scale(1.12);
  }
  .key.refused i {
    animation: shake 0.4s var(--ease);
  }
  @keyframes shake {
    25% {
      transform: translateX(-3px);
    }
    75% {
      transform: translateX(3px);
    }
  }
  .row {
    display: grid;
    grid-template-columns: 1fr auto;
    grid-template-rows: auto auto;
    column-gap: 10px;
    padding: 8px 10px 8px 2px;
    min-width: 0;
  }
  .name {
    font-weight: 550;
    font-size: 13.5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ink-2);
    transition: color 0.15s;
  }
  li.on .name,
  li:hover .name {
    color: var(--ink);
  }
  .sub {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--ink-3);
    grid-column: 1;
  }
  .sub .pulse {
    width: 6px;
    height: 6px;
  }
  .badge {
    font-size: 11px;
    font-weight: 600;
  }
  .badge.failed {
    color: var(--failed);
  }
  .badge.stalled {
    color: var(--stalled);
  }
  .v {
    grid-row: 1 / span 2;
    grid-column: 2;
    align-self: center;
    font-size: 11px;
    color: var(--ink-2);
  }
  li:not(.on) .v {
    color: var(--ink-3);
  }
</style>
