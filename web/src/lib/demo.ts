// A self-contained example bucket: realistic runs generated in memory, laid out exactly
// like a real bucket (docs/format.md), with one run that keeps training while you watch.

import type { FileChange, FileEntry, RunMeta, Source } from './types'

function rng(seed: number) {
  return () => {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function gauss(r: () => number) {
  return Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r())
}

type Row = Record<string, number>
type Gen = (step: number, r: () => number) => Row

interface Spec {
  project: string
  id: string
  config: Record<string, unknown>
  steps: number // total planned steps
  every: number // log interval in steps
  secPerStep: number
  startedAgo: number // seconds before now
  status: 'running' | 'finished' | 'failed'
  failAt?: number
  gen: Gen
  gpu: string
  host: string
}

function lm(opts: { lr: number; width: number; warmup: number; floor: number; seed: number; spikes?: number }): Gen {
  const speed = Math.sqrt(opts.lr / 3e-4) * (opts.width / 512) ** 0.3
  const spikeAt = new Set<number>()
  const sr = rng(opts.seed * 7 + 1)
  for (let i = 0; i < (opts.spikes ?? 2); i++) spikeAt.add(Math.floor(800 + sr() * 9000))
  let spike = 0
  return (s, r) => {
    const base = opts.floor + 3.4 * Math.pow(1 + (s * speed) / 180, -0.42)
    if ([...spikeAt].some((k) => Math.abs(s - k) < opts.lr * 3000)) spike = Math.max(spike, 0.9)
    spike *= 0.93
    const loss = base * (1 + 0.035 * gauss(r)) + spike
    const warm = Math.min(1, s / opts.warmup)
    const cos = 0.1 + 0.9 * 0.5 * (1 + Math.cos(Math.PI * Math.min(1, s / 20000)))
    const row: Row = {
      'train/loss': loss,
      'train/grad_norm': 0.35 + 2.2 * Math.exp(-s / 1800) + 0.08 * Math.abs(gauss(r)) + spike * 3,
      'optim/lr': opts.lr * warm * cos,
      'sys/gpu_mem_gb': 14.2 + (opts.width / 512) * 4.1 + 0.05 * r(),
      'throughput/tokens_per_s': (118000 * 512) / opts.width + 2400 * gauss(r),
    }
    if (s % 250 === 0 && s > 0) {
      const gap = 0.012 * Math.log1p(s / 1500)
      row['eval/loss'] = base + gap + 0.012 * gauss(r)
      row['eval/acc'] = Math.min(0.97, 0.18 + 0.78 * (1 - Math.exp(-(s * speed) / 5200))) + 0.006 * gauss(r)
    }
    return row
  }
}

function rl(opts: { lr: number; entropy: number; seed: number; ceiling: number }): Gen {
  const mid = 2600 / Math.sqrt(opts.lr / 3e-4)
  return (s, r) => {
    const p = 1 / (1 + Math.exp(-(s - mid) / (mid * 0.28)))
    const ret = opts.ceiling * p + 18 * gauss(r) * (0.4 + p)
    return {
      'rollout/ep_return': ret,
      'rollout/ep_len': 180 + 620 * p + 25 * gauss(r),
      'train/policy_loss': -0.012 - 0.02 * Math.exp(-s / 1500) + 0.006 * gauss(r),
      'train/value_loss': 30 * Math.exp(-s / 2200) * (1 + p) + 1.2 + 0.4 * Math.abs(gauss(r)),
      'train/entropy': opts.entropy * (0.35 + 0.65 * Math.exp(-s / 3800)) + 0.01 * gauss(r),
      'train/approx_kl': 0.004 + 0.012 * Math.exp(-s / 3000) + 0.0015 * Math.abs(gauss(r)),
      'sys/fps': 3100 + 140 * gauss(r),
    }
  }
}

const HOUR = 3600
const SEG_BYTES = 256 * 1024

const specs: Spec[] = [
  // ---- seqmem: a small language-model sweep
  { project: 'seqmem', id: 'quiet-harbor-2k9d', config: { lr: 3e-4, width: 512, depth: 8, batch_size: 64, warmup: 500, dataset: 'numseq-v2' }, steps: 12000, every: 10, secPerStep: 0.42, startedAgo: 30 * HOUR, status: 'finished', gen: lm({ lr: 3e-4, width: 512, warmup: 500, floor: 0.92, seed: 1 }), gpu: 'NVIDIA GeForce RTX 3090', host: 'C.2581173' },
  { project: 'seqmem', id: 'amber-falcon-p0x4', config: { lr: 1e-3, width: 512, depth: 8, batch_size: 64, warmup: 500, dataset: 'numseq-v2' }, steps: 12000, every: 10, secPerStep: 0.42, startedAgo: 27 * HOUR, status: 'finished', gen: lm({ lr: 1e-3, width: 512, warmup: 500, floor: 0.97, seed: 2, spikes: 4 }), gpu: 'NVIDIA GeForce RTX 3090', host: 'C.2581173' },
  { project: 'seqmem', id: 'lunar-moss-81fa', config: { lr: 3e-4, width: 1024, depth: 8, batch_size: 64, warmup: 500, dataset: 'numseq-v2' }, steps: 12000, every: 10, secPerStep: 0.71, startedAgo: 22 * HOUR, status: 'finished', gen: lm({ lr: 3e-4, width: 1024, warmup: 500, floor: 0.84, seed: 3 }), gpu: 'NVIDIA RTX 5090', host: 'C.2604420' },
  { project: 'seqmem', id: 'tidal-cedar-5bq1', config: { lr: 3e-3, width: 512, depth: 8, batch_size: 64, warmup: 100, dataset: 'numseq-v2' }, steps: 12000, every: 10, secPerStep: 0.42, startedAgo: 9 * HOUR, status: 'failed', failAt: 3100, gen: lm({ lr: 3e-3, width: 512, warmup: 100, floor: 1.08, seed: 4, spikes: 6 }), gpu: 'NVIDIA GeForce RTX 3090', host: 'C.2581173' },
  { project: 'seqmem', id: 'silver-otter-m3c7', config: { lr: 5e-4, width: 1024, depth: 12, batch_size: 128, warmup: 800, dataset: 'numseq-v3' }, steps: 16000, every: 10, secPerStep: 0.8, startedAgo: 1.6 * HOUR, status: 'running', gen: lm({ lr: 5e-4, width: 1024, warmup: 800, floor: 0.79, seed: 5 }), gpu: 'NVIDIA RTX 5090', host: 'C.2611032' },
  // ---- silktouch: reinforcement learning
  { project: 'silktouch', id: 'north-kiln-ta21', config: { algo: 'ppo', lr: 3e-4, envs: 64, ent_coef: 0.01, gamma: 0.995 }, steps: 9000, every: 10, secPerStep: 1.1, startedAgo: 70 * HOUR, status: 'finished', gen: rl({ lr: 3e-4, entropy: 1.6, seed: 11, ceiling: 410 }), gpu: 'NVIDIA GeForce RTX 3090', host: 'C.2459012' },
  { project: 'silktouch', id: 'copper-reed-9h2s', config: { algo: 'ppo', lr: 6e-4, envs: 128, ent_coef: 0.005, gamma: 0.995 }, steps: 9000, every: 10, secPerStep: 1.3, startedAgo: 50 * HOUR, status: 'finished', gen: rl({ lr: 6e-4, entropy: 1.6, seed: 12, ceiling: 520 }), gpu: 'NVIDIA GeForce RTX 3090', host: 'C.2459012' },
  { project: 'silktouch', id: 'pale-signal-44wk', config: { algo: 'ppo', lr: 6e-4, envs: 128, ent_coef: 0.02, gamma: 0.999 }, steps: 9000, every: 10, secPerStep: 1.3, startedAgo: 7 * HOUR, status: 'running', gen: rl({ lr: 6e-4, entropy: 2.1, seed: 13, ceiling: 590 }), gpu: 'NVIDIA GeForce RTX 3090', host: 'C.2467755' },
  // ---- evoquant: finished work
  { project: 'evoquant', id: 'dune-lattice-0v6e', config: { bits: 4, population: 32, generations: 400 }, steps: 4000, every: 10, secPerStep: 2.2, startedAgo: 200 * HOUR, status: 'finished', gen: lm({ lr: 2e-4, width: 768, warmup: 200, floor: 1.4, seed: 21, spikes: 0 }), gpu: 'Tesla T4', host: 'kaggle' },
  { project: 'evoquant', id: 'brisk-meadow-lk30', config: { bits: 3, population: 48, generations: 400 }, steps: 4000, every: 10, secPerStep: 2.4, startedAgo: 160 * HOUR, status: 'finished', gen: lm({ lr: 2e-4, width: 768, warmup: 200, floor: 1.62, seed: 22, spikes: 0 }), gpu: 'Tesla T4', host: 'kaggle' },
]

interface LiveRun {
  spec: Spec
  step: number
  r: () => number
  t0: number
  pending: string
  seg: number
  summary: Record<string, number>
  rows: number
}

export class DemoSource implements Source {
  kind = 'demo' as const
  name = 'example'
  private files = new Map<string, { text: string; updated: number }>()
  private live: LiveRun[] = []
  private listeners = new Set<(c: FileChange[]) => void>()
  private timers: number[] = []

  constructor() {
    const now = Date.now() / 1000
    for (const spec of specs) this.build(spec, now)
  }

  private put(path: string, text: string, updated = Date.now()) {
    this.files.set(path, { text, updated })
  }

  private meta(spec: Spec, t0: number, summary: Record<string, number>, rows: number, segs: number, status: RunMeta['status'], heartbeat: number): RunMeta {
    const name = spec.id.slice(0, spec.id.lastIndexOf('-'))
    return {
      format: 1,
      project: spec.project,
      id: spec.id,
      name,
      status,
      created: new Date(t0 * 1000).toISOString(),
      heartbeat: new Date(heartbeat * 1000).toISOString(),
      ended: status === 'running' ? null : new Date(heartbeat * 1000).toISOString(),
      flush_interval: 15,
      config: spec.config,
      summary,
      system: { host: spec.host, gpu: spec.gpu, python: '3.12.4', platform: 'Linux-6.8.0-x86_64' },
      git: { commit: (spec.id.charCodeAt(0) * 99991).toString(16).slice(0, 7), branch: 'main', dirty: spec.status === 'running' },
      tags: [],
      notes: '',
      segments: segs,
      rows,
    }
  }

  private build(spec: Spec, now: number) {
    const r = rng(spec.id.length * 1000 + spec.id.charCodeAt(0))
    const t0 = now - spec.startedAgo
    const elapsedSteps = Math.floor(spec.startedAgo / spec.secPerStep)
    const last = spec.status === 'running' ? Math.min(elapsedSteps, spec.steps - 1) : spec.failAt ?? spec.steps
    const dir = `${spec.project}/${spec.id}`
    const summary: Record<string, number> = {}
    let seg = 0
    let text = ''
    let rows = 0
    for (let s = 0; s <= last; s += spec.every) {
      const row = spec.gen(s, r)
      Object.assign(summary, row)
      summary._step = s
      text += JSON.stringify({ _step: s, _time: +(t0 + s * spec.secPerStep).toFixed(2), ...round(row) }) + '\n'
      rows++
      if (text.length > SEG_BYTES) {
        this.put(`${dir}/metrics/${String(seg).padStart(6, '0')}.jsonl`, text, (t0 + s * spec.secPerStep) * 1000)
        seg++
        text = ''
      }
    }
    const end = t0 + last * spec.secPerStep
    this.put(`${dir}/metrics/${String(seg).padStart(6, '0')}.jsonl`, text, end * 1000)
    this.put(`${dir}/meta.json`, JSON.stringify(this.meta(spec, t0, round(summary), rows, seg + 1, spec.status, end)), end * 1000)
    if (spec.status === 'running') {
      this.live.push({ spec, step: last + spec.every, r, t0, pending: '', seg, summary, rows })
    }
  }

  async list(): Promise<FileEntry[]> {
    await delay(120)
    return [...this.files].map(([path, f]) => ({ path, size: f.text.length, updated: f.updated }))
  }

  async read(path: string, from = 0, to?: number): Promise<string> {
    await delay(60 + Math.random() * 120)
    return this.files.get(path)?.text.slice(from, to) ?? ''
  }

  watch(onChange: (changes: FileChange[]) => void): () => void {
    this.listeners.add(onChange)
    if (this.timers.length === 0) this.start()
    return () => {
      this.listeners.delete(onChange)
      if (this.listeners.size === 0) this.stop()
    }
  }

  private start() {
    // Training ticks every 250 ms (sped up so there is something to watch); the
    // "logger" flushes every 2 s like a real run would.
    this.timers.push(
      window.setInterval(() => {
        for (const l of this.live) {
          const s = l.step
          const row = l.spec.gen(s, l.r)
          Object.assign(l.summary, row)
          l.summary._step = s
          l.pending += JSON.stringify({ _step: s, _time: +(l.t0 + s * l.spec.secPerStep).toFixed(2), ...round(row) }) + '\n'
          l.rows++
          l.step += l.spec.every
        }
      }, 250),
      window.setInterval(() => this.flush(), 2000),
    )
  }

  private stop() {
    this.timers.forEach(clearInterval)
    this.timers = []
  }

  private flush() {
    const changes: FileChange[] = []
    const now = Date.now()
    for (const l of this.live) {
      if (!l.pending) continue
      const dir = `${l.spec.project}/${l.spec.id}`
      const path = `${dir}/metrics/${String(l.seg).padStart(6, '0')}.jsonl`
      const f = this.files.get(path)!
      this.put(path, f.text + l.pending, now)
      l.pending = ''
      const meta = this.meta(l.spec, l.t0, round(l.summary), l.rows, l.seg + 1, 'running', now / 1000)
      this.put(`${dir}/meta.json`, JSON.stringify(meta), now)
      changes.push({ path, op: 'update', size: this.files.get(path)!.text.length }, { path: `${dir}/meta.json`, op: 'update', size: 0 })
    }
    if (changes.length) this.listeners.forEach((fn) => fn(changes))
  }
}

function round(row: Row): Row {
  const out: Row = {}
  for (const k in row) out[k] = Number.isInteger(row[k]) ? row[k] : +row[k].toPrecision(6)
  return out
}

function delay(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}
