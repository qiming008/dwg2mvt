import { getAuthToken } from './auth'

export function createAuthHeaders(extra: HeadersInit = {}) {
  const headers = new Headers(extra)
  const token = getAuthToken()
  if (token) {
    headers.set('Authorization', token)
  }
  return headers
}

export function headersToRecord(headers: Headers) {
  const record: Record<string, string> = {}
  headers.forEach((value, key) => {
    record[key] = value
  })
  return record
}

export async function requestJson<T>(input: RequestInfo | URL, init: RequestInit = {}) {
  const res = await fetch(input, {
    ...init,
    headers: createAuthHeaders(init.headers),
  })

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`)
  }

  return (await res.json()) as T
}

export type PluginRequestConfig = {
  url: string
  method?: string
  data?: unknown
  params?: Record<string, unknown>
  headers?: HeadersInit
}

export function createPluginRequestClient() {
  return async function pluginRequest<T = unknown>(config: PluginRequestConfig): Promise<T> {
    const method = (config.method || 'get').toUpperCase()
    const url = new URL(config.url, window.location.origin)

    if (config.params && method === 'GET') {
      Object.entries(config.params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, String(value))
        }
      })
    }

    const init: RequestInit = {
      method,
      headers: createAuthHeaders(config.headers),
    }

    if (config.data !== undefined && method !== 'GET') {
      init.body = typeof config.data === 'string' ? config.data : JSON.stringify(config.data)
      if (!(init.headers instanceof Headers)) {
        init.headers = new Headers(init.headers)
      }
      init.headers.set('Content-Type', 'application/json')
    }

    return requestJson<T>(url, init)
  }
}
