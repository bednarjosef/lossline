// Sign in with Hugging Face, entirely in the browser (OAuth 2 + PKCE, no client secret).
// The client ID is the URL of oauth-client.json, which the build emits next to the app
// (see vite.config.ts), so nothing has to be registered with Hugging Face.

const HUB = 'https://huggingface.co'
const KEY = 'lossline.auth'
const PENDING = 'lossline.oauth'
const SCOPE = 'openid profile read-repos'

export interface Session {
  token: string
  refresh?: string
  expires?: number // ms
  kind: 'oauth' | 'token'
}

const site = __SITE_URL__
const clientId = site ? `${site}oauth-client.json` : ''

/** Sign in with HF works only when served from the URL the build was made for. */
export const oauthAvailable = !!site && location.href.startsWith(site)

function load(): Session | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

function save(s: Session | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s))
    else localStorage.removeItem(KEY)
  } catch {
    // storage blocked: the session lasts until the tab closes
  }
  current = s
}

let current: Session | null = load()

export function session(): Session | null {
  return current
}

export function useToken(token: string) {
  save({ token: token.trim(), kind: 'token' })
}

export function signOut() {
  save(null)
}

function b64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

function randomString(n = 48): string {
  return b64url(crypto.getRandomValues(new Uint8Array(n)))
}

export async function startSignIn() {
  const verifier = randomString()
  const state = randomString(16)
  const challenge = b64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))))
  sessionStorage.setItem(PENDING, JSON.stringify({ verifier, state, hash: location.hash }))
  const q = new URLSearchParams({
    client_id: clientId,
    redirect_uri: site,
    response_type: 'code',
    scope: SCOPE,
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })
  location.assign(`${HUB}/oauth/authorize?${q}`)
}

async function tokenRequest(body: Record<string, string>): Promise<Session> {
  const res = await fetch(`${HUB}/oauth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ client_id: clientId, ...body }),
  })
  if (!res.ok) throw new Error(`Hugging Face refused the sign-in (${res.status}).`)
  const t = await res.json()
  return {
    token: t.access_token,
    refresh: t.refresh_token,
    expires: Date.now() + (t.expires_in ?? 3600) * 1000,
    kind: 'oauth',
  }
}

/** Finishes a sign-in if this page load is the redirect back from Hugging Face. */
export async function completeSignIn(): Promise<void> {
  const q = new URLSearchParams(location.search)
  const code = q.get('code')
  if (!code && !q.get('error')) return
  const pending = JSON.parse(sessionStorage.getItem(PENDING) ?? 'null')
  sessionStorage.removeItem(PENDING)
  history.replaceState(null, '', location.pathname + (pending?.hash ?? ''))
  if (!code) throw new Error('Sign-in was cancelled.')
  if (!pending || pending.state !== q.get('state')) throw new Error('Sign-in expired. Try again.')
  save(await tokenRequest({ grant_type: 'authorization_code', code, redirect_uri: site, code_verifier: pending.verifier }))
}

let refreshing: Promise<void> | null = null

/** A valid access token, refreshing it first if it is about to expire. */
export async function token(): Promise<string | null> {
  const s = current
  if (!s) return null
  if (s.kind === 'oauth' && s.expires && s.expires - Date.now() < 60_000 && s.refresh) {
    refreshing ??= tokenRequest({ grant_type: 'refresh_token', refresh_token: s.refresh })
      .then(save)
      .catch(() => save(null))
      .finally(() => (refreshing = null))
    await refreshing
  }
  return current?.token ?? null
}
