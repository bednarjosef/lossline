import uPlot from 'uplot'
import type { MetricSeries } from './types'

/**
 * Debiased exponential moving average whose strength depends on x spacing, not point
 * count: the same slider setting smooths a metric logged every step and one logged
 * every 500 steps over the same stretch of the x axis. Nulls are skipped.
 */
export function ema(xs: number[], ys: (number | null)[], weight: number): (number | null)[] {
  if (weight <= 0 || xs.length < 2) return ys
  // as if the series had 1000 evenly spaced points
  const ref = (xs[xs.length - 1] - xs[0]) / 1000 || 1
  let last = 0
  let norm = 0
  let prev = xs[0]
  return ys.map((y, i) => {
    if (y == null || !Number.isFinite(y)) return null
    const w = Math.pow(weight, Math.max(xs[i] - prev, ref) / ref)
    prev = xs[i]
    last = w * last + (1 - w) * y
    norm = w * norm + (1 - w)
    return last / norm
  })
}

/** Largest-Triangle-Three-Buckets: indices of `n` points that keep the curve's shape. */
export function lttb(xs: number[], ys: (number | null)[], n: number): number[] {
  const idx: number[] = []
  for (let i = 0; i < xs.length; i++) if (ys[i] != null) idx.push(i)
  if (idx.length <= n || n < 3) return idx
  const out = [idx[0]]
  const every = (idx.length - 2) / (n - 2)
  let a = 0
  for (let i = 0; i < n - 2; i++) {
    const start = Math.floor((i + 1) * every) + 1
    const end = Math.min(Math.floor((i + 2) * every) + 1, idx.length)
    let ax = 0
    let ay = 0
    for (let j = start; j < end; j++) {
      ax += xs[idx[j]]
      ay += ys[idx[j]]!
    }
    ax /= end - start || 1
    ay /= end - start || 1
    const rs = Math.floor(i * every) + 1
    const re = Math.floor((i + 1) * every) + 1
    const px = xs[idx[a]]
    const py = ys[idx[a]]!
    let best = -1
    let pick = rs
    for (let j = rs; j < re; j++) {
      const area = Math.abs((px - ax) * (ys[idx[j]]! - py) - (px - xs[idx[j]]) * (ay - py))
      if (area > best) {
        best = area
        pick = j
      }
    }
    out.push(idx[pick])
    a = pick
  }
  out.push(idx[idx.length - 1])
  return out
}

export interface Line {
  key: string
  slot: number
  series: MetricSeries
  t0: number
}

export interface Built {
  data: uPlot.AlignedData
  /** for each drawn line after x: which run, and whether it is the raw or smoothed trace */
  layout: { key: string; slot: number; raw: boolean }[]
  positive: boolean
}

/**
 * Turns per-run series into uPlot's aligned table. Each run contributes its smoothed
 * line, plus a faint raw line underneath when smoothing is on.
 */
export function build(
  lines: Line[],
  opts: { x: 'step' | 'time'; smoothing: number; points: number; range?: [number, number] | null },
): Built {
  const tables: uPlot.AlignedData[] = []
  const layout: Built['layout'] = []
  let positive = true
  const smooth = opts.smoothing > 0

  for (const l of lines) {
    const s = l.series
    // dedupe x (keep the last value logged for a step)
    const xs: number[] = []
    const ys: (number | null)[] = []
    for (let i = 0; i < s.step.length; i++) {
      const x = opts.x === 'step' ? s.step[i] : s.time[i] - l.t0
      const y = s.value[i]
      if (y != null && y <= 0) positive = false
      if (xs.length && x <= xs[xs.length - 1]) {
        if (x === xs[xs.length - 1]) ys[ys.length - 1] = y
        continue
      }
      xs.push(x)
      ys.push(y)
    }
    if (!xs.length) continue
    let sm = ema(xs, ys, opts.smoothing)
    if (opts.range) {
      // zoomed: sample only the visible window (plus a margin) at full detail
      const [a, b] = opts.range
      const pad = (b - a) * 0.05
      let i0 = 0
      while (i0 < xs.length && xs[i0] < a - pad) i0++
      let i1 = xs.length
      while (i1 > i0 && xs[i1 - 1] > b + pad) i1--
      // keep one point either side so lines run to the edge
      i0 = Math.max(0, i0 - 1)
      i1 = Math.min(xs.length, i1 + 1)
      xs.splice(i1)
      ys.splice(i1)
      sm = sm.slice(0, i1)
      xs.splice(0, i0)
      ys.splice(0, i0)
      sm = sm.slice(i0)
    }
    const keep = lttb(xs, smooth ? sm : ys, opts.points)
    const kx = keep.map((i) => xs[i])
    if (smooth) {
      // raw keeps its own shape (spikes matter), sampled independently
      const rawKeep = lttb(xs, ys, opts.points)
      const merged = [...new Set([...keep, ...rawKeep])].sort((a, b) => a - b)
      tables.push([merged.map((i) => xs[i]), merged.map((i) => ys[i]), merged.map((i) => sm[i])] as uPlot.AlignedData)
      layout.push({ key: l.key, slot: l.slot, raw: true }, { key: l.key, slot: l.slot, raw: false })
    } else {
      tables.push([kx, keep.map((i) => ys[i])] as uPlot.AlignedData)
      layout.push({ key: l.key, slot: l.slot, raw: false })
    }
  }

  if (!tables.length) return { data: [[]], layout, positive }
  const data = tables.length === 1 ? tables[0] : uPlot.join(tables)
  return { data, layout, positive }
}

/** Nearest non-null value of series `si` around aligned index `idx`, within `window` indices. */
export function nearest(data: uPlot.AlignedData, si: number, idx: number, window = 400): number | null {
  const ys = data[si] as (number | null)[]
  for (let d = 0; d <= window; d++) {
    const l = ys[idx - d]
    if (l != null) return idx - d
    const r = ys[idx + d]
    if (r != null) return idx + d
  }
  return null
}
