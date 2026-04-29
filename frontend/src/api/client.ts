/** API client: paths under `/api/v1/`. Dev: Vite proxies `/api` to Django. Prod: set `VITE_API_BASE_URL`. */

export const AUTH_TOKEN_STORAGE_KEY = 'playto_auth_token'

export function getStoredAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
}

export function setStoredAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token)
}

export function clearStoredAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
}

function apiUrl(path: string): string {
  const p = path.replace(/^\//, '')
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
  const suffix = `/api/v1/${p}`
  if (!base) return suffix
  return `${base}${suffix}`
}

export type ApiFetchOptions = RequestInit & {
  skipAuth?: boolean
  idempotencyKey?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function formatApiError(body: unknown, status: number): string {
  if (body && typeof body === 'object') {
    const o = body as Record<string, unknown>
    if (typeof o.detail === 'string') return o.detail
    if (typeof o.detail === 'object' && o.detail !== null) {
      return JSON.stringify(o.detail)
    }
    if (typeof o.error === 'string' && typeof o.detail === 'string') {
      return `${o.detail}`
    }
    if (typeof o.error === 'string') return o.error
  }
  return `Request failed (${status})`
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { skipAuth, idempotencyKey, ...init } = options
  const url = apiUrl(path)
  const headers = new Headers(init.headers)
  if (
    init.body !== undefined &&
    init.body !== null &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json')
  }
  if (!skipAuth) {
    const t = getStoredAuthToken()
    if (t) headers.set('Authorization', `Token ${t}`)
  }
  if (idempotencyKey) {
    headers.set('Idempotency-Key', idempotencyKey)
  }

  const res = await fetch(url, { ...init, headers })
  const text = await res.text()
  let json: unknown = null
  if (text) {
    try {
      json = JSON.parse(text) as unknown
    } catch {
      json = { raw: text }
    }
  }

  if (!res.ok) {
    throw new ApiError(formatApiError(json, res.status), res.status, json)
  }

  return json as T
}
