<script lang="ts">
  import type { Account, BucketInfo } from '../lib/hf'
  import { ago } from '../lib/format'
  import Wordmark from './Wordmark.svelte'
  import Icon from './Icon.svelte'

  let {
    account,
    buckets,
    onpick,
    onsignout,
  }: { account: Account | null; buckets: BucketInfo[]; onpick: (id: string) => void; onsignout: () => void } = $props()

  let manual = $state('')
  const user = $derived(account?.name ?? 'you')

  function submit(e: SubmitEvent) {
    e.preventDefault()
    const id = manual.trim().replace(/^hf:\/\/buckets\//, '')
    if (/^[\w.-]+\/[\w.-]+$/.test(id)) onpick(id)
  }
</script>

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

    {#if buckets.length}
      <h1>Which bucket holds your runs?</h1>
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
    {:else}
      <h1>Start with a bucket.</h1>
      <p class="lede">Create one, point your training script at it, and your runs appear here.</p>
      <pre><code><span class="c"># once</span>
hf buckets create lossline --private
pip install lossline

<span class="c"># in your training script</span>
import lossline
lossline.init(project="my-model", config=cfg)
lossline.log(&#123;"train/loss": loss&#125;)

<span class="c"># on the training box</span>
LOSSLINE_BUCKET={user}/lossline python train.py</code></pre>
    {/if}

    <form onsubmit={submit}>
      <label class="sr-only" for="bucket-id">Bucket</label>
      <input id="bucket-id" class="field mono" placeholder="owner/bucket" bind:value={manual} autocomplete="off" spellcheck="false" />
      <button class="btn btn-line" type="submit">Open</button>
    </form>
  </section>
</main>

<style>
  .pick {
    min-height: 100dvh;
    padding-inline: var(--gutter);
  }
  header {
    height: var(--top);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  section {
    max-width: 560px;
    margin: 10vh auto 0;
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
    font-size: clamp(28px, 4vw, 36px);
    letter-spacing: -0.035em;
    line-height: 1.05;
  }
  .lede {
    color: var(--ink-2);
    font-size: 15.5px;
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
  form {
    display: flex;
    gap: 8px;
    margin-top: 6px;
  }
  form .field {
    font-size: 12.5px;
  }
</style>
