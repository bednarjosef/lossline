<script lang="ts">
  import uPlot from 'uplot'
  import 'uplot/dist/uPlot.min.css'
  import { onMount } from 'svelte'
  import { build, nearest, type Line } from '../lib/series'
  import { ui, cssVar } from '../lib/ui.svelte'
  import { clock, fmt, fmtStep } from '../lib/format'

  let {
    lines,
    height,
    log = false,
    names,
    big = false,
    onpick,
  }: {
    lines: Line[]
    height: number
    log?: boolean
    names: Map<string, string>
    big?: boolean
    onpick?: () => void
  } = $props()

  let el: HTMLDivElement
  let tip: HTMLDivElement
  let plot: uPlot | null = null
  let inside = false
  let revealed = $state(false)

  const built = $derived(
    build(lines, { x: ui.x, smoothing: ui.smoothing, points: big ? 1600 : 700, range: ui.zoom }),
  )
  const empty = $derived(built.data.length < 2 || (built.data[0] as number[]).length === 0)

  // canvas can't read CSS variables, so resolve the theme's colors whenever it changes
  let ink = { axis: '#858a96', grid: '#e2e4e9', surface: '#fff', slots: [] as string[] }
  function readTheme() {
    ink = {
      axis: cssVar('--ink-3'),
      grid: cssVar('--line'),
      surface: cssVar('--raised'),
      slots: Array.from({ length: 8 }, (_, i) => cssVar(`--c${i + 1}`)),
    }
  }

  function alpha(hex: string, a: number) {
    const n = parseInt(hex.slice(1), 16)
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
  }

  function stroke(key: string, slot: number, raw: boolean) {
    return () => {
      const c = ink.slots[slot] ?? '#888'
      const other = ui.hoverRun && ui.hoverRun !== key
      if (raw) return alpha(c, other ? 0.05 : 0.2)
      return other ? alpha(c, 0.16) : c
    }
  }

  // round elapsed-time ticks: seconds, minutes, hours, days
  const TIME_INCRS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800]

  const font = (px: number) => `${px}px 'Martian Mono Variable', ui-monospace, monospace`

  function measure(u: uPlot, values: string[] | null) {
    if (!values?.length) return 40
    const ctx = u.ctx
    ctx.save()
    ctx.font = font(big ? 11 : 10)
    const w = Math.max(...values.map((v) => ctx.measureText(v).width))
    ctx.restore()
    return Math.ceil(w) + 16
  }

  function opts(width: number): uPlot.Options {
    const xfmt = (v: number) => (ui.x === 'step' ? fmtStep(v) : clock(v))
    return {
      width,
      height,
      padding: [big ? 14 : 10, big ? 22 : 16, 0, 0],
      legend: { show: false },
      scales: {
        x: { time: false },
        y: log ? { distr: 3, log: 10 } : { distr: 1 },
      },
      axes: [
        {
          stroke: () => ink.axis,
          grid: { stroke: () => ink.grid, width: 1 },
          ticks: { show: false },
          font: font(big ? 11 : 10),
          size: big ? 34 : 28,
          gap: 4,
          space: big ? 90 : 64,
          incrs: ui.x === 'time' ? TIME_INCRS : undefined,
          values: (_u, vals) => vals.map(xfmt),
        },
        {
          stroke: () => ink.axis,
          grid: { stroke: () => ink.grid, width: 1 },
          ticks: { show: false },
          font: font(big ? 11 : 10),
          gap: 6,
          space: big ? 44 : 32,
          size: (u, values) => measure(u, values),
          values: (_u, vals) => vals.map((v) => fmt(v, 3)),
        },
      ],
      series: [
        {},
        ...built.layout.map((l) => ({
          stroke: stroke(l.key, l.slot, l.raw),
          width: l.raw ? 1 : big ? 2 : 1.75,
          spanGaps: true,
          points: l.raw
            ? { show: false }
            : { show: false, size: 8, width: 2, stroke: () => ink.surface, fill: () => ink.slots[l.slot] },
        })),
      ],
      cursor: {
        sync: { key: 'lossline', setSeries: false },
        drag: { x: true, y: false, setScale: false },
        points: {
          size: 9,
          width: 2,
          stroke: () => ink.surface,
          fill: (u, si) => (built.layout[si - 1]?.raw ? 'transparent' : ink.slots[built.layout[si - 1]?.slot ?? 0]),
        },
        bind: {
          dblclick: () => () => {
            ui.zoom = null
            return null
          },
        },
      },
      hooks: {
        setSelect: [
          (u) => {
            if (u.select.width > 6) {
              const a = u.posToVal(u.select.left, 'x')
              const b = u.posToVal(u.select.left + u.select.width, 'x')
              ui.zoom = [a, b]
            }
            u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false)
          },
        ],
        setCursor: [(u) => renderTip(u)],
        draw: [(u) => drawEnds(u)],
      },
    }
  }

  /** endpoint dot on each line: where the run is now */
  function drawEnds(u: uPlot) {
    const ctx = u.ctx
    const xs = u.data[0] as number[]
    const r = (big ? 4 : 3.2) * uPlot.pxRatio
    built.layout.forEach((l, i) => {
      if (l.raw) return
      const ys = u.data[i + 1] as (number | null)[]
      let j = ys.length - 1
      while (j >= 0 && ys[j] == null) j--
      if (j < 0) return
      const x = u.valToPos(xs[j], 'x', true)
      const y = u.valToPos(ys[j]!, 'y', true)
      if (x < u.bbox.left - 1 || x > u.bbox.left + u.bbox.width + 1) return
      const faded = ui.hoverRun && ui.hoverRun !== l.key
      ctx.save()
      ctx.globalAlpha = faded ? 0.2 : 1
      ctx.beginPath()
      ctx.arc(x, y, r + 2 * uPlot.pxRatio, 0, Math.PI * 2)
      ctx.fillStyle = ink.surface
      ctx.fill()
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fillStyle = ink.slots[l.slot]
      ctx.fill()
      ctx.restore()
    })
  }

  function renderTip(u: uPlot) {
    const idx = u.cursor.idx
    if (!inside || idx == null || empty) {
      tip.hidden = true
      return
    }
    const xs = u.data[0] as number[]
    const rows: { key: string; slot: number; v: number }[] = []
    built.layout.forEach((l, i) => {
      if (l.raw) return
      const j = nearest(u.data, i + 1, idx)
      if (j == null) return
      // ignore values far from the pointer (a run that ended long before this x)
      const span = (u.scales.x.max ?? 0) - (u.scales.x.min ?? 0)
      if (Math.abs(xs[j] - xs[idx]) > span * 0.03) return
      rows.push({ key: l.key, slot: l.slot, v: (u.data[i + 1] as number[])[j] })
    })
    if (!rows.length) {
      tip.hidden = true
      return
    }
    rows.sort((a, b) => b.v - a.v)
    tip.replaceChildren()
    const head = document.createElement('div')
    head.className = 'tip-x'
    head.textContent = ui.x === 'step' ? `step ${fmtStep(xs[idx])}` : clock(xs[idx])
    tip.append(head)
    for (const r of rows) {
      const row = document.createElement('div')
      row.className = 'tip-row'
      if (ui.hoverRun && ui.hoverRun !== r.key) row.classList.add('dim')
      const key = document.createElement('i')
      key.style.background = ink.slots[r.slot]
      const val = document.createElement('b')
      val.textContent = fmt(r.v, 5)
      const name = document.createElement('span')
      name.textContent = names.get(r.key) ?? r.key
      row.append(key, val, name)
      tip.append(row)
    }
    tip.hidden = false
    const left = u.cursor.left ?? 0
    const top = u.cursor.top ?? 0
    const w = tip.offsetWidth
    const h = tip.offsetHeight
    const W = el.clientWidth
    const x = left + u.bbox.left / uPlot.pxRatio
    tip.style.transform = `translate(${x + 16 + w > W ? x - w - 16 : x + 16}px, ${Math.max(0, Math.min(top - h / 2, height - h))}px)`
  }

  const shapeKey = () => `${built.layout.map((l) => `${l.key}:${l.slot}:${l.raw}`).join('|')}#${log}#${ui.x}#${height}`

  function create() {
    plot?.destroy()
    plot = null
    shape = ''
    // uPlot can't lay out axes without data or width; wait until there is both
    if (empty || !el?.clientWidth) return
    readTheme()
    shape = shapeKey()
    plot = new uPlot(opts(el.clientWidth), built.data, el)
    const over = plot.over
    let down: [number, number] | null = null
    over.addEventListener('pointerenter', () => (inside = true))
    over.addEventListener('pointerleave', () => {
      inside = false
      tip.hidden = true
    })
    over.addEventListener('pointerdown', (e) => (down = [e.clientX, e.clientY]))
    over.addEventListener('pointerup', (e) => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 4) onpick?.()
      down = null
    })
    applyZoom()
  }

  function applyZoom() {
    if (!plot) return
    const z = ui.zoom
    const xs = plot.data[0] as number[]
    if (!xs.length) return
    if (z) plot.setScale('x', { min: z[0], max: z[1] })
    else if (xs[0] === xs[xs.length - 1]) plot.setScale('x', { min: xs[0] - 1, max: xs[0] + 1 })
    else plot.setScale('x', { min: xs[0], max: xs[xs.length - 1] })
  }

  onMount(() => {
    create()
    const ro = new ResizeObserver(() => {
      if (!plot) create()
      else if (el.clientWidth && plot.width !== el.clientWidth) plot.setSize({ width: el.clientWidth, height })
    })
    ro.observe(el)
    document.fonts?.ready.then(() => plot?.redraw(false, true))
    return () => {
      ro.disconnect()
      plot?.destroy()
      plot = null
    }
  })

  // structure changes (series added/removed, log scale, axis mode) rebuild the plot
  let shape = ''
  $effect(() => {
    const s = shapeKey()
    if (!plot || s !== shape) {
      create()
    } else {
      plot.setData(built.data, false)
      applyZoom()
    }
    if (!empty && !revealed) revealed = true
  })

  $effect(() => {
    void ui.zoom
    applyZoom()
  })

  $effect(() => {
    void ui.dark
    readTheme()
    plot?.redraw(false, true)
  })

  $effect(() => {
    void ui.hoverRun
    plot?.redraw(false, false)
  })
</script>

<div class="chart" class:big class:revealed class:empty style:height="{height}px">
  <div class="plot" bind:this={el}></div>
  <div class="tip" bind:this={tip} hidden></div>
</div>

<style>
  .chart {
    position: relative;
    width: 100%;
  }
  .plot {
    width: 100%;
    height: 100%;
    clip-path: inset(0 100% 0 0);
  }
  .revealed .plot {
    animation: reveal 1.1s var(--ease) forwards;
  }
  @keyframes reveal {
    to {
      clip-path: inset(0 0 0 0);
    }
  }
  .plot :global(.u-over) {
    cursor: crosshair;
  }
  .plot :global(.u-select) {
    background: var(--wash-2);
    border-inline: 1px solid var(--line-2);
  }
  .plot :global(.u-cursor-x) {
    border-right: 1px solid var(--line-2);
  }
  .plot :global(.u-cursor-y) {
    display: none;
  }

  .tip {
    position: absolute;
    top: 0;
    left: 0;
    z-index: 5;
    pointer-events: none;
    display: grid;
    gap: 3px;
    min-width: 150px;
    max-width: 280px;
    padding: 8px 10px 9px;
    border-radius: var(--r);
    background: color-mix(in srgb, var(--raised) 94%, transparent);
    backdrop-filter: blur(8px);
    box-shadow:
      0 0 0 1px var(--line),
      var(--shadow);
    font-size: 12px;
    transition: transform 0.06s linear;
  }
  .tip[hidden] {
    display: none;
  }
  .tip :global(.tip-x) {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-3);
    margin-bottom: 2px;
  }
  .tip :global(.tip-row) {
    display: grid;
    grid-template-columns: 12px auto 1fr;
    align-items: center;
    gap: 8px;
  }
  .tip :global(.tip-row.dim) {
    opacity: 0.4;
  }
  .tip :global(.tip-row i) {
    width: 12px;
    height: 2.5px;
    border-radius: 2px;
  }
  .tip :global(.tip-row b) {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    color: var(--ink);
  }
  .tip :global(.tip-row span) {
    color: var(--ink-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
