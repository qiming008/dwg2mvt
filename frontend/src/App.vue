<script setup lang="ts">
import { ref, onMounted } from 'vue'
import Uploader from './components/Uploader.vue'
import Map from './components/Map.vue'
import type { ConvertResult } from './types'

interface Job {
  job_id: string
  filename: string
  status: string
  created_at: number
}

const result = ref<ConvertResult | null>(null)
const error = ref<string | null>(null)
const jobs = ref<Job[]>([])
const selectedJobId = ref<string>('')

const fetchJobs = async () => {
  try {
    const res = await fetch('/api/jobs')
    if (res.ok) {
      jobs.value = await res.json()
    }
  } catch (e) {
    console.error('Failed to fetch jobs', e)
  }
}

const loadJob = async (jobId: string) => {
  if (!jobId) return
  try {
    const res = await fetch(`/api/convert/${jobId}`)
    if (res.ok) {
      const data = await res.json()
      result.value = data
      error.value = null
      selectedJobId.value = jobId
    } else {
      error.value = 'Failed to load job'
    }
  } catch (e) {
    error.value = 'Error loading job: ' + e
  }
}

const onConvert = (res: ConvertResult) => {
  error.value = null
  result.value = res
  fetchJobs() // Refresh list after upload
  if (res.job_id) {
    selectedJobId.value = res.job_id
  }
}

const onError = (msg: string) => {
  error.value = msg
  result.value = null
}

onMounted(() => {
  fetchJobs()
})
</script>

<template>
  <header class="app-header">
    <div class="header-top">
      <h1 class="app-title">DWG 转切片</h1>
      <div class="header-actions">
        <Uploader
          api-base="/api"
          @convert="onConvert"
          @error="onError"
        />
        <div class="job-selector" v-if="jobs.length > 0">
          <label>已上传：</label>
          <select v-model="selectedJobId" @change="loadJob(selectedJobId)">
            <option value="" disabled>选择图纸...</option>
            <option v-for="job in jobs" :key="job.job_id" :value="job.job_id">
              {{ job.filename }} ({{ new Date(job.created_at * 1000).toLocaleString() }})
            </option>
          </select>
        </div>
      </div>
    </div>
    <p class="app-sub">
      LibreDWG → DXF → GDAL → GeoPackage → GeoServer MVT / WMTS
    </p>
  </header>
  
  <div v-if="error" class="app-error">{{ error }}</div>
  <main class="app-main">
    <Map :result="result" />
    <div v-if="result && !result.mvt_url && result.status === 'done'" class="app-hint">
      转换完成。GeoServer 未返回 MVT 地址时可
      <a :href="`/api/convert/${result.job_id}/gpkg`" download style="margin-left: 4px">下载 GPKG</a>
      在 QGIS 等工具中查看，或配置 GeoServer 后重新发布。
    </div>
  </main>
</template>

<style scoped>
.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 15px;
}

.job-selector {
  display: flex;
  align-items: center;
  gap: 10px;
}

.job-selector select {
  padding: 4px 8px;
  border-radius: 4px;
  border: 1px solid #ccc;
  font-size: 14px;
  min-width: 200px;
}
</style>
