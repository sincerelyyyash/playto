/** API client: all paths are under `/api/v1/` (Vite dev proxy → Django). */

export const AUTH_TOKEN_STORAGE_KEY = 'playto_auth_token'

function apiUrl(path: string): string {
  const p = path.replace(/^\//, '')
  return `/api/v1/${p}`
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
    const t = sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
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
