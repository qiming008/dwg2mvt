<template>
  <div class="cad-view-app">
    <header class="app-header">
      <div class="header-top">
        <div class="title-block">
          <h1 class="app-title">DWG / DXF 转切图</h1>
          <p class="app-sub">LibreDWG → DXF → GDAL → GeoPackage → GeoServer MVT / WMTS</p>
        </div>

        <div class="header-actions">
          <Uploader
            @convert="onConvert"
            @error="onError"
          />

          <div
            v-if="jobs.length > 0"
            ref="jobMenuRef"
            class="job-selector"
          >
            <button
              type="button"
              class="job-selector-trigger"
              :class="{ open: jobMenuOpen }"
              :title="selectedJobSummary"
              @click="toggleJobMenu"
            >
              <span class="job-selector-trigger-main">{{ selectedJobPrimaryLabel }}</span>
              <span class="job-selector-trigger-sub">{{ selectedJobSecondaryLabel }}</span>
              <span class="job-selector-caret">▾</span>
            </button>

            <Transition name="fade-scale">
              <div
                v-if="jobMenuOpen"
                class="job-dropdown-menu"
              >
                <div class="job-dropdown-header">
                  <span>图纸列表</span>
                  <div class="job-dropdown-header-actions">
                    <button
                      type="button"
                      class="job-dropdown-delete-all"
                      :disabled="jobs.length === 0"
                      @click.stop="deleteAllJobs"
                    >
                      全部删除
                    </button>
                    <span class="job-dropdown-count">{{ jobs.length }} 项</span>
                  </div>
                </div>

                <div
                  v-for="job in jobs"
                  :key="job.job_id"
                  class="job-dropdown-item"
                  :class="{ active: job.job_id === selectedJobId }"
                >
                  <button
                    type="button"
                    class="job-dropdown-select"
                    @click="selectJob(job.job_id)"
                  >
                    <span class="job-dropdown-dot" />
                    <span class="job-dropdown-content">
                      <span class="job-dropdown-name">{{ job.filename }}</span>
                      <span class="job-dropdown-time">{{ formatJobTime(job.created_at) }}</span>
                    </span>
                    <span class="job-dropdown-chevron">›</span>
                  </button>

                  <button
                    type="button"
                    class="job-dropdown-delete"
                    title="删除"
                    aria-label="删除图纸"
                    @click.stop="deleteJob(job)"
                  >
                    ×
                  </button>
                </div>
              </div>
            </Transition>
          </div>
        </div>
      </div>
    </header>

    <div
      v-if="error"
      class="app-error"
    >
      {{ error }}
    </div>

    <main class="app-main">
      <Map :result="result" />

      <div
        v-if="result && !result.mvt_url && result.status === 'done'"
        class="app-hint"
      >
        转换完成，GeoServer 未返回 MVT 地址时可以
        <a
          :href="API_ROUTES.gpkgDownload(result.job_id)"
          download
          style="margin-left: 4px"
        >下载 GPKG</a>
        在 QGIS 等工具中查看，或配置 GeoServer 后重新发布。
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import Uploader from './components/Uploader.vue'
import Map from './components/Map.vue'
import { API_ROUTES } from './api/routes'
import { requestJson } from './utils/request'
import type { ConvertResult, DeleteJobResult } from './types'

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
const jobMenuRef = ref<HTMLDivElement | null>(null)
const jobMenuOpen = ref(false)

const selectedJob = computed(() => jobs.value.find((job) => job.job_id === selectedJobId.value))

const selectedJobSummary = computed(() => {
  const selected = selectedJob.value
  if (!selected) {
    return '选择图纸'
  }
  return `${selected.filename} · ${formatJobTime(selected.created_at)}`
})

const selectedJobPrimaryLabel = computed(() => selectedJob.value?.filename || '选择图纸')

const selectedJobSecondaryLabel = computed(() => {
  const selected = selectedJob.value
  if (!selected) return '尚未选择'
  return formatJobTime(selected.created_at)
})

const formatJobTime = (timestamp: number) => {
  if (!timestamp) return ''
  return new Date(timestamp * 1000).toLocaleString()
}

const closeJobMenu = () => {
  jobMenuOpen.value = false
}

const toggleJobMenu = () => {
  jobMenuOpen.value = !jobMenuOpen.value
}

const fetchJobs = async () => {
  try {
    jobs.value = await requestJson<Job[]>(API_ROUTES.jobs, { method: 'GET' })
    if (selectedJobId.value && !jobs.value.some((job) => job.job_id === selectedJobId.value)) {
      selectedJobId.value = ''
    }
  } catch (e) {
    console.error('Failed to fetch jobs', e)
  }
}

const loadJob = async (jobId: string) => {
  if (!jobId) return
  try {
    const data = await requestJson<ConvertResult>(API_ROUTES.convertById(jobId), { method: 'GET' })
    result.value = data
    error.value = null
    selectedJobId.value = jobId
  } catch (e) {
    error.value = '加载图纸失败：' + e
  }
}

const selectJob = async (jobId: string) => {
  await loadJob(jobId)
  closeJobMenu()
}

const deleteJob = async (job: Job) => {
  const confirmed = window.confirm(`确定删除图纸「${job.filename}」吗？`)
  if (!confirmed) return

  try {
    const res = await requestJson<DeleteJobResult>(API_ROUTES.deleteJob(job.job_id), { method: 'DELETE' })
    if (!res.ok) {
      error.value = res.message || '删除失败'
      return
    }

    if (selectedJobId.value === job.job_id) {
      selectedJobId.value = ''
      result.value = null
    }

    await fetchJobs()
    closeJobMenu()
    error.value = null
  } catch (e) {
    error.value = '删除失败：' + e
  }
}

const deleteAllJobs = async () => {
  if (jobs.value.length === 0) return

  const confirmed = window.confirm(`确定删除全部 ${jobs.value.length} 张图纸吗？`)
  if (!confirmed) return

  const currentJobs = [...jobs.value]
  const failures: string[] = []

  try {
    for (const job of currentJobs) {
      try {
        const res = await requestJson<DeleteJobResult>(API_ROUTES.deleteJob(job.job_id), {
          method: 'DELETE',
        })
        if (!res.ok) {
          failures.push(res.message || `删除图纸「${job.filename}」失败`)
        }
      } catch (err) {
        failures.push(`删除图纸「${job.filename}」失败：${err}`)
      }
    }

    selectedJobId.value = ''
    result.value = null
    await fetchJobs()
    closeJobMenu()
    error.value = failures.length ? `部分删除失败：${failures[0]}` : null
  } catch (e) {
    error.value = '全部删除失败：' + e
    await fetchJobs()
  }
}

const onConvert = (res: ConvertResult) => {
  error.value = null
  result.value = res
  fetchJobs()
  if (res.job_id) {
    selectedJobId.value = res.job_id
  }
}

const onError = (msg: string) => {
  error.value = msg
  result.value = null
}

const onDocClick = (event: MouseEvent) => {
  if (!jobMenuOpen.value) return
  const target = event.target as Node | null
  if (jobMenuRef.value && target && !jobMenuRef.value.contains(target)) {
    jobMenuOpen.value = false
  }
}

onMounted(() => {
  fetchJobs()
  document.addEventListener('click', onDocClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
})
</script>

<style scoped>
.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}

.title-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.app-title {
  margin: 0;
}

.app-sub {
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.job-selector {
  display: flex;
  align-items: center;
  gap: 0;
  position: relative;
}

.job-selector-trigger {
  min-width: 320px;
  max-width: 420px;
  height: 48px;
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas:
    "main caret"
    "sub caret";
  gap: 3px 14px;
  align-items: center;
  text-align: left;
  cursor: pointer;
  padding: 0 16px;
  border-radius: 18px;
  border: 1px solid rgba(115, 161, 255, 0.24);
  background:
    linear-gradient(180deg, rgba(18, 26, 42, 0.98) 0%, rgba(10, 16, 27, 0.98) 100%);
  color: #eef4ff;
  box-shadow:
    0 14px 34px rgba(0, 0, 0, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
  user-select: none;
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background 0.18s ease;
}

.job-selector-trigger:hover {
  border-color: rgba(125, 166, 255, 0.44);
  transform: translateY(-1px);
  box-shadow:
    0 18px 38px rgba(0, 0, 0, 0.26),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.job-selector-trigger.open {
  border-color: rgba(90, 140, 255, 0.54);
  box-shadow:
    0 18px 40px rgba(0, 0, 0, 0.28),
    0 0 0 1px rgba(90, 140, 255, 0.18) inset;
}

.job-selector-trigger-main {
  grid-area: main;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.2;
  color: #f4f8ff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-selector-trigger-sub {
  grid-area: sub;
  font-size: 12px;
  color: rgba(211, 223, 247, 0.74);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-selector-caret {
  grid-area: caret;
  align-self: center;
  color: rgba(238, 244, 255, 0.72);
  font-size: 13px;
}

.job-dropdown-menu {
  position: absolute;
  top: calc(100% + 12px);
  right: 0;
  left: auto;
  width: min(520px, calc(100vw - 32px));
  min-width: 440px;
  max-height: 380px;
  overflow: auto;
  padding: 14px;
  border-radius: 20px;
  border: 1px solid rgba(125, 166, 255, 0.16);
  background:
    linear-gradient(180deg, rgba(11, 16, 28, 0.98) 0%, rgba(8, 12, 20, 0.98) 100%);
  box-shadow: 0 30px 72px rgba(0, 0, 0, 0.44);
  z-index: 60;
  backdrop-filter: blur(16px);
}

.job-dropdown-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 4px 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  color: rgba(235, 242, 255, 0.88);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.job-dropdown-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.job-dropdown-count {
  color: rgba(174, 191, 221, 0.8);
  font-weight: 500;
}

.job-dropdown-delete-all {
  border: 1px solid rgba(255, 119, 119, 0.38);
  background: linear-gradient(135deg, rgba(255, 86, 86, 0.22), rgba(255, 86, 86, 0.08));
  color: #ffd7d7;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.16s ease, filter 0.16s ease, opacity 0.16s ease;
}

.job-dropdown-delete-all:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.05);
}

.job-dropdown-delete-all:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.job-dropdown-item {
  display: flex;
  align-items: stretch;
  gap: 10px;
  margin-bottom: 10px;
  min-width: 0;
}

.job-dropdown-item:last-child {
  margin-bottom: 0;
}

.job-dropdown-item.active .job-dropdown-select {
  border-color: rgba(79, 140, 255, 0.56);
  background:
    linear-gradient(180deg, rgba(79, 140, 255, 0.16) 0%, rgba(79, 140, 255, 0.08) 100%);
}

.job-dropdown-select {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.04);
  color: #eef4ff;
  cursor: pointer;
  transition:
    background 0.18s ease,
    border-color 0.18s ease,
    transform 0.18s ease;
  min-width: 0;
}

.job-dropdown-select:hover {
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(125, 166, 255, 0.28);
  transform: translateX(1px);
}

.job-dropdown-dot {
  width: 10px;
  height: 10px;
  flex: 0 0 10px;
  border-radius: 999px;
  background: linear-gradient(180deg, #83a5ff 0%, #4f8cff 100%);
  box-shadow: 0 0 0 4px rgba(79, 140, 255, 0.12);
}

.job-dropdown-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.job-dropdown-name {
  font-size: 14px;
  line-height: 1.35;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-dropdown-time {
  font-size: 12px;
  color: rgba(174, 191, 221, 0.82);
}

.job-dropdown-chevron {
  color: rgba(174, 191, 221, 0.62);
  font-size: 18px;
  line-height: 1;
}

.job-dropdown-delete {
  flex: 0 0 36px;
  align-self: center;
  border: 1px solid rgba(255, 120, 120, 0.28);
  background: rgba(255, 88, 88, 0.08);
  color: #ffb0b0;
  border-radius: 12px;
  padding: 0;
  cursor: pointer;
  width: 36px;
  height: 36px;
  font-size: 20px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    background 0.18s ease,
    border-color 0.18s ease,
    color 0.18s ease,
    transform 0.18s ease;
}

.job-dropdown-delete:hover {
  background: rgba(255, 88, 88, 0.18);
  border-color: rgba(255, 120, 120, 0.42);
  color: #ffd0d0;
  transform: translateY(-1px);
}

.fade-scale-enter-active,
.fade-scale-leave-active {
  transition:
    opacity 0.16s ease,
    transform 0.16s ease;
}

.fade-scale-enter-from,
.fade-scale-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}
</style>
