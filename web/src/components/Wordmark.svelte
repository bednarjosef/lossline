<script lang="ts">
  let { size = 18 }: { size?: number } = $props()
</script>

<span class="mark" style:font-size="{size}px">
  <svg viewBox="0 0 28 20" aria-hidden="true">
    <path d="M2 2.5c1.8 8 3.8 12 7.8 13.4S19 17.5 24 17.5" />
    <circle cx="24" cy="17.5" r="2.4" />
  </svg>
  <span>lossline</span>
</span>

<style>
  .mark {
    display: inline-flex;
    align-items: center;
    gap: 0.42em;
    font-weight: 650;
    letter-spacing: -0.035em;
    line-height: 1;
  }
  svg {
    width: 1.4em;
    height: 1em;
    overflow: visible;
  }
  path {
    fill: none;
    stroke: currentColor;
    stroke-width: 2.4;
    stroke-linecap: round;
    stroke-dasharray: 40;
    stroke-dashoffset: 0;
    animation: draw 1.2s var(--ease) both;
  }
  circle {
    fill: var(--c1);
    animation: pop 0.5s 0.9s var(--ease) both;
    transform-origin: 24px 17.5px;
  }
  @keyframes draw {
    from {
      stroke-dashoffset: 40;
    }
  }
  @keyframes pop {
    from {
      transform: scale(0);
    }
  }
</style>
