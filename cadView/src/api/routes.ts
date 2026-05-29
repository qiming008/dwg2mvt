import { API_BASE } from '../config'

export const API_ROUTES = {
  jobs: `${API_BASE}/jobs`,
  convertById: (jobId: string) => `${API_BASE}/convert/${jobId}`,
  layers: (jobId: string) => `${API_BASE}/layers/${jobId}`,
  status: (jobId: string) => `${API_BASE}/status/${jobId}`,
  deleteJob: (jobId: string) => `${API_BASE}/jobs/${jobId}`,
  convert: `${API_BASE}/convert`,
  gpkgDownload: (jobId: string) => `${API_BASE}/convert/${jobId}/gpkg`,
  originalPreviewStart: (jobId: string) => `${API_BASE}/convert/${jobId}/original-preview`,
  originalPreviewStatus: (jobId: string) => `${API_BASE}/convert/${jobId}/original-preview/status`,
  originalPreviewFile: (jobId: string) => `${API_BASE}/convert/${jobId}/original-preview/file`,
  epsg: '/jy-csp-gis/api/baseinfo/epsg',
  minecodeDictList: '/jy-csp-gis/api/v2.7/three/sysDict/list?clientId=jy-csp-gis&dictCode=MINECODE',
} as const
