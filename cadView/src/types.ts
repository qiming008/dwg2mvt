export interface ConvertResult {
  job_id: string
  status: string
  progress?: number
  message?: string
  dxf_path?: string
  gpkg_path?: string
  layer_name?: string
  mine_code?: string
  seam_code?: string
  seam_label?: string
  belt_code?: string
  coordinate_system?: string
  mvt_url?: string
  raster_url?: string
  wmts_url?: string
  bbox?: number[]
}

export interface LayerInfo {
  name: string
  color: string
  visible?: boolean
  kind?: string
}

export interface CoordinateSystemOption {
  epsgId: string
  epsgDesc: string
  epsgName?: string
  minLng?: string
  maxLng?: string
  mindleLng?: string
  remark?: string | null
}

export interface SeamOption {
  id?: string
  label: string
  valuea: string
  remarks?: string | null
}
