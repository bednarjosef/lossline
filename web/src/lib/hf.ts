// Minimal Hugging Face Hub client for buckets. Every request goes straight from the
// browser to huggingface.co with the user's own token.

import { token } from './auth'
import type { FileChange, FileEntry, Source } from './types'

const HUB = 'https://huggingface.co'

export class HubError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

async function hub(url: string, init: RequestInit = {}): Promise<Response> {
  const t = await token()
  const headers = new Headers(init.headers)
  if (t) headers.set('Authorization', `Bearer ${t}`)
  const res = await fetch(url.startsWith('http') ? url : HUB + url, { ...init, headers, cache: 'no-store' })
  if (res.ok || res.status === 206 || res.status === 416) return res
  if (res.status === 401) throw new HubError('Your Hugging Face session has ended. Sign in again.', 401)
  if (res.status === 403 || res.status === 404) throw new HubError('This bucket does not exist, or your account cannot read it.', res.status)
  if (res.status === 429) throw new HubError('Hugging Face is rate limiting this account. Waiting a moment before retrying.', 429)
  throw new HubError(`Hugging Face returned an error (${res.status}).`, res.status)
}

export interface Account {
  name: string
  fullname: string
  avatarUrl: string
  orgs: string[]
}

export async function whoami(): Promise<Account> {
  const d = await (await hub('/api/whoami-v2')).json()
  return {
    name: d.name,
    fullname: d.fullname ?? d.name,
    avatarUrl: d.avatarUrl?.startsWith('http') ? d.avatarUrl : `${HUB}${d.avatarUrl ?? ''}`,
    orgs: (d.orgs ?? []).map((o: { name: string }) => o.name),
  }
}

export interface BucketInfo {
  id: string
  private: boolean
  updated: number
  files: number
}

export async function listBuckets(owner: string): Promise<BucketInfo[]> {
  try {
    const d = await (await hub(`/api/buckets/${owner}`)).json()
    return d.map((b: { id: string; private: boolean; updatedAt: string; totalFiles: number }) => ({
      id: b.id,
      private: b.private,
      updated: Date.parse(b.updatedAt),
      files: b.totalFiles,
    }))
  } catch {
    return []
  }
}

function nextLink(res: Response): string | null {
  const link = res.headers.get('Link')
  const m = link?.match(/<([^>]+)>;\s*rel="next"/)
  return m ? m[1] : null
}

export class BucketSource implements Source {
  kind = 'hf' as const
  constructor(public name: string) {}

  async list(): Promise<FileEntry[]> {
    const out: FileEntry[] = []
    let url: string | null = `/api/buckets/${this.name}/tree?recursive=true`
    while (url) {
      const res = await hub(url)
      for (const f of await res.json()) {
        if (f.type !== 'file') continue
        out.push({ path: f.path, size: f.size, updated: Date.parse(f.uploadedAt ?? f.mtime) })
      }
      url = nextLink(res)
    }
    return out
  }

  async read(path: string, from = 0, to?: number): Promise<string> {
    const ranged = from > 0 || to !== undefined
    const headers: HeadersInit = ranged ? { Range: `bytes=${from}-${to !== undefined ? to - 1 : ''}` } : {}
    const res = await hub(`/buckets/${this.name}/resolve/${path.split('/').map(encodeURIComponent).join('/')}`, { headers })
    if (res.status === 416) return ''
    // A server that ignores Range sends the whole file: drop what we already have.
    if (ranged && res.status === 200) return (await res.text()).slice(from, to)
    return res.text()
  }

  watch(onChange: (changes: FileChange[]) => void): () => void {
    const ctrl = new AbortController()
    let cursor: string | null = null
    let backoff = 1000

    const run = async () => {
      while (!ctrl.signal.aborted) {
        try {
          const q = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
          const res = await hub(`/api/buckets/${this.name}/events${q}`, {
            headers: { Accept: 'text/event-stream' },
            signal: ctrl.signal,
          })
          backoff = 1000
          await readEvents(res, (event, data) => {
            if (data?.cursor) cursor = data.cursor
            if (event === 'changes' && data?.changes) onChange(data.changes)
            if (event === 'reset') {
              cursor = null
              onChange([{ path: '', op: 'update' }]) // tells the store to re-list
            }
          })
        } catch (e) {
          if (ctrl.signal.aborted) return
          const wait = e instanceof HubError && e.status === 429 ? 30_000 : backoff
          backoff = Math.min(backoff * 2, 30_000)
          await new Promise((r) => setTimeout(r, wait))
        }
      }
    }
    run()
    return () => ctrl.abort()
  }
}

/** Parses a server-sent-events body. fetch() is used instead of EventSource because
 * EventSource cannot send the Authorization header. */
async function readEvents(res: Response, on: (event: string, data: any) => void) {
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buf += value
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i)
      buf = buf.slice(i + 2)
      let event = 'message'
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      try {
        on(event, JSON.parse(data))
      } catch {
        // ignore malformed events
      }
    }
  }
}
