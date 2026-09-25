<script lang="ts">
  import { slide } from 'svelte/transition'
  import type { Account, BucketInfo } from '../lib/hf'
  import { ago } from '../lib/format'
  import Wordmark from './Wordmark.svelte'
  import Icon from './Icon.svelte'

  let {
    mode,
    account,
    buckets,
    onpick,
    onsignout,
    onbrowse,
  }: {
    mode: 'setup' | 'pick'
    account: Account | null
    buckets: BucketInfo[]
    onpick: (id: string) => void
    onsignout: () => void
    onbrowse: () => void
  } = $props()

  let manual = $state('')
  let others = $state(false)
  const user = $derived(account?.name ?? 'you')

  function submit(e: SubmitEvent) {
    e.preventDefault()
    const id = manual.trim().replace(/^hf:\/\/buckets\//, '')
    if (/^[\w.-]+\/[\w.-]+$/.test(id)) onpick(id)
  }

  function browse() {
    others = !others
    if (others) onbrowse()
  }
</script>

{#snippet list()}
  {#if buckets.length}
    <ul>
      {#each buckets as b, i (b.id)}
        <li style:animation-delay="{i * 40}ms">
          <button onclick={() => onpick(b.id)}>
            <Icon name="bucket" />
            <span class="id">{b.id}</span>
            <span class="meta">{b.private ? 'private' : 'public'} · {ago(b.updated)}</span>
            <Icon name="arrow" size={16} />
          </button>
        </li>
      {/each}
    </ul>
  {/if}
  <form onsubmit={submit}>
    <label class="sr-only" for="bucket-id">Bucket</label>
    <input id="bucket-id" class="field mono" placeholder="owner/bucket" bind:value={manual} autocomplete="off" spellcheck="false" />
    <button class="btn btn-line" type="submit">Open</button>
  </form>
{/snippet}

<main class="pick">
  <header>
    <Wordmark size={17} />
    <button class="btn btn-ghost" onclick={onsignout}>Sign out</button>
  </header>

  <section>
    {#if account}
      <div class="who">
        <img src={account.avatarUrl} alt="" />
        <span>{account.fullname}</span>
      </div>
    {/if}

    {#if mode === 'setup'}
      <h1>Log your first run.</h1>
      <pre><code><span class="c"># install</span>
pip install "git+https://github.com/bednarjosef/lossline#subdirectory=python"

<span class="c"># in your training script</span>
import lossline
lossline.init(project="my-model", config=cfg)
lossline.log(&#123;"train/loss": loss&#125;)

<span class="c"># on a machine that isn't logged in to Hugging Face</span>
HF_TOKEN=hf_… python train.py</code></pre>
      <p class="wait"><span class="pulse"></span><span>Runs go to <b class="mono">{user}/lossline</b>. This page opens it as soon as it exists.</span></p>

      <button class="more" onclick={browse} aria-expanded={others}>
        Use a different bucket <Icon name="chevron" size={15} />
      </button>
      {#if others}
        <div class="others" transition:slide={{ duration: 240 }}>
          {@render list()}
        </div>
      {/if}
    {:else}
      <h1>Choose a bucket.</h1>
      {@render list()}
    {/if}
  </section>
</main>

<style>
  .pick {
    min-height: 100dvh;
    padding-inline: var(--gutter);
    padding-bottom: 60px;
  }
  header {
    height: var(--top);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  section {
    max-width: 560px;
    margin: 9vh auto 0;
    display: grid;
    gap: 18px;
    animation: rise 0.7s var(--ease) both;
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(10px);
    }
  }
  .who {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--ink-2);
  }
  .who img {
    width: 26px;
    height: 26px;
    border-radius: 50%;
  }
  h1 {
    font-size: clamp(28px, 4vw, 38px);
    letter-spacing: -0.04em;
    line-height: 1.05;
  }
  pre {
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
  .c {
    color: var(--ink-3);
  }
  .wait {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px 10px;
    color: var(--ink-2);
    font-size: 14px;
  }
  .wait b {
    color: var(--ink);
    font-weight: 500;
    font-size: 12px;
  }
  .more {
    justify-self: start;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 10px;
    font-size: 13.5px;
    font-weight: 550;
    color: var(--ink-3);
    transition: color 0.2s;
  }
  .more:hover,
  .more[aria-expanded='true'] {
    color: var(--ink);
  }
  .more :global(svg) {
    transition: transform 0.25s var(--ease);
  }
  .more[aria-expanded='true'] :global(svg) {
    transform: rotate(180deg);
  }
  .others {
    display: grid;
    gap: 12px;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 6px;
  }
  li {
    animation: rise 0.5s var(--ease) both;
  }
  li button {
    width: 100%;
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
    border-radius: 12px;
    background: var(--raised);
    box-shadow: 0 0 0 1px var(--line);
    text-align: left;
    transition:
      box-shadow 0.2s,
      transform 0.2s var(--ease);
    color: var(--ink-3);
  }
  li button:hover {
    box-shadow:
      0 0 0 1px var(--line-2),
      var(--shadow);
    transform: translateY(-1px);
    color: var(--ink);
  }
  .id {
    font-weight: 600;
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .meta {
    font-size: 12.5px;
    color: var(--ink-3);
  }
  form {
    display: flex;
    gap: 8px;
  }
  form .field {
    font-size: 12.5px;
  }
</style>
