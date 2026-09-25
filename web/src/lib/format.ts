/** Compact number for axes and readouts: 0.000312 → 3.12e-4, 12840 → 12.8k. */
export function fmt(v: number | null | undefined, digits = 4): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  if (a === 0) return '0'
  if (a >= 1e15 || a < 1e-4) return v.toExponential(2).replace('e+', 'e')
  if (a >= 1e4) return compact(v)
  const s = v.toPrecision(digits)
  return s.includes('e') ? Number(s).toString() : trimZeros(s)
}

function trimZeros(s: string): string {
  return s.includes('.') ? s.replace(/\.?0+$/, '') : s
}

export function compact(v: number): string {
  const a = Math.abs(v)
  const units: [number, string][] = [
    [1e12, 'T'],
    [1e9, 'B'],
    [1e6, 'M'],
    [1e3, 'k'],
  ]
  for (const [n, u] of units) {
    if (a >= n) return trimZeros((v / n).toFixed(a / n >= 100 ? 0 : a / n >= 10 ? 1 : 2)) + u
  }
  return trimZeros(v.toFixed(a >= 100 ? 0 : a >= 10 ? 1 : 2))
}

export function fmtStep(v: number): string {
  return Math.abs(v) >= 1e4 ? compact(v) : Math.round(v).toLocaleString('en-US')
}

/** 3725 s → "1h 2m" */
export function duration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  const s = Math.floor(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  const h = Math.floor(m / 60)
  if (h < 48) return `${h}h ${m % 60}m`
  return `${Math.floor(h / 24)}d ${h % 24}h`
}

/** Axis label for elapsed seconds: 0, 30s, 5m, 1h, 1h30 */
export function clock(seconds: number): string {
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m${s % 60 ? String(s % 60).padStart(2, '0') : ''}`
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  return m ? `${h}h${String(m).padStart(2, '0')}` : `${h}h`
}

export function ago(ms: number, now = Date.now()): string {
  const s = Math.max(0, (now - ms) / 1000)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  if (s < 86400 * 30) return `${Math.round(s / 86400)}d ago`
  return new Date(ms).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function when(ms: number): string {
  return new Date(ms).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function configValue(v: unknown): string {
  if (v == null) return 'null'
  if (typeof v === 'number') return fmt(v, 6)
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}
