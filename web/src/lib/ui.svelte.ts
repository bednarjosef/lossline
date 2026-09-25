// View state that belongs to this viewer: theme, chart settings, which runs are shown.
// Kept in localStorage when available; everything works without it.

import type { Run } from './types'

export const SLOTS = 8

type Theme = 'system' | 'light' | 'dark'

interface Selection {
  /** run id → color slot (0..7) for runs currently shown */
  slots: Record<string, number>
  /** every run id this viewer has seen in the project, so new runs can join automatically */
  seen: string[]
}

interface Saved {
  theme: Theme
  x: 'step' | 'time'
  smoothing: number
  logY: Record<string, boolean>
  hero: Record<string, string>
  selection: Record<string, Selection>
  source: { kind: 'hf' | 'demo'; bucket?: string } | null
}

const KEY = 'lossline.prefs'

function load(): Partial<Saved> {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}')
  } catch {
    return {}
  }
}

class UI {
  theme = $state<Theme>('system')
  x = $state<'step' | 'time'>('step')
  smoothing = $state(0.9)
  logY = $state<Record<string, boolean>>({})
  hero = $state<Record<string, string>>({})
  selection = $state<Record<string, Selection>>({})
  source = $state<Saved['source']>(null)

  /** x-range zoom shared by every chart in a project; null = full range */
  zoom = $state<[number, number] | null>(null)
  /** run key under the pointer in the run list, highlighted in every chart */
  hoverRun = $state<string | null>(null)
  dark = $state(false)

  constructor() {
    const s = load()
    if (s.theme) this.theme = s.theme
    if (s.x) this.x = s.x
    if (typeof s.smoothing === 'number') this.smoothing = s.smoothing
    if (s.logY) this.logY = s.logY
    if (s.hero) this.hero = s.hero
    if (s.selection) this.selection = s.selection
    if (s.source) this.source = s.source

    const mq = matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const root = document.documentElement
      if (this.theme === 'system') delete root.dataset.theme
      else root.dataset.theme = this.theme
      this.dark = this.theme === 'dark' || (this.theme === 'system' && mq.matches)
    }
    mq.addEventListener('change', apply)

    $effect.root(() => {
      $effect(() => {
        void this.theme
        apply()
      })
      $effect(() => {
        const saved: Saved = {
          theme: this.theme,
          x: this.x,
          smoothing: this.smoothing,
          logY: this.logY,
          hero: this.hero,
          selection: this.selection,
          source: this.source,
        }
        try {
          localStorage.setItem(KEY, JSON.stringify(saved))
          localStorage.setItem('lossline.theme', this.theme)
        } catch {
          // storage blocked; settings last for this visit
        }
      })
    })
  }

  toggleTheme() {
    this.theme = this.dark ? 'light' : 'dark'
  }

  /**
   * Which runs of a project are drawn, and in which color. Colors follow the run:
   * a run keeps its slot while shown. New runs join automatically while slots are free.
   */
  shown(project: string, runs: Run[]): Map<string, number> {
    const slots = this.selection[project]?.slots ?? initial(runs).slots
    const out = new Map<string, number>()
    for (const r of runs) if (slots[r.id] !== undefined) out.set(r.key, slots[r.id])
    return out
  }

  /** Records the selection and lets new runs join. Call from an effect, not while rendering. */
  syncSelection(project: string, runs: Run[]) {
    const sel = this.selection[project]
    if (!sel) {
      if (runs.length) this.selection[project] = initial(runs)
      return
    }
    const fresh = runs.filter((r) => !sel.seen.includes(r.id)).reverse()
    if (!fresh.length) return
    for (const r of fresh) {
      const slot = freeSlot(sel.slots)
      if (slot >= 0) sel.slots[r.id] = slot
    }
    sel.seen = runs.map((r) => r.id)
  }

  /** Returns false when all color slots are taken. */
  toggleRun(project: string, id: string): boolean {
    const sel = this.selection[project]
    if (!sel) return false
    if (sel.slots[id] !== undefined) {
      delete sel.slots[id]
      return true
    }
    const slot = freeSlot(sel.slots)
    if (slot < 0) return false
    sel.slots[id] = slot
    return true
  }

  solo(project: string, id: string) {
    const sel = this.selection[project]
    if (!sel) return
    const slot = sel.slots[id] ?? 0
    sel.slots = { [id]: slot }
  }
}

/** First visit: the six most recent runs, oldest first so colors read in order. */
function initial(runs: Run[]): Selection {
  const pick = runs.slice(0, 6).reverse()
  return { slots: Object.fromEntries(pick.map((r, i) => [r.id, i])), seen: runs.map((r) => r.id) }
}

function freeSlot(slots: Record<string, number>): number {
  const used = new Set(Object.values(slots))
  for (let i = 0; i < SLOTS; i++) if (!used.has(i)) return i
  return -1
}

export const ui = new UI()

export function color(slot: number): string {
  return `var(--c${slot + 1})`
}

/** Resolved hex for canvas drawing (canvas can't read CSS variables). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

// ------------------------------------------------------------------ routing

export type Route = { view: 'home' } | { view: 'project'; project: string; run: string | null }

function parse(): Route {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  if (parts[0] === 'p' && parts[1]) return { view: 'project', project: parts[1], run: parts[2] ?? null }
  return { view: 'home' }
}

class Router {
  route = $state<Route>(parse())
  constructor() {
    addEventListener('hashchange', () => (this.route = parse()))
  }
  go(path: string) {
    if (location.hash !== path) location.hash = path
  }
}

export const router = new Router()

export function projectPath(p: string) {
  return `#/p/${encodeURIComponent(p)}`
}

export function runPath(p: string, id: string) {
  return `#/p/${encodeURIComponent(p)}/${encodeURIComponent(id)}`
}
