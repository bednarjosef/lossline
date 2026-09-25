<script lang="ts">
  import { onMount } from 'svelte'
  import { fade } from 'svelte/transition'
  import { completeSignIn, session, signOut, useToken } from './lib/auth'
  import { BucketSource, listBuckets, whoami, type Account, type BucketInfo } from './lib/hf'
  import { DemoSource } from './lib/demo'
  import { store } from './lib/store.svelte'
  import { router, ui } from './lib/ui.svelte'
  import SignIn from './components/SignIn.svelte'
  import BucketPicker from './components/BucketPicker.svelte'
  import TopBar from './components/TopBar.svelte'
  import Home from './components/Home.svelte'
  import ProjectView from './components/ProjectView.svelte'

  let phase = $state<'boot' | 'signin' | 'pick' | 'app'>('boot')
  let error = $state('')
  let account = $state<Account | null>(null)
  let buckets = $state<BucketInfo[]>([])

  async function connect() {
    error = ''
    if (ui.source?.kind === 'demo') {
      account = null
      phase = 'app'
      await store.open(new DemoSource())
      return
    }
    if (!session()) {
      phase = 'signin'
      return
    }
    try {
      account = await whoami()
    } catch (e) {
      signOut()
      error = (e as Error).message
      phase = 'signin'
      return
    }
    const saved = ui.source?.kind === 'hf' ? ui.source.bucket : undefined
    if (saved) return openBucket(saved)
    const owners = [account.name, ...account.orgs]
    buckets = (await Promise.all(owners.map(listBuckets))).flat().sort((a, b) => b.updated - a.updated)
    const preferred = buckets.find((b) => b.id === `${account!.name}/lossline`) ?? buckets.find((b) => b.id.endsWith('/lossline'))
    if (preferred) return openBucket(preferred.id)
    phase = 'pick'
  }

  async function openBucket(id: string) {
    ui.source = { kind: 'hf', bucket: id }
    phase = 'app'
    await store.open(new BucketSource(id))
  }

  function demo() {
    ui.source = { kind: 'demo' }
    connect()
  }

  function withToken(t: string) {
    useToken(t)
    ui.source = null
    connect()
  }

  function leave() {
    store.close()
    signOut()
    ui.source = null
    account = null
    router.go('#/')
    phase = 'signin'
  }

  async function switchBucket() {
    store.close()
    ui.source = null
    if (!account) return leave()
    const owners = [account.name, ...account.orgs]
    buckets = (await Promise.all(owners.map(listBuckets))).flat().sort((a, b) => b.updated - a.updated)
    router.go('#/')
    phase = 'pick'
  }

  onMount(async () => {
    try {
      await completeSignIn()
    } catch (e) {
      error = (e as Error).message
    }
    await connect()
  })

  const route = $derived(router.route)
</script>

{#if phase === 'signin'}
  <div in:fade={{ duration: 250 }}>
    <SignIn {error} ondemo={demo} ontoken={withToken} />
  </div>
{:else if phase === 'pick'}
  <div in:fade={{ duration: 250 }}>
    <BucketPicker {account} {buckets} onpick={openBucket} onsignout={leave} />
  </div>
{:else if phase === 'app'}
  <div class="app" in:fade={{ duration: 250 }}>
    <TopBar {account} onswitch={switchBucket} onsignout={leave} />
    {#if store.state === 'error'}
      <div class="problem">
        <h2>Could not open {store.source?.name ?? 'the bucket'}</h2>
        <p>{store.error}</p>
        <div class="row">
          <button class="btn btn-line" onclick={() => connect()}>Try again</button>
          <button class="btn btn-ghost" onclick={switchBucket}>Choose another bucket</button>
        </div>
      </div>
    {:else if route.view === 'project'}
      {#key route.project}
        <ProjectView project={route.project} runId={route.run} />
      {/key}
    {:else}
      <Home />
    {/if}
  </div>
{/if}

<style>
  .app {
    min-height: 100%;
  }
  .problem {
    max-width: 460px;
    margin: 18vh auto 0;
    padding-inline: var(--gutter);
    display: grid;
    gap: 10px;
  }
  .problem h2 {
    font-size: 20px;
  }
  .problem p {
    color: var(--ink-2);
  }
  .row {
    display: flex;
    gap: 8px;
    margin-top: 8px;
  }
</style>
