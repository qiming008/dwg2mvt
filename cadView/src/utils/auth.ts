import { ref } from 'vue'

const TOKEN_KEYS = ['access_token', 'accessToken', 'token']
let runtimeToken = ''
let runtimeOrgNode: unknown = null
export const runtimeOrgNodeVersion = ref(0)

function normalizeBearer(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return ''
  if (/^Bearer\s+/i.test(trimmed)) return trimmed
  return `Bearer ${trimmed}`
}

function unwrapStoredToken(raw: string | null) {
  if (!raw) return ''

  const trimmed = raw.trim()
  if (!trimmed) return ''

  try {
    const parsed = JSON.parse(trimmed) as {
      content?: unknown
      access_token?: unknown
      token?: unknown
      value?: unknown
    }

    const candidate =
      parsed.content ?? parsed.access_token ?? parsed.token ?? parsed.value ?? ''

    if (typeof candidate === 'string') {
      return candidate
    }
  } catch {
    // Not a wrapped storage object.
  }

  return trimmed
}

export function getAuthToken() {
  if (runtimeToken) {
    return normalizeBearer(runtimeToken)
  }

  const fromQuery = new URLSearchParams(window.location.search)
  const queryToken = fromQuery.get('token') || fromQuery.get('access_token')
  if (queryToken) {
    return normalizeBearer(queryToken)
  }

  for (const key of TOKEN_KEYS) {
    const sessionToken = unwrapStoredToken(window.sessionStorage.getItem(key))
    if (sessionToken) {
      return normalizeBearer(sessionToken)
    }

    const localToken = unwrapStoredToken(window.localStorage.getItem(key))
    if (localToken) {
      return normalizeBearer(localToken)
    }
  }

  return ''
}

export function setRuntimeAuthToken(token: string | undefined | null) {
  runtimeToken = token?.trim() || ''
}

export function clearRuntimeAuthToken() {
  runtimeToken = ''
}

export function setRuntimeOrgNode(node: unknown) {
  runtimeOrgNode = node ?? null
  runtimeOrgNodeVersion.value += 1
}

export function getRuntimeOrgNode() {
  return runtimeOrgNode
}
