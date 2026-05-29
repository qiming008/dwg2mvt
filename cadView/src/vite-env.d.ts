/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_DICT_SERVICE_BASE?: string
  readonly VITE_GEOSERVER_BASE?: string
  readonly VITE_GEOSERVER_PUBLIC_BASE?: string
  readonly VITE_API_TARGET?: string
  readonly VITE_BACKEND_URL?: string
  readonly VITE_GEOSERVER_TARGET?: string
  readonly VITE_AUTO_PROXY?: string
  readonly VITE_DEV_PORT?: string
  readonly VITE_PUBLIC_BASE?: string
  readonly VITE_TILE_PUBLIC_ORIGIN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
