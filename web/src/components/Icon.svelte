<script lang="ts">
  let { name, size = 18 }: { name: string; size?: number } = $props()

  const paths: Record<string, string> = {
    sun: 'M12 4V2m0 20v-2m8-8h2M2 12h2m13.66-5.66 1.41-1.41M4.93 19.07l1.41-1.41m0-11.32L4.93 4.93m14.14 14.14-1.41-1.41M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
    moon: 'M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z',
    search: 'm20 20-4.2-4.2M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z',
    x: 'M18 6 6 18M6 6l12 12',
    check: 'm5 12.5 4.5 4.5L19 7',
    chevron: 'm7 10 5 5 5-5',
    back: 'M15 18 9 12l6-6',
    logout: 'M15 17l5-5-5-5m5 5H9m3 9H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h6',
    runs: 'M4 6h16M4 12h16M4 18h10',
    copy: 'M9 9h10v10H9zM5 15V5h10',
    solo: 'M12 3v18M3 12h18',
    reset: 'M4 12a8 8 0 1 0 2.5-5.8M4 4v4h4',
    log: 'M4 20c4 0 5-3 6-7s2-9 10-9',
    arrow: 'M5 12h14m-6-6 6 6-6 6',
    bucket: 'M4 7h16l-1.5 12.2A2 2 0 0 1 16.5 21h-9a2 2 0 0 1-2-1.8L4 7Zm0 0c0-2 3.6-3.5 8-3.5S20 5 20 7',
  }
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.75"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"><path d={paths[name]} /></svg>
