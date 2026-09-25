import { pickHero } from './metrics'
import type { FileChange, FileEntry, MetricSeries, Project, Run, RunMeta, Source, Status } from './types'

const META = /^([^/]+)\/([^/]+)\/meta\.json$/
const SEGMENT = /^([^/]+)\/([^/]+)\/metrics\/(\d+)\.jsonl$/
const utf8 = new TextEncoder()

/** Parsed metrics of one run, filled in incrementally as segments grow. */
export class RunData {
  metrics = new Map<string, MetricSeries>()
  /** bytes consumed per segment index */
  consumed: number[] = []
  partial = ''
  t0 = NaN
  lastStep = 0
  rows = 0

  ingest(text: string) {
    const all = this.partial + text
    const end = all.lastIndexOf('\n')
    if (end < 0) {
      this.partial = all
      return
    }
    this.partial = all.slice(end + 1)
    for (const line of all.slice(0, end).split('\n')) {
      if (!line) continue
      let row: Record<string, number | null>
      try {
        row = JSON.parse(line)
      } catch {
        continue
      }
      const step = row._step as number
      const time = row._time as number
      if (!Number.isFinite(this.t0)) this.t0 = time
      this.lastStep = step
      this.rows++
      for (const k in row) {
        if (k[0] === '_') continue
        let m = this.metrics.get(k)
        if (!m) this.metrics.set(k, (m = { step: [], time: [], value: [] }))
        m.step.push(step)
        m.time.push(time)
        m.value.push(row[k])
      }
    }
  }
}

function statusOf(meta: RunMeta | null, updated: number, now: number): Status {
  if (!meta) return 'running'
  if (meta.status !== 'running') return meta.status
  const heartbeat = Math.max(Date.parse(meta.heartbeat) || 0, updated)
  const grace = (3 * (meta.flush_interval || 15) + 60) * 1000
  return now - heartbeat > grace ? 'stalled' : 'running'
}

class Store {
  source = $state<Source | null>(null)
  state = $state<'idle' | 'loading' | 'ready' | 'error'>('idle')
  error = $state('')
  files = $state<Record<string, FileEntry>>({})
  metas = $state<Record<string, RunMeta>>({})
  now = $state(Date.now())
  /** bumps whenever any loaded run receives new rows */
  tick = $state(0)
  /** a light look at the end of a run, for sparklines in lists */
  previews = $state<Record<string, { metric: string; values: number[] }>>({})
  private previewed = new Map<string, number>()

  private data = new Map<string, RunData>()
  private loading = new Map<string, Promise<void>>()
  private metaLoads = new Map<string, Promise<void>>()
  private unwatch: (() => void) | null = null
  private clock = 0
  private pendingMeta = new Set<string>()
  private metaTimer = 0

  runs = $derived.by(() => {
    const byKey = new Map<string, Run>()
    for (const f of Object.values(this.files)) {
      const m = META.exec(f.path) ?? SEGMENT.exec(f.path)
      if (!m) continue
      const key = `${m[1]}/${m[2]}`
      let run = byKey.get(key)
      if (!run) {
        run = { key, project: m[1], id: m[2], meta: null, status: 'running', created: f.updated, updated: 0, segments: [] }
        byKey.set(key, run)
      }
      run.updated = Math.max(run.updated, f.updated)
      if (m[3] !== undefined) run.segments.push(f)
    }
    for (const run of byKey.values()) {
      run.meta = this.metas[run.key] ?? null
      run.segments.sort((a, b) => (a.path < b.path ? -1 : 1))
      if (run.meta) run.created = Date.parse(run.meta.created) || run.created
      else run.created = Math.min(...run.segments.map((s) => s.updated), run.updated)
      run.status = statusOf(run.meta, run.updated, this.now)
    }
    return [...byKey.values()].sort((a, b) => b.created - a.created)
  })

  projects = $derived.by((): Project[] => {
    const by = new Map<string, Run[]>()
    for (const r of this.runs) {
      if (!by.has(r.project)) by.set(r.project, [])
      by.get(r.project)!.push(r)
    }
    return [...by]
      .map(([name, runs]) => ({
        name,
        runs,
        updated: Math.max(...runs.map((r) => r.updated)),
        live: runs.filter((r) => r.status === 'running').length,
      }))
      .sort((a, b) => b.live - a.live || b.updated - a.updated)
  })

  async open(source: Source) {
    this.close()
    this.source = source
    this.state = 'loading'
    this.error = ''
    try {
      await this.relist()
      this.state = 'ready'
    } catch (e) {
      this.state = 'error'
      this.error = (e as Error).message
      return
    }
    this.unwatch = source.watch((c) => this.onChanges(c))
    this.clock = window.setInterval(() => (this.now = Date.now()), 15_000)
  }

  close() {
    this.unwatch?.()
    this.unwatch = null
    clearInterval(this.clock)
    this.source = null
    this.files = {}
    this.metas = {}
    this.data.clear()
    this.loading.clear()
    this.metaLoads.clear()
    this.previews = {}
    this.previewed.clear()
    this.state = 'idle'
  }

  private async relist() {
    const list = await this.source!.list()
    const files: Record<string, FileEntry> = {}
    for (const f of list) files[f.path] = f
    this.files = files
    // metas are small; load them all so every list can show status and summaries
    const keys = list.map((f) => META.exec(f.path)).filter(Boolean) as RegExpExecArray[]
    await pool(
      keys.map((m) => () => this.loadMeta(`${m[1]}/${m[2]}`)),
      8,
    )
  }

  private loadMeta(key: string): Promise<void> {
    const src = this.source!
    const p = src
      .read(`${key}/meta.json`)
      .then((t) => {
        if (this.source !== src) return
        try {
          this.metas[key] = JSON.parse(t)
        } catch {
          // a half-written meta.json is replaced on the next flush
        }
      })
      .catch(() => {})
      .finally(() => this.metaLoads.delete(key))
    this.metaLoads.set(key, p)
    return p
  }

  /**
   * A sparkline's worth of a run without downloading it: eight small byte windows
   * spread evenly across its segments, so the whole shape of the curve shows.
   */
  async preview(key: string, metric?: string) {
    const last = this.previewed.get(key)
    if (last && Date.now() - last < 10_000) return
    this.previewed.set(key, Date.now())
    const run = this.run(key)
    const src = this.source
    if (!run?.segments.length || !src) return
    const segs = run.segments
    const total = segs.reduce((n, s) => n + s.size, 0)
    const W = 16 * 1024
    const windows = total <= W * 8 ? [0] : Array.from({ length: 8 }, (_, i) => Math.floor((i * (total - W)) / 7))
    const texts = await Promise.all(
      windows.map(async (pos) => {
        let i = 0
        while (i < segs.length - 1 && pos >= segs[i].size) pos -= segs[i++].size
        const whole = total <= W * 8
        const text = await src.read(segs[i].path, pos, whole ? undefined : Math.min(segs[i].size, pos + W)).catch(() => '')
        // keep complete lines only
        const start = pos > 0 ? text.indexOf('\n') + 1 : 0
        const end = text.lastIndexOf('\n')
        return whole && segs.length > 1 ? '' : text.slice(start, end + 1)
      }),
    )
    if (this.source !== src) return
    const windowsRows = texts.map((t) =>
      t.split('\n').flatMap((l) => {
        try {
          return l ? [JSON.parse(l) as Record<string, number | null>] : []
        } catch {
          return []
        }
      }),
    )
    const rows = windowsRows.flat()
    const name = metric ?? pickHero(new Set(rows.flatMap((r) => Object.keys(r).filter((k) => k[0] !== '_'))))
    if (!name) return
    const per = Math.ceil(48 / windowsRows.length)
    const values = windowsRows.flatMap((w) => {
      const v = w.map((r) => r[name]).filter((x): x is number => x != null && Number.isFinite(x))
      if (v.length <= per) return v
      return Array.from({ length: per }, (_, i) => {
        const a = Math.floor((i * v.length) / per)
        const b = Math.max(a + 1, Math.floor(((i + 1) * v.length) / per))
        return v.slice(a, b).reduce((x, y) => x + y, 0) / (b - a)
      })
    })
    this.previews[key] = { metric: name, values }
  }

  run(key: string): Run | undefined {
    return this.runs.find((r) => r.key === key)
  }

  /** Parsed metrics for a run, or undefined until loaded. Read `tick` to react to updates. */
  metrics(key: string): RunData | undefined {
    return this.data.get(key)
  }

  /** Loads (or tops up) a run's metrics. Safe to call repeatedly. */
  ensure(key: string): Promise<void> {
    const inflight = this.loading.get(key)
    if (inflight) return inflight
    const p = this.sync(key).finally(() => this.loading.delete(key))
    this.loading.set(key, p)
    return p
  }

  private async sync(key: string) {
    const run = this.run(key)
    const src = this.source
    if (!run || !src) return
    let d = this.data.get(key)
    const fresh = !d
    d ??= new RunData()
    let changed = false
    for (let i = 0; i < run.segments.length; i++) {
      const seg = run.segments[i]
      const have = d.consumed[i] ?? 0
      if (have >= seg.size) continue
      // a segment is only read once earlier ones are complete, so lines never interleave
      if (i > 0 && (d.consumed[i - 1] ?? 0) < run.segments[i - 1].size) break
      const text = await src.read(seg.path, have)
      if (this.source !== src) return
      d.ingest(text)
      d.consumed[i] = have + utf8.encode(text).length
      changed = true
    }
    if (fresh) this.data.set(key, d)
    if (changed || fresh) this.tick++
  }

  private onChanges(changes: FileChange[]) {
    if (changes.some((c) => c.path === '')) {
      this.relist().catch(() => {})
      return
    }
    const touched = new Set<string>()
    const files = { ...this.files }
    const now = Date.now()
    for (const c of changes) {
      if (c.op === 'delete') {
        delete files[c.path]
        continue
      }
      const m = META.exec(c.path)
      if (m) {
        this.pendingMeta.add(`${m[1]}/${m[2]}`)
        files[c.path] = { path: c.path, size: c.size ?? files[c.path]?.size ?? 0, updated: now }
        continue
      }
      const s = SEGMENT.exec(c.path)
      if (!s) continue
      files[c.path] = { path: c.path, size: c.size ?? files[c.path]?.size ?? 0, updated: now }
      touched.add(`${s[1]}/${s[2]}`)
    }
    this.files = files
    for (const key of touched) {
      if (this.data.has(key)) this.ensure(key)
      if (this.previews[key]) this.preview(key, this.previews[key].metric)
    }
    if (this.pendingMeta.size && !this.metaTimer) {
      // meta.json changes with every flush; batch the re-reads
      this.metaTimer = window.setTimeout(() => {
        this.metaTimer = 0
        const keys = [...this.pendingMeta]
        this.pendingMeta.clear()
        keys.forEach((k) => this.loadMeta(k))
      }, 400)
    }
  }
}

async function pool(tasks: (() => Promise<void>)[], n: number) {
  let i = 0
  await Promise.all(
    Array.from({ length: Math.min(n, tasks.length) }, async () => {
      while (i < tasks.length) await tasks[i++]()
    }),
  )
}

export const store = new Store()
