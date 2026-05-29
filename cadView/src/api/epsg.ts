import { requestJson } from '../utils/request'
import { API_ROUTES } from './routes'
import type { CoordinateSystemOption } from '../types'

interface EpsgItem {
  epsgId?: string | number
  epsgDesc?: string
  epsgName?: string
  minLng?: string | number
  maxLng?: string | number
  mindleLng?: string | number
  remark?: string | null
}

interface EpsgResponse {
  code?: number
  data?: EpsgItem[] | CoordinateSystemOption[]
  rows?: EpsgItem[] | CoordinateSystemOption[]
}

function normalizeItem(item: EpsgItem): CoordinateSystemOption {
  const epsgId = String(item.epsgId ?? '')
  const epsgDesc = String(item.epsgDesc ?? epsgId)
  return {
    epsgId,
    epsgDesc,
    epsgName: item.epsgName ? String(item.epsgName) : undefined,
    minLng: item.minLng ? String(item.minLng) : undefined,
    maxLng: item.maxLng ? String(item.maxLng) : undefined,
    mindleLng: item.mindleLng ? String(item.mindleLng) : undefined,
    remark: item.remark ?? null,
  }
}

function compareByEpsgId(a: CoordinateSystemOption, b: CoordinateSystemOption) {
  const aNum = Number(a.epsgId)
  const bNum = Number(b.epsgId)
  if (Number.isFinite(aNum) && Number.isFinite(bNum)) {
    return aNum - bNum
  }
  return a.epsgId.localeCompare(b.epsgId, 'zh-CN', { numeric: true })
}

export async function fetchEpsgOptions() {
  const payload = await requestJson<EpsgResponse | EpsgItem[] | CoordinateSystemOption[]>(
    API_ROUTES.epsg,
    { method: 'GET' }
  )
  const list = Array.isArray(payload)
    ? payload
    : Array.isArray(payload.data)
      ? payload.data
      : Array.isArray(payload.rows)
        ? payload.rows
        : []

  return list
    .map((item) => normalizeItem(item as EpsgItem))
    .sort(compareByEpsgId)
}
