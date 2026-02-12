export interface ConvertResult {
  job_id: string
  status: string
  progress?: number
  message?: string
  dxf_path?: string
  gpkg_path?: string
  layer_name?: string
  mvt_url?: string
  raster_url?: string
  wmts_url?: string
  bbox?: number[]
}
