<template>
  <div class="map-wrapper">
    <div class="sidebar" :class="{ 'is-collapsed': isLayerListCollapsed }" v-if="layers.length > 0 && mapMode === 'vector'">
      <div class="sidebar-toggle" @click="isLayerListCollapsed = !isLayerListCollapsed" :title="isLayerListCollapsed ? '展开图层列表' : '收起图层列表'">
        {{ isLayerListCollapsed ? '▶' : '◀' }}
      </div>
      <div class="sidebar-content" v-show="!isLayerListCollapsed">
        <div class="sidebar-header">
          <h3>图层列表</h3>
          <label class="select-all">
            <input type="checkbox" :checked="allLayersSelected" @change="toggleAllLayers" />
            全选
          </label>
        </div>
        <div class="layer-list">
          <label v-for="layer in layers" :key="layer.name" class="layer-item">
            <input type="checkbox" :checked="selectedLayers.has(layer.name)" @change="toggleLayer(layer.name)" />
            <span class="layer-color-box" :style="{ backgroundColor: layer.color }"></span>
            <span class="layer-name" :title="layer.name">{{ layer.name }}</span>
          </label>
        </div>
      </div>
    </div>
    <div ref="mapContainer" class="map-container">
       <div class="map-toolbar" v-if="result">
         <button class="mode-toggle-btn" @click="toggleMode">
           切换为{{ mapMode === 'vector' ? '栅格预览' : '矢量预览' }}
         </button>
         <button class="original-preview-btn" @click="openOriginalPreview">
           原图预览
         </button>
       </div>
       <div class="mode-badge" v-if="result">
         {{ mapMode === 'original' ? '当前：原图预览' : mapMode === 'raster' ? '当前：栅格预览' : '当前：矢量预览' }}
       </div>
      <button class="reset-btn" @click="resetView" v-if="result">
         重置视角
      </button>
      <div
        v-if="mapMode === 'original'"
        class="original-preview-viewer"
        @wheel.prevent="handleOriginalPreviewWheel"
        @pointerdown="startOriginalPreviewDrag"
      >
        <div
          v-if="originalPreviewSvg"
          ref="originalPreviewSvgContainer"
          class="original-preview-svg"
          v-html="originalPreviewSvg"
        ></div>
        <div v-else class="preview-state" :class="{ 'is-error': originalPreviewStatus === 'error' }">
          {{ originalPreviewMessage }}
        </div>
      </div>
       <div class="coords-display" v-if="mouseCoords">
         经度：{{ mouseCoords[0].toFixed(6) }}, 纬度：{{ mouseCoords[1].toFixed(6) }}
       </div>
    </div>
  </div>
</template>


<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { API_ROUTES } from '../api/routes'
import { createAuthHeaders, requestJson } from '../utils/request'
import { GEOSERVER_PUBLIC_BASE, TILE_PUBLIC_ORIGIN } from '../config'
import type { ConvertResult, LayerInfo, OriginalPreviewStatus, OriginalPreviewStatusValue } from '../types'

const props = defineProps<{
  result: ConvertResult | null
}>()

const emit = defineEmits<{
  (e: 'selection-change', layers: string[]): void
}>()

const mapContainer = ref<HTMLElement | null>(null)
const map = ref<any>(null)
const layers = ref<LayerInfo[]>([])
const selectedLayers = ref<Set<string>>(new Set())
const isLayerListCollapsed = ref(false)
const mouseCoords = ref<[number, number] | null>(null)
const originalPreviewStatus = ref<OriginalPreviewStatusValue>('pending')
const originalPreviewMessage = ref('原图预览尚未生成')
const originalPreviewUrl = ref('')
const originalPreviewSvg = ref('')
const originalPreviewSvgContainer = ref<HTMLElement | null>(null)
const originalPreviewViewBox = ref({ x: 0, y: 0, width: 0, height: 0 })
const originalPreviewBaseViewBox = ref({ x: 0, y: 0, width: 0, height: 0 })
const originalPreviewDrag = ref({ active: false, x: 0, y: 0 })
let originalPreviewTimer: number | undefined
let originalPreviewStartedAt = 0
watch(isLayerListCollapsed, () => {
  setTimeout(() => {
    map.value?.resize()
  }, 350)
})

const mapMode = ref<'vector' | 'raster' | 'original'>('vector')
const allLayersSelected = computed(() => {
  const layerNames = new Set(layers.value.map(layer => layer.name))
  if (layerNames.size === 0) return false
  if (selectedLayers.value.size !== layerNames.size) return false
  return Array.from(layerNames).every(layerName => selectedLayers.value.has(layerName))
})

const normalizeLayerName = (value: unknown): string => String(value ?? '')
const tilePublicOrigin = TILE_PUBLIC_ORIGIN || window.location.origin

const buildSameOriginUrl = (url: string) => {
  if (url.startsWith('/')) {
    return tilePublicOrigin + url
  }
  return url
}

const buildPreviewUrl = (url: string) => {
  const apiOrigin = new URL(API_ROUTES.jobs, window.location.origin).origin
  const normalizedUrl = url.startsWith('/') ? new URL(url, apiOrigin).toString() : buildSameOriginUrl(url)
  const separator = normalizedUrl.includes('?') ? '&' : '?'
  return `${normalizedUrl}${separator}t=${Date.now()}`
}

const loadOriginalPreviewSvg = async (url: string) => {
  const res = await fetch(url, {
    headers: createAuthHeaders(),
  })
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`)
  }
  const svg = await res.text()
  const safeSvg = svg
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/\son[a-z]+\s*=\s*(['"]).*?\1/gi, '')
  originalPreviewSvg.value = safeSvg
  const viewBox = parseSvgViewBox(safeSvg)
  if (viewBox) {
    originalPreviewBaseViewBox.value = viewBox
    originalPreviewViewBox.value = { ...viewBox }
  }
  await nextTick()
  applyOriginalPreviewViewBox()
}

const textSizeExpression = [
  'interpolate',
  ['linear'],
  ['zoom'],
  8,
  ['max', 2, ['min', 7, ['*', ['to-number', ['get', 'text_size'], 12], 0.12]]],
  12,
  ['max', 4, ['min', 18, ['*', ['to-number', ['get', 'text_size'], 12], 0.45]]],
  16,
  ['max', 7, ['min', 42, ['*', ['to-number', ['get', 'text_size'], 12], 0.95]]],
  19,
  ['max', 9, ['min', 64, ['*', ['to-number', ['get', 'text_size'], 12], 1.25]]],
] as unknown as maplibregl.ExpressionSpecification

const textAnchorExpression = [
  'case',
  ['all', ['<=', ['to-number', ['get', 'anchor_x'], 0.5], 0.25], ['>=', ['to-number', ['get', 'anchor_y'], 0.5], 0.75]], 'top-left',
  ['all', ['>=', ['to-number', ['get', 'anchor_x'], 0.5], 0.75], ['>=', ['to-number', ['get', 'anchor_y'], 0.5], 0.75]], 'top-right',
  ['>=', ['to-number', ['get', 'anchor_y'], 0.5], 0.75], 'top',
  ['all', ['<=', ['to-number', ['get', 'anchor_x'], 0.5], 0.25], ['<=', ['to-number', ['get', 'anchor_y'], 0.5], 0.25]], 'bottom-left',
  ['all', ['>=', ['to-number', ['get', 'anchor_x'], 0.5], 0.75], ['<=', ['to-number', ['get', 'anchor_y'], 0.5], 0.25]], 'bottom-right',
  ['<=', ['to-number', ['get', 'anchor_y'], 0.5], 0.25], 'bottom',
  ['<=', ['to-number', ['get', 'anchor_x'], 0.5], 0.25], 'left',
  ['>=', ['to-number', ['get', 'anchor_x'], 0.5], 0.75], 'right',
  'center',
] as unknown as maplibregl.ExpressionSpecification

const textJustifyExpression = [
  'case',
  ['<=', ['to-number', ['get', 'anchor_x'], 0.5], 0.25], 'left',
  ['>=', ['to-number', ['get', 'anchor_x'], 0.5], 0.75], 'right',
  'center',
] as unknown as maplibregl.ExpressionSpecification

const textColorExpression = [
  'coalesce',
  ['get', 'text_color'],
  ['get', 'line_color'],
  '#ffffff',
] as unknown as maplibregl.ExpressionSpecification

const normalizeTileUrl = (url: string) => {
  if (url.startsWith('/')) return buildSameOriginUrl(url)

  try {
    const parsed = new URL(url)
    const geoserverPath = parsed.pathname.match(/\/(?:csrap_)?geoserver\/(.*)$/)
    if (geoserverPath) {
      return `${tilePublicOrigin}${GEOSERVER_PUBLIC_BASE}/${geoserverPath[1]}${parsed.search}`
    }
  } catch {
    // Keep the original URL if it is not an absolute URL.
  }

  return url
}

const buildLayerFilter = (): maplibregl.FilterSpecification => {
  const selectedLayerList = Array.from(selectedLayers.value).map(normalizeLayerName)
  if (selectedLayerList.length === 0) {
    return ['==', 'Layer', '__NO_MATCH__'] as unknown as maplibregl.FilterSpecification
  }
  return ['in', 'Layer', ...selectedLayerList] as unknown as maplibregl.FilterSpecification
}

const textFeatureFilter = ['any', ['has', 'Text'], ['has', 'text_content']] as unknown as maplibregl.FilterSpecification

const getDefaultViewBounds = (result: ConvertResult | null): number[] | undefined => {
  return result?.view_bbox || result?.bbox
}

const parseSvgViewBox = (svg: string) => {
  const match = svg.match(/\sviewBox=["']\s*([-\d.]+)[,\s]+([-\d.]+)[,\s]+([-\d.]+)[,\s]+([-\d.]+)\s*["']/i)
  if (!match) return null
  const values = match.slice(1).map(Number)
  if (values.some((value) => !Number.isFinite(value)) || values[2] <= 0 || values[3] <= 0) return null
  return { x: values[0], y: values[1], width: values[2], height: values[3] }
}

const applyOriginalPreviewViewBox = () => {
  const svg = originalPreviewSvgContainer.value?.querySelector('svg')
  const box = originalPreviewViewBox.value
  if (!svg || box.width <= 0 || box.height <= 0) return
  svg.setAttribute('viewBox', `${box.x} ${box.y} ${box.width} ${box.height}`)
}

const resetOriginalPreviewView = () => {
  originalPreviewViewBox.value = { ...originalPreviewBaseViewBox.value }
  nextTick(applyOriginalPreviewViewBox)
}

const stopOriginalPreviewPolling = () => {
  if (originalPreviewTimer !== undefined) {
    window.clearInterval(originalPreviewTimer)
    originalPreviewTimer = undefined
  }
}

const applyOriginalPreviewStatus = (status: OriginalPreviewStatus) => {
  originalPreviewStatus.value = status.status
  originalPreviewMessage.value = status.message || (
    status.status === 'ready'
      ? '原图预览已生成'
      : status.status === 'running'
        ? '正在生成原图预览...'
        : status.status === 'error'
          ? '原图预览生成失败'
          : '原图预览尚未生成'
  )

  if (status.status === 'ready' && status.url) {
    const previewUrl = buildPreviewUrl(status.url)
    originalPreviewUrl.value = previewUrl
    loadOriginalPreviewSvg(previewUrl).catch((e) => {
      console.error('Load original preview SVG error:', e)
      originalPreviewStatus.value = 'error'
      originalPreviewMessage.value = '加载原图预览失败'
    })
    stopOriginalPreviewPolling()
  }

  if (status.status === 'error') {
    stopOriginalPreviewPolling()
  }
}

const fetchOriginalPreviewStatus = async () => {
  const jobId = props.result?.job_id
  if (!jobId) return

  try {
    const status = await requestJson<OriginalPreviewStatus>(API_ROUTES.originalPreviewStatus(jobId), {
      method: 'GET',
    })
    applyOriginalPreviewStatus(status)
  } catch (e) {
    console.error('Fetch original preview status error:', e)
    originalPreviewStatus.value = 'error'
    originalPreviewMessage.value = '获取原图预览状态失败'
    stopOriginalPreviewPolling()
    return
  }

  if (originalPreviewStatus.value === 'running' && Date.now() - originalPreviewStartedAt > 5 * 60 * 1000) {
    originalPreviewStatus.value = 'error'
    originalPreviewMessage.value = '原图预览生成时间较长，请稍后重新打开查看'
    stopOriginalPreviewPolling()
  }
}

const startOriginalPreviewPolling = () => {
  stopOriginalPreviewPolling()
  originalPreviewTimer = window.setInterval(fetchOriginalPreviewStatus, 2000)
}

const openOriginalPreview = async () => {
  const jobId = props.result?.job_id
  if (!jobId) return

  mapMode.value = 'original'
  renderMapLayers()
  resetOriginalPreviewView()
  originalPreviewUrl.value = ''
  originalPreviewSvg.value = ''
  originalPreviewStatus.value = 'running'
  originalPreviewMessage.value = '正在准备原图预览...'
  originalPreviewStartedAt = Date.now()

  try {
    const status = await requestJson<OriginalPreviewStatus>(API_ROUTES.originalPreviewStart(jobId), {
      method: 'POST',
    })
    applyOriginalPreviewStatus(status)
    if (status.status === 'running' || status.status === 'pending') {
      startOriginalPreviewPolling()
    }
  } catch (e) {
    console.error('Start original preview error:', e)
    originalPreviewStatus.value = 'error'
    originalPreviewMessage.value = '启动原图预览失败'
    stopOriginalPreviewPolling()
  }
}

const handleOriginalPreviewWheel = (event: WheelEvent) => {
  const svg = originalPreviewSvgContainer.value?.querySelector('svg')
  const rect = svg?.getBoundingClientRect()
  const base = originalPreviewBaseViewBox.value
  const current = originalPreviewViewBox.value
  if (!rect || rect.width <= 0 || rect.height <= 0 || base.width <= 0 || base.height <= 0 || current.width <= 0) return

  const zoom = event.deltaY < 0 ? 1.18 : 0.85
  const minWidth = base.width / 32
  const maxWidth = base.width * 1.5
  const nextWidth = Math.min(maxWidth, Math.max(minWidth, current.width / zoom))
  const nextHeight = nextWidth * (current.height / current.width)
  const ratioX = (event.clientX - rect.left) / rect.width
  const ratioY = (event.clientY - rect.top) / rect.height
  const anchorX = current.x + current.width * ratioX
  const anchorY = current.y + current.height * ratioY
  originalPreviewViewBox.value = {
    x: anchorX - nextWidth * ratioX,
    y: anchorY - nextHeight * ratioY,
    width: nextWidth,
    height: nextHeight,
  }
  applyOriginalPreviewViewBox()
}

const startOriginalPreviewDrag = (event: PointerEvent) => {
  if (event.button !== 0) return
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  originalPreviewDrag.value = {
    active: true,
    x: event.clientX,
    y: event.clientY,
  }
  window.addEventListener('pointermove', handleOriginalPreviewDrag)
  window.addEventListener('pointerup', stopOriginalPreviewDrag)
  window.addEventListener('pointercancel', stopOriginalPreviewDrag)
}

const handleOriginalPreviewDrag = (event: PointerEvent) => {
  if (!originalPreviewDrag.value.active) return
  event.preventDefault()
  const dx = event.clientX - originalPreviewDrag.value.x
  const dy = event.clientY - originalPreviewDrag.value.y
  const svg = originalPreviewSvgContainer.value?.querySelector('svg')
  const rect = svg?.getBoundingClientRect()
  const current = originalPreviewViewBox.value
  if (rect && rect.width > 0 && rect.height > 0 && current.width > 0 && current.height > 0) {
    originalPreviewViewBox.value = {
      x: current.x - dx * (current.width / rect.width),
      y: current.y - dy * (current.height / rect.height),
      width: current.width,
      height: current.height,
    }
    applyOriginalPreviewViewBox()
  }
  originalPreviewDrag.value = {
    active: true,
    x: event.clientX,
    y: event.clientY,
  }
}

const stopOriginalPreviewDrag = () => {
  originalPreviewDrag.value.active = false
  window.removeEventListener('pointermove', handleOriginalPreviewDrag)
  window.removeEventListener('pointerup', stopOriginalPreviewDrag)
  window.removeEventListener('pointercancel', stopOriginalPreviewDrag)
}

const toggleMode = () => {
  mapMode.value = mapMode.value === 'vector' ? 'raster' : 'vector'
  renderMapLayers()
}

const resetView = () => {
  if (mapMode.value === 'original') {
    resetOriginalPreviewView()
    return
  }
  const bounds = getDefaultViewBounds(props.result)
  if (!map.value || !bounds) return
  const [minX, minY, maxX, maxY] = bounds
  // Validate bounds
  const isValid = (n: number) => Number.isFinite(n) && Math.abs(n) < 1e20
  const isValidLat = (n: number) => n >= -90 && n <= 90
  
  if (isValid(minX) && isValid(minY) && isValid(maxX) && isValid(maxY) &&
      isValidLat(minY) && isValidLat(maxY)) {
    try {
      map.value.fitBounds(bounds as [number, number, number, number], { padding: 50 })
    } catch (e) {
      console.error('Error fitting bounds:', e)
    }
  } else {
    console.warn('Invalid bounds, cannot reset view:', bounds)
  }
}

const toggleLayer = (layerName: string) => {
  if (selectedLayers.value.has(layerName)) {
    selectedLayers.value.delete(layerName)
  } else {
    selectedLayers.value.add(layerName)
  }
  updateMapFilters()
  emit('selection-change', Array.from(selectedLayers.value))
}

const toggleAllLayers = () => {
  if (allLayersSelected.value) {
    selectedLayers.value = new Set()
  } else {
    selectedLayers.value = new Set(layers.value.map(l => l.name))
  }
  updateMapFilters()
  emit('selection-change', Array.from(selectedLayers.value))
}

const updateMapFilters = () => {
  if (!map.value) return
  
  const layerFilter = buildLayerFilter()
  
  // Update fill and line layers
  if (map.value.getLayer('dwg-layer-fill')) {
    map.value.setFilter(
      'dwg-layer-fill',
      ['all', ['==', '$type', 'Polygon'], layerFilter] as maplibregl.FilterSpecification
    )
  }
  if (map.value.getLayer('dwg-layer-line')) {
    map.value.setFilter(
      'dwg-layer-line',
      ['all', ['any', ['==', '$type', 'LineString'], ['==', '$type', 'Polygon']], layerFilter] as maplibregl.FilterSpecification
    )
  }

  // Update text layer
  if (map.value.getLayer('dwg-layer-text')) {
    map.value.setFilter('dwg-layer-text', ['all', textFeatureFilter, layerFilter] as maplibregl.FilterSpecification)
  }
}

const renderMapLayers = () => {
  if (!map.value || !props.result) return

  const sourceId = 'dwg-source'
  const layerIdLine = 'dwg-layer-line'
  const layerIdFill = 'dwg-layer-fill'
  const layerIdText = 'dwg-layer-text'
  const layerIdRaster = 'dwg-layer-raster'

  // Remove existing layers/sources
  if (map.value.getLayer(layerIdLine)) map.value.removeLayer(layerIdLine)
  if (map.value.getLayer(layerIdFill)) map.value.removeLayer(layerIdFill)
  if (map.value.getLayer(layerIdText)) map.value.removeLayer(layerIdText)
  if (map.value.getLayer(layerIdRaster)) map.value.removeLayer(layerIdRaster)
  if (map.value.getSource(sourceId)) map.value.removeSource(sourceId)

  if (mapMode.value === 'original') return

  if (mapMode.value === 'raster') {
    if (!props.result.raster_url) {
      console.warn('No raster URL available')
    } else {
      const rasterUrl = normalizeTileUrl(props.result.raster_url)

      map.value.addSource(sourceId, {
        type: 'raster',
        tiles: [rasterUrl],
        tileSize: 256,
        scheme: 'xyz'
      })

      map.value.addLayer({
        id: layerIdRaster,
        type: 'raster',
        source: sourceId,
        paint: {
          'raster-opacity': 1
        }
      })
      return
    }
  }

  // Vector Mode
  if (!props.result.mvt_url) return

  const mvtUrl = normalizeTileUrl(props.result.mvt_url)
  
  console.log('Loading MVT URL in MapLibre:', mvtUrl)

  map.value.addSource(sourceId, {
    type: 'vector',
    tiles: [mvtUrl],
    scheme: 'xyz'
  })

  // Use layer_name from result, or default to generic if missing.
  const sourceLayer = props.result.layer_name || 'entities'

  // Add fill layer first (so it's below lines)
  map.value.addLayer({
    id: layerIdFill,
    type: 'fill',
    source: sourceId,
    'source-layer': sourceLayer,
    filter: [
      'all',
      ['==', '$type', 'Polygon']
    ] as unknown as maplibregl.FilterSpecification,
    paint: {
      'fill-color': ['coalesce', ['get', 'fill_color'], 'rgba(0,0,0,0)'],
      'fill-opacity': 0.8,
      'fill-outline-color': 'rgba(0,0,0,0)'
    }
  })

  // Add line layer
  map.value.addLayer({
    id: layerIdLine,
    type: 'line',
    source: sourceId,
    'source-layer': sourceLayer,
    filter: ['in', '$type', 'LineString', 'Polygon'],
    paint: {
      'line-color': ['coalesce', ['get', 'line_color'], '#2563eb'],
      'line-width': [
        'case',
        ['has', 'line_width'],
        ['/', ['get', 'line_width'], 25], // Convert 1/100mm to ~pixels (25 units = 1px)
        1 // Default line width if missing
      ]
    }
  })

  // Add symbol layer for text
  map.value.addLayer({
    id: 'dwg-layer-text',
    type: 'symbol',
    source: sourceId,
    'source-layer': sourceLayer,
    layout: {
      'text-field': ['coalesce', ['get', 'text_content'], ['get', 'Text']],
      'text-size': textSizeExpression,
      'text-rotate': ['coalesce', ['get', 'text_angle'], ['get', 'rotation'], 0],
      'text-anchor': textAnchorExpression,
      'text-justify': textJustifyExpression,
      'text-max-width': 1000,
      'text-line-height': 1,
      'text-allow-overlap': true,
      'text-ignore-placement': true,
      'text-rotation-alignment': 'map',
      'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular']
    },
    paint: {
      'text-color': textColorExpression
    },
    filter: textFeatureFilter
  })
  
  // Re-apply filters if needed
  updateMapFilters()
}

onMounted(() => {
  if (!mapContainer.value) return

  // Initialize MapLibre GL map (Open-source Mapbox GL compatible)
  map.value = new maplibregl.Map({
    container: mapContainer.value,
    style: {
      version: 8,
      sources: {},
      layers: [
        {
          id: 'background',
          type: 'background',
          paint: {
            'background-color': '#212830'
          }
        }
      ]
    },
    // center: [116.4, 39.9], // Don't set initial center to avoid loading unnecessary tiles
    // zoom: 3,
    localIdeographFontFamily: "'SimSun', 'SimHei', 'sans-serif'"
  })
  
  ;(map.value as any).addControl(new maplibregl.NavigationControl())
  
  // Add mouse move event listener to track coordinates
  map.value.on('mousemove', (e: any) => {
    const lng = e.lngLat.lng
    const lat = e.lngLat.lat
    mouseCoords.value = [lng, lat]
  })
  
  map.value.on('mouseleave', () => {
    mouseCoords.value = null
  })
})

onUnmounted(() => {
  stopOriginalPreviewPolling()
  stopOriginalPreviewDrag()
  if (map.value) {
    map.value.remove()
    map.value = null
  }
})

watch(() => props.result, async (newVal) => {
  if (!map.value || !newVal) return
  
  // 1. Fetch layers
    if (newVal.job_id) {
      try {
        const data = await requestJson<LayerInfo[] | string[]>(API_ROUTES.layers(newVal.job_id), {
          method: 'GET',
        })
        const rawLayers = data as Array<string | LayerInfo>
        // Backward compatibility: if array of strings, map to objects
        if (rawLayers.length > 0 && typeof rawLayers[0] === 'string') {
          layers.value = (rawLayers as string[]).map((l) => ({ name: normalizeLayerName(l), color: '#9ca3af', visible: true }))
        } else {
          layers.value = (rawLayers as LayerInfo[]).map((layer) => ({
            ...layer,
            name: normalizeLayerName(layer.name),
          }))
        }
        const defaultVisibleLayers = layers.value
          .filter(layer => layer.visible !== false)
          .map(layer => normalizeLayerName(layer.name))
        selectedLayers.value = new Set(defaultVisibleLayers)
        emit('selection-change', Array.from(selectedLayers.value))
      } catch (e) {
        console.error('Fetch layers error:', e)
    }
  }

  // 2. Fit Bounds First (to prevent loading tiles for wrong location)
  // Note: MVT doesn't provide bounds automatically, so we use the bounds from the conversion result.
  const viewBounds = getDefaultViewBounds(newVal)
  console.log('Conversion result bounds:', newVal.bbox, 'view bounds:', viewBounds)
  if (viewBounds) {
    const [minX, minY, maxX, maxY] = viewBounds
    // Validate bounds to prevent MapLibre error
    const isValid = (n: number) => Number.isFinite(n) && Math.abs(n) < 1e20
    const isValidLat = (n: number) => n >= -90 && n <= 90
    
    if (isValid(minX) && isValid(minY) && isValid(maxX) && isValid(maxY) &&
        isValidLat(minY) && isValidLat(maxY)) {
      console.log('Fitting bounds:', viewBounds)
      try {
        // Use animate: false to jump immediately before loading layers
        map.value.fitBounds(viewBounds as [number, number, number, number], { padding: 50, animate: false })
      } catch (e) {
        console.error('Error fitting bounds:', e)
      }
    } else {
      console.warn('Invalid bounds detected, skipping fitBounds:', viewBounds)
    }
  }

  // 3. Render Map Layers (Vector or Raster)
  renderMapLayers()
})
</script>



<style scoped>
.map-wrapper {
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;
  position: relative;
}

.sidebar {
  width: 240px;
  background: #3b4453;
  border-right: 1px solid #2d3239;
  display: flex;
  flex-direction: row;
  z-index: 10;
  box-shadow: 2px 0 5px rgba(0,0,0,0.2);
  transition: width 0.3s ease;
}

.sidebar.is-collapsed {
  width: 24px;
}

.sidebar-toggle {
  width: 24px;
  height: 100%;
  background: #23272e;
  color: #9ca3af;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border-right: 1px solid #1f2937;
  font-size: 10px;
  flex-shrink: 0;
}

.sidebar-toggle:hover {
  background: #374151;
  color: #fff;
}

.sidebar-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
  height: 100%;
}

.sidebar-header {
  padding: 10px 15px;
  border-bottom: 1px solid #2d3239;
  background: #2e3440;
}

.sidebar-header h3 {
  margin: 0 0 8px 0;
  font-size: 1rem;
  color: #e5e7eb;
}

.select-all {
  font-size: 0.85rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #9ca3af;
}

.layer-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.layer-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  cursor: pointer;
  font-size: 0.9rem;
  color: #d1d5db;
}

.layer-item:hover {
  color: #fff;
}

.layer-color-box {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 1px solid rgba(255,255,255,0.2);
}

.map-toolbar {
  position: absolute;
  top: 10px;
  right: 60px;
  z-index: 10;
  display: flex;
  gap: 8px;
}

.mode-toggle-btn {
  background-color: rgba(30, 41, 59, 0.8);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.2);
  padding: 8px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: background-color 0.2s;
}

.mode-toggle-btn:hover {
  background-color: rgba(30, 41, 59, 1);
}

.mode-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 10;
  background-color: rgba(15, 23, 42, 0.86);
  color: #e5e7eb;
  border: 1px solid rgba(255, 255, 255, 0.14);
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  letter-spacing: 0.02em;
  pointer-events: none;
}

.reset-btn {
  position: absolute;
  bottom: 40px;
  right: 10px;
  z-index: 10;
  background-color: #3b82f6;
  color: white;
  border: none;
  padding: 8px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
  transition: background-color 0.2s;
}

.reset-btn:hover {
  background-color: #2563eb;
}

.original-preview-btn {
  background-color: #10b981;
  color: white;
  border: none;
  padding: 8px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
  transition: background-color 0.2s;
}

.original-preview-btn:hover {
  background-color: #059669;
}

.coords-display {
  position: absolute;
  bottom: 10px;
  left: 10px;
  z-index: 10;
  background-color: rgba(30, 41, 59, 0.85);
  color: #e5e7eb;
  padding: 6px 12px;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'Consolas', 'Monaco', monospace;
  pointer-events: none;
  box-shadow: 0 2px 4px rgba(0,0,0,0.3);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.layer-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.map-container {
  flex: 1;
  height: 100%;
  background: rgb(11, 32, 81);
  position: relative;
}

.original-preview-viewer {
  position: absolute;
  inset: 0;
  z-index: 5;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #050505;
  cursor: grab;
  touch-action: none;
}

.original-preview-viewer:active {
  cursor: grabbing;
}

.original-preview-svg {
  max-width: 96%;
  max-height: 96%;
  user-select: none;
  pointer-events: none;
}

.original-preview-svg :deep(svg) {
  display: block;
  width: min(100%, 96vw);
  height: min(100%, 96vh);
  max-width: 100%;
  max-height: 100%;
}

.preview-state {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  color: #e5e7eb;
  text-align: center;
}

.preview-state.is-error {
  color: #fecaca;
}
</style>
