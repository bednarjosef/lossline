<script lang="ts">
  // A small area sparkline with an emphasized endpoint.
  let {
    values,
    color = 'var(--c1)',
    height = 56,
  }: { values: number[]; color?: string; height?: number } = $props()

  const W = 200
  const geo = $derived.by(() => {
    const v = values.filter(Number.isFinite)
    if (v.length < 2) return null
    const lo = Math.min(...v)
    const hi = Math.max(...v)
    const pad = 4
    const y = (x: number) => pad + (1 - (x - lo) / (hi - lo || 1)) * (height - pad * 2)
    const pts = v.map((val, i) => [(i / (v.length - 1)) * (W - 6), y(val)] as const)
    const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('')
    return { line, area: `${line}L${W - 6},${height}L0,${height}Z`, end: pts[pts.length - 1] }
  })
</script>

<div class="spark">
<svg viewBox="0 0 {W} {height}" preserveAspectRatio="none" style:height="{height}px" aria-hidden="true">
  {#if geo}
    <path class="area" d={geo.area} style:fill={color} />
    <path class="line" d={geo.line} style:stroke={color} vector-effect="non-scaling-stroke" />
  {/if}
</svg>
{#if geo}
  <span class="end" style:left="{(geo.end[0] / W) * 100}%" style:top="{geo.end[1]}px" style:background={color}></span>
{/if}
</div>

<style>
  .spark {
    position: relative;
  }
  svg {
    display: block;
    width: 100%;
    overflow: visible;
  }
  .area {
    opacity: 0.1;
  }
  .line {
    fill: none;
    stroke-width: 1.75;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .end {
    position: absolute;
    width: 7px;
    height: 7px;
    margin: -3.5px 0 0 -3.5px;
    border-radius: 50%;
    box-shadow: 0 0 0 2px var(--raised);
  }
</style>
