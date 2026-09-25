<script lang="ts">
  import { fly } from 'svelte/transition'
  import type { Account } from '../lib/hf'
  import { store } from '../lib/store.svelte'
  import { router, ui } from '../lib/ui.svelte'
  import Wordmark from './Wordmark.svelte'
  import Icon from './Icon.svelte'

  let { account, onswitch, onsignout }: { account: Account | null; onswitch: () => void; onsignout: () => void } = $props()

  let menu = $state(false)
  const route = $derived(router.route)
  const demo = $derived(store.source?.kind === 'demo')

  function outside(node: HTMLElement) {
    const close = (e: PointerEvent) => {
      if (!node.contains(e.target as Node)) menu = false
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && (menu = false)
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', esc)
    return { destroy: () => (document.removeEventListener('pointerdown', close), document.removeEventListener('keydown', esc)) }
  }
</script>

<header class="top">
  <nav>
    <a href="#/" class="home" aria-label="All projects"><Wordmark size={16} /></a>
    {#if route.view === 'project'}
      <span class="sep">/</span>
      {#key route.project}
        <a class="crumb" href="#/p/{encodeURIComponent(route.project)}" in:fly={{ x: -6, duration: 300 }}>{route.project}</a>
      {/key}
    {/if}
  </nav>

  <div class="right">
    {#if demo}
      <span class="example">Example data</span>
    {/if}
    <button class="icon-btn" onclick={() => ui.toggleTheme()} aria-label="Switch theme">
      {#key ui.dark}
        <span class="swap" in:fly={{ y: 6, duration: 250 }}><Icon name={ui.dark ? 'sun' : 'moon'} /></span>
      {/key}
    </button>
    {#if demo}
      <button class="btn btn-primary" onclick={onsignout}>Sign in</button>
    {:else if account}
      <div class="acct" use:outside>
        <button class="avatar" onclick={() => (menu = !menu)} aria-label="Account" aria-expanded={menu}>
          <img src={account.avatarUrl} alt="" />
        </button>
        {#if menu}
          <div class="menu" transition:fly={{ y: -6, duration: 180 }}>
            <div class="menu-head">
              <b>{account.fullname}</b>
              <span class="mono">{store.source?.name}</span>
            </div>
            <button onclick={() => ((menu = false), onswitch())}><Icon name="bucket" size={16} />Switch bucket</button>
            <button onclick={() => ((menu = false), onsignout())}><Icon name="logout" size={16} />Sign out</button>
          </div>
        {/if}
      </div>
    {/if}
  </div>
</header>

<style>
  .top {
    position: sticky;
    top: 0;
    z-index: 30;
    height: calc(var(--top) + env(safe-area-inset-top, 0px));
    padding: env(safe-area-inset-top, 0px) var(--gutter) 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    background: color-mix(in srgb, var(--ground) 82%, transparent);
    backdrop-filter: saturate(1.4) blur(14px);
    border-bottom: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
  }
  nav {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  .home {
    display: flex;
    padding: 6px 4px;
    border-radius: 8px;
  }
  .sep {
    color: var(--line-2);
    font-size: 18px;
    font-weight: 300;
  }
  .crumb {
    font-weight: 600;
    letter-spacing: -0.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .right {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .example {
    font-size: 12px;
    font-weight: 550;
    color: var(--ink-2);
    padding: 4px 10px;
    border-radius: 99px;
    box-shadow: inset 0 0 0 1px var(--line-2);
    margin-right: 4px;
  }
  @media (max-width: 600px) {
    .example {
      display: none;
    }
  }
  .swap {
    display: grid;
  }
  .acct {
    position: relative;
  }
  .avatar {
    display: grid;
    width: 34px;
    height: 34px;
    place-items: center;
    border-radius: 50%;
    transition: box-shadow 0.2s;
  }
  .avatar:hover,
  .avatar[aria-expanded='true'] {
    box-shadow: 0 0 0 3px var(--wash-2);
  }
  .avatar img {
    width: 28px;
    height: 28px;
    border-radius: 50%;
  }
  .menu {
    position: absolute;
    right: 0;
    top: calc(100% + 8px);
    min-width: 240px;
    padding: 6px;
    border-radius: 14px;
    background: var(--raised);
    box-shadow:
      0 0 0 1px var(--line),
      var(--shadow-lg);
    display: grid;
  }
  .menu-head {
    display: grid;
    gap: 2px;
    padding: 10px 10px 12px;
    margin-bottom: 4px;
    border-bottom: 1px solid var(--line);
  }
  .menu-head span {
    color: var(--ink-3);
    font-size: 11px;
  }
  .menu button {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 10px;
    border-radius: 8px;
    color: var(--ink-2);
    text-align: left;
  }
  .menu button:hover {
    background: var(--wash);
    color: var(--ink);
  }
</style>
