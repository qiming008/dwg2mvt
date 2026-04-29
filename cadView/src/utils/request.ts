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
