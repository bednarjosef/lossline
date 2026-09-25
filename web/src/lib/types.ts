export type Status = 'running' | 'finished' | 'failed' | 'stalled'

/** meta.json, as written by the logger (docs/format.md). */
export interface RunMeta {
  format: number
  project: string
  id: string
  name: string
  status: 'running' | 'finished' | 'failed'
  created: string
  heartbeat: string
  ended: string | null
  flush_interval: number
  config: Record<string, unknown>
  summary: Record<string, number | null>
  system: Record<string, string>
  git: { commit?: string; branch?: string; dirty?: boolean } | null
  tags: string[]
  notes: string
  segments: number
  rows: number
}

/** A file in the bucket (or the demo's in-memory stand-in for one). */
export interface FileEntry {
  path: string
  size: number
  updated: number // ms
}

export interface FileChange {
  path: string
  op: 'add' | 'update' | 'delete'
  size?: number
}

/** Where runs come from. Deliberately file-shaped so every source behaves the same. */
export interface Source {
  kind: 'hf' | 'demo'
  /** e.g. "josefbednar/lossline" */
  name: string
  list(): Promise<FileEntry[]>
  /** Text of the file from byte `from` up to (not including) byte `to`, or to the end. */
  read(path: string, from?: number, to?: number): Promise<string>
  /** Calls back with file changes until the returned function is called. */
  watch(onChange: (changes: FileChange[]) => void): () => void
}

export interface MetricSeries {
  step: number[]
  time: number[]
  value: (number | null)[]
}

export interface Run {
  key: string // project/id
  project: string
  id: string
  meta: RunMeta | null
  status: Status
  created: number // ms
  updated: number // ms
  segments: FileEntry[]
}

export interface Project {
  name: string
  runs: Run[]
  updated: number
  live: number
}
