import { requestJson } from '../utils/request'
import { API_ROUTES } from './routes'
import type { SeamOption } from '../types'

interface MinecodeItem {
  createBy?: string | null
  delFlag?: string | null
  id?: string
  parentId?: string | null
  label?: string
  remarks?: string | null
  sort?: number | null
  updateBy?: string | null
  valuea?: string
}

interface MinecodeResponse {
  code?: number
  data?: MinecodeItem[] | SeamOption[]
  rows?: MinecodeItem[] | SeamOption[]
}

function normalizeItem(item: MinecodeItem): SeamOption {
  return {
    id: item.id,
    label: String(item.label ?? ''),
    valuea: String(item.valuea ?? ''),
    remarks: item.remarks ?? null,
  }
}

export async function fetchMinecodeOptions() {
  const payload = await requestJson<MinecodeResponse | MinecodeItem[] | SeamOption[]>(
    API_ROUTES.minecodeDictList,
    { method: 'GET' },
  )

  const list = Array.isArray(payload)
    ? payload
    : Array.isArray(payload.data)
      ? payload.data
      : Array.isArray(payload.rows)
        ? payload.rows
        : []

  return list
    .map((item) => normalizeItem(item as MinecodeItem))
    .sort((a, b) => {
      const aValue = a.valuea.trim().toLowerCase()
      const bValue = b.valuea.trim().toLowerCase()
      const aRank = aValue === 'other' ? 1 : /^[a-z]\d+$/i.test(a.valuea.trim()) ? 2 : 0
      const bRank = bValue === 'other' ? 1 : /^[a-z]\d+$/i.test(b.valuea.trim()) ? 2 : 0

      if (aRank !== bRank) {
        return aRank - bRank
      }

      return a.valuea.localeCompare(b.valuea, 'en', { sensitivity: 'base' })
    })
}
