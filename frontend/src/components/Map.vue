<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { ConvertResult } from '../types'

const props = defineProps<{
  result: ConvertResult | null
}>()

const mapContainer = ref<HTMLElement | null>(null)
const map = ref<any>(null)
const layers = ref<{name: string, color: string}[]>([])
const selectedLayers = ref<Set<string>>(new Set())
const mapMode = ref<'vector' | 'raster'>('vector')

const toggleMode = () => {
  mapMode.value = mapMode.value === 'vector' ? 'raster' : 'vector'
  renderMapLayers()
}

const resetView = () => {
  if (!map.value || !props.result?.bbox) return
  const [minX, minY, maxX, maxY] = props.result.bbox
  // Validate bounds
  const isValid = (n: number) => Number.isFinite(n) && Math.abs(n) < 1e20
  const isValidLat = (n: number) => n >= -90 && n <= 90
  
  if (isValid(minX) && isValid(minY) && isValid(maxX) && isValid(maxY) &&
      isValidLat(minY) && isValidLat(maxY)) {
    try {
      map.value.fitBounds(props.result.bbox as [number, number, number, number], { padding: 50 })
    } catch (e) {
      console.error('Error fitting bounds:', e)
    }
  } else {
    console.warn('Invalid bounds, cannot reset view:', props.result.bbox)
  }
}

const toggleLayer = (layerName: string) => {
  if (selectedLayers.value.has(layerName)) {
    selectedLayers.value.delete(layerName)
  } else {
    selectedLayers.value.add(layerName)
  }
  updateMapFilters()
}

const toggleAllLayers = (e: Event) => {
  const checked = (e.target as HTMLInputElement).checked
  if (checked) {
    selectedLayers.value = new Set(layers.value.map(l => l.name))
  } else {
    selectedLayers.value = new Set()
  }
  updateMapFilters()
}

const updateMapFilters = () => {
  if (!map.value) return
  
  const layerFilter: maplibregl.ExpressionSpecification = ['in', ['get', 'Layer'], ['literal', Array.from(selectedLayers.value)]]
  
  // Update fill and line layers
  const shapeLayers = ['dwg-layer-fill', 'dwg-layer-line']
  shapeLayers.forEach(id => {
    if (map.value?.getLayer(id)) {
      map.value.setFilter(id, layerFilter as maplibregl.FilterSpecification)
    }
  })

  // Update text layer (preserve 'has Text' check)
  if (map.value.getLayer('dwg-layer-text')) {
    map.value.setFilter('dwg-layer-text', ['all', ['has', 'Text'], layerFilter] as maplibregl.FilterSpecification)
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

  if (mapMode.value === 'raster') {
    if (!props.result.raster_url) {
      console.warn('No raster URL available')
      return
    }
    let rasterUrl = props.result.raster_url
    if (rasterUrl.startsWith('/')) rasterUrl = window.location.origin + rasterUrl
    
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

  // Vector Mode
  if (!props.result.mvt_url) return

  let mvtUrl = props.result.mvt_url
  if (mvtUrl.startsWith('/')) {
    mvtUrl = window.location.origin + mvtUrl
  }
  
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
    filter: ['==', '$type', 'Polygon'],
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
      'text-field': ['get', 'Text'],
      'text-size': 12,
      'text-rotate': ['get', 'rotation'],
      'text-allow-overlap': false,
      'text-ignore-placement': false,
      'text-rotation-alignment': 'map',
      'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular']
    },
    paint: {
      'text-color': '#ffffff'
    },
    filter: ['has', 'Text']
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
      glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
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
    center: [116.4, 39.9],
    zoom: 3,
    localIdeographFontFamily: "'SimSun', 'SimHei', 'sans-serif'"
  })
  
  ;(map.value as any).addControl(new maplibregl.NavigationControl())
})

onUnmounted(() => {
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
      const res = await fetch(`/api/layers/${newVal.job_id}`)
      if (res.ok) {
        const data = await res.json()
        // Backward compatibility: if array of strings, map to objects
        if (data.length > 0 && typeof data[0] === 'string') {
           layers.value = data.map((l: string) => ({ name: l, color: '#9ca3af' }))
        } else {
           layers.value = data
        }
        selectedLayers.value = new Set(layers.value.map(l => l.name))
      }
    } catch (e) {
      console.error('Fetch layers error:', e)
    }
  }

  // 2. Render Map Layers (Vector or Raster)
  renderMapLayers()
  
  // Note: MVT doesn't provide bounds automatically, so we use the bounds from the conversion result.
  console.log('Conversion result bounds:', newVal.bbox)
  if (newVal.bbox) {
    const [minX, minY, maxX, maxY] = newVal.bbox
    // Validate bounds to prevent MapLibre error
    const isValid = (n: number) => Number.isFinite(n) && Math.abs(n) < 1e20
    const isValidLat = (n: number) => n >= -90 && n <= 90
    
    if (isValid(minX) && isValid(minY) && isValid(maxX) && isValid(maxY) &&
        isValidLat(minY) && isValidLat(maxY)) {
      console.log('Fitting bounds:', newVal.bbox)
      try {
        map.value.fitBounds(newVal.bbox as [number, number, number, number], { padding: 50 })
      } catch (e) {
        console.error('Error fitting bounds:', e)
      }
    } else {
      console.warn('Invalid bounds detected, skipping fitBounds:', newVal.bbox)
    }
  }
})
</script>

<template>
  <div class="map-wrapper">
    <div class="sidebar" v-if="layers.length > 0 && mapMode === 'vector'">
      <div class="sidebar-header">
        <h3>图层列表</h3>
        <label class="select-all">
          <input type="checkbox" :checked="selectedLayers.size === layers.length" @change="toggleAllLayers" />
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
    <div ref="mapContainer" class="map-container">
       <button class="mode-toggle-btn" @click="toggleMode" v-if="result">
         切换为{{ mapMode === 'vector' ? '栅格切片 (图片)' : '矢量切片 (交互)' }}
       </button>
       <button class="reset-btn" @click="resetView" v-if="result">
         重置视角
       </button>
    </div>
  </div>
</template>

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
  flex-direction: column;
  z-index: 10;
  box-shadow: 2px 0 5px rgba(0,0,0,0.2);
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
  width: 12px;
  height: 12px;
  border-radius: 2px;
  flex-shrink: 0;
  border: 1px solid rgba(255,255,255,0.2);
}

.mode-toggle-btn {
  position: absolute;
  top: 10px;
  right: 60px;
  z-index: 10;
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
</style>
