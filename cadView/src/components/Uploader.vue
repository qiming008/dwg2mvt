<template>
  <div class="uploader-form">
    <button type="button" :disabled="loading" class="uploader-submit-btn" @click="openUploadDialog">
      {{ loading ? '上传中...' : '上传并配置' }}
    </button>
  </div>

  <div v-if="showUploadDialog && !loading" class="modal-overlay">
    <div class="modal-content config-modal">
      <h3>上传图纸配置</h3>

      <div class="field-block">
        <div class="file-row">
          <button type="button" class="secondary-btn" :disabled="loading" @click="triggerFileSelect">
            选择图纸
          </button>
          <span class="file-name">{{ file ? file.name : '未选择文件' }}</span>
          <input
            ref="fileInputRef"
            type="file"
            accept=".dwg,.dxf"
            @change="onFileChange"
            class="hidden-file-input"
          />
        </div>
      </div>

      <label class="field-block">
        <span class="field-label">煤矿编码</span>
        <input
          v-model.trim="mineCodeInput"
          type="text"
          list="mine-code-options"
          placeholder="请输入煤矿名称或编码"
          class="field-input"
        />
        <datalist id="mine-code-options">
          <option
            v-for="option in filteredMineOptions"
            :key="option.code"
            :value="option.code"
          >
            {{ option.name }}
          </option>
        </datalist>
      </label>

      <label class="field-block">
        <span class="field-label">坐标系</span>
        <select v-model="coordinateSystem" class="field-input">
          <option value="">请选择坐标系</option>
          <option
            v-for="option in coordinateSystemOptions"
            :key="option.epsgId"
            :value="option.epsgId"
          >
            {{ option.epsgDesc }} ({{ option.epsgId }})
          </option>
        </select>
      </label>

      <div class="field-hint">
        请选择与原图一致的坐标系，后端会按它进行图纸转换。
      </div>

      <label class="field-block">
        <span class="field-label">煤层编码</span>
        <input
          v-model.trim="seamCodeInput"
          type="text"
          list="seam-code-options"
          placeholder="请输入煤层编码"
          class="field-input"
        />
        <datalist id="seam-code-options">
          <option
            v-for="option in seamOptions"
            :key="option.valuea"
            :value="option.valuea"
          >
            {{ option.label }}
          </option>
        </datalist>
      </label>

      <div class="field-hint">
        煤层编码可直接输入，也可以从建议列表中选择。
      </div>

      <label class="clean-toggle">
        <input v-model="cleanMode" type="checkbox" />
        <span>上传时清理文字、标注和噪声图层</span>
      </label>
      <div class="field-hint">
        勾选后会在上传转换阶段直接移除文字层、标注层等辅助内容，矢量切片会更干净。
      </div>

      <div class="modal-footer">
        <button type="button" @click="closeUploadDialog" class="cancel-btn">取消</button>
        <button
          type="button"
          @click="confirmUpload"
          :disabled="!canSubmitConfig"
          class="primary-btn"
        >
          确认上传
        </button>
      </div>
    </div>
  </div>

  <div v-if="loading" class="modal-overlay">
    <div class="modal-content">
      <h3>正在处理切片...</h3>

      <div class="progress-wrapper">
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" :style="{ width: progress + '%' }"></div>
        </div>
        <div class="progress-text">{{ progress }}% - {{ progressMsg }}</div>
      </div>

      <div v-if="showDetails" class="logs-container">
        <div v-for="(log, idx) in logs" :key="idx" class="log-item">
          {{ log }}
        </div>
      </div>

      <div class="modal-footer">
        <button type="button" @click="showDetails = !showDetails" class="detail-btn">
          {{ showDetails ? '收起详细信息' : '详细信息' }}
        </button>
        <button type="button" @click="cancelUpload" class="cancel-btn">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fetchEpsgOptions } from '../api/epsg'
import { fetchMinecodeOptions } from '../api/minecode'
import { API_ROUTES } from '../api/routes'
import { coordinateSystemOptions as localCoordinateSystemOptions } from '../data/coordinate-systems'
import { createAuthHeaders, requestJson } from '../utils/request'
import { getRuntimeOrgNode, runtimeOrgNodeVersion } from '../utils/auth'
import type { ConvertResult, CoordinateSystemOption, SeamOption } from '../types'

const emit = defineEmits<{
  (e: 'convert', res: ConvertResult): void
  (e: 'error', msg: string): void
}>()

const loading = ref(false)
const progress = ref(0)
const progressMsg = ref('')
const file = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const showDetails = ref(false)
const logs = ref<string[]>([])
const currentJobId = ref<string | null>(null)
const xhr = ref<XMLHttpRequest | null>(null)

const showUploadDialog = ref(false)
const mineCodeInput = ref('')
const coordinateSystem = ref('')
const seamCodeInput = ref('')
const cleanMode = ref(true)

const seamOptions = ref<SeamOption[]>([])
const coordinateSystemOptions = ref<CoordinateSystemOption[]>(localCoordinateSystemOptions)

interface MineOption {
  code: string
  name: string
}

const flattenMineOptions = (node: unknown): MineOption[] => {
  if (!node || typeof node !== 'object') return []

  const current = node as {
    isMine?: boolean
    name?: unknown
    code?: unknown
    children?: unknown
  }

  const result: MineOption[] = []
  if (current.isMine) {
    const code = String(current.code ?? '')
    const name = String(current.name ?? code)
    if (code) {
      result.push({ code, name })
    }
  }

  if (Array.isArray(current.children)) {
    for (const child of current.children) {
      result.push(...flattenMineOptions(child))
    }
  }

  return result
}

const mineOptions = computed(() => {
  runtimeOrgNodeVersion.value
  const orgNode = getRuntimeOrgNode()
  return flattenMineOptions(orgNode)
})

const filteredMineOptions = computed(() => {
  const keyword = mineCodeInput.value.trim().toLowerCase()
  if (!keyword) {
    return mineOptions.value
  }
  return mineOptions.value.filter((item) => {
    return item.name.toLowerCase().includes(keyword) || item.code.toLowerCase().includes(keyword)
  })
})

const resetUploadConfig = () => {
  mineCodeInput.value = ''
  coordinateSystem.value = ''
  seamCodeInput.value = ''
  cleanMode.value = true
}

const resetSelectedFile = () => {
  file.value = null
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
  }
}

const canSubmitConfig = computed(() => {
  return Boolean(file.value && mineCodeInput.value.trim() && coordinateSystem.value.trim() && seamCodeInput.value.trim())
})

const onFileChange = (e: Event) => {
  const target = e.target as HTMLInputElement
  file.value = target.files?.[0] ?? null
}

const triggerFileSelect = () => {
  fileInputRef.value?.click()
}

const loadCoordinateSystems = async () => {
  try {
    const options = await fetchEpsgOptions()
    
    if (options.length > 0) {
      coordinateSystemOptions.value = options
    }
  } catch (error) {
    console.warn('Failed to load EPSG options, fallback to local list.', error)
  }
}

const loadMinecodes = async () => {
  try {
    seamOptions.value = await fetchMinecodeOptions()
  } catch (error) {
    console.warn('Failed to load minecode options.', error)
    seamOptions.value = []
  }
}

const addLog = (msg: string) => {
  if (!msg) return
  const last = logs.value[logs.value.length - 1]
  if (last !== msg) {
    logs.value.push(msg)
  }
}

const openUploadDialog = () => {
  resetSelectedFile()
  resetUploadConfig()
  showUploadDialog.value = true
}

const closeUploadDialog = () => {
  showUploadDialog.value = false
  resetSelectedFile()
  resetUploadConfig()
}

const cancelUpload = () => {
  if (xhr.value) {
    xhr.value.abort()
    xhr.value = null
  }
  loading.value = false
  currentJobId.value = null
  logs.value = []
  resetSelectedFile()
  resetUploadConfig()
  emit('error', '已取消上传')
}

const pollStatus = async (jobId: string) => {
  if (!loading.value) return

  const poll = async () => {
    if (!loading.value || currentJobId.value !== jobId) return

    try {
      const res = await requestJson<ConvertResult>(API_ROUTES.status(jobId), { method: 'GET' })
      progress.value = res.progress || 0
      progressMsg.value = res.message || ''
      addLog(res.message || '')

      if (res.status === 'done') {
        loading.value = false
        emit('convert', res)
        return
      }

      if (res.status === 'error') {
        loading.value = false
        emit('error', res.message || '转换失败')
        return
      }

      setTimeout(poll, 1000)
    } catch (error) {
      console.error(error)
      if (loading.value) setTimeout(poll, 2000)
    }
  }

  poll()
}

const confirmUpload = async () => {
  if (!file.value || !canSubmitConfig.value) {
    emit('error', '请先补全煤矿编码、坐标系和煤层编码')
    return
  }

  const mineKeyword = mineCodeInput.value.trim()
  const selectedMine = mineOptions.value.find((item) => {
    return item.code === mineKeyword || item.name === mineKeyword
  })
  const mineCode = selectedMine?.code || mineKeyword
  const mineLabel = selectedMine?.name || mineKeyword
  const seamCode = seamCodeInput.value.trim()
  const selectedSeam = seamOptions.value.find((item) => item.valuea === seamCode)
  const seamLabel = selectedSeam?.label || seamCode

  showUploadDialog.value = false
  loading.value = true
  progress.value = 0
  progressMsg.value = '正在上传...'
  logs.value = ['开始上传...']
  showDetails.value = false
  emit('error', '')

  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('mine_code', mineCode)
    form.append('mine_label', mineLabel)
    form.append('coordinateSystem', coordinateSystem.value.trim())
    form.append('seam_code', seamCode.toLowerCase())
    form.append('seam_label', seamLabel)
    form.append('clean_mode', cleanMode.value ? 'true' : 'false')

    const req = new XMLHttpRequest()
    xhr.value = req
    req.open('POST', API_ROUTES.convert)
    const authHeaders = createAuthHeaders()
    authHeaders.forEach((value, key) => {
      req.setRequestHeader(key, value)
    })

    req.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100)
        progress.value = percent
        progressMsg.value = `正在上传... ${percent}%`
      }
    }

    req.onload = () => {
      xhr.value = null
      if (req.status >= 200 && req.status < 300) {
        try {
          const res = JSON.parse(req.responseText) as ConvertResult
          if (res.status === 'error') {
            loading.value = false
            emit('error', res.message || '转换失败')
            return
          }

          addLog('上传完成，等待处理...')
          progress.value = 0
          progressMsg.value = '准备转换...'
          currentJobId.value = res.job_id
          pollStatus(res.job_id)
        } catch {
          loading.value = false
          emit('error', '响应解析失败')
        }
      } else {
        loading.value = false
        let msg = `请求失败 ${req.status}`
        try {
          const err = JSON.parse(req.responseText)
          msg = err.detail?.msg || err.detail || err.message || msg
        } catch {
          // ignore
        }
        emit('error', msg)
      }
    }

    req.onerror = () => {
      xhr.value = null
      loading.value = false
      emit('error', '网络错误')
    }

    req.onabort = () => {
      xhr.value = null
    }

    req.send(form)
  } catch (error) {
    loading.value = false
    emit('error', error instanceof Error ? error.message : '未知错误')
  }
}

onMounted(() => {
  loadCoordinateSystems()
  loadMinecodes()
})
</script>

<style scoped>
.uploader-form {
  display: flex;
  align-items: center;
}

.uploader-submit-btn,
.primary-btn,
.secondary-btn,
.cancel-btn,
.detail-btn {
  border: none;
  border-radius: 12px;
  padding: 10px 18px;
  cursor: pointer;
}

.uploader-submit-btn,
.primary-btn {
  background: linear-gradient(135deg, #4f8cff 0%, #2a68ff 100%);
  color: #fff;
}

.secondary-btn {
  background: rgba(255, 255, 255, 0.1);
  color: #eef4ff;
}

.cancel-btn,
.detail-btn {
  background: rgba(255, 255, 255, 0.08);
  color: #eef4ff;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(4, 10, 20, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  width: min(560px, calc(100vw - 32px));
  background: rgba(12, 18, 32, 0.96);
  border: 1px solid rgba(111, 163, 255, 0.18);
  border-radius: 18px;
  padding: 22px;
  color: #eef4ff;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.4);
}

.config-modal {
  max-height: 88vh;
  overflow: auto;
}

.field-block {
  display: grid;
  gap: 8px;
  margin-top: 16px;
}

.field-label {
  font-size: 0.95rem;
  color: #cfe0ff;
}

.field-input {
  width: 100%;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(111, 163, 255, 0.28);
  background: rgba(9, 16, 30, 0.9);
  color: #eef4ff;
  box-sizing: border-box;
}

.field-hint {
  margin-top: 10px;
  color: #a9bbd9;
  font-size: 0.9rem;
  line-height: 1.6;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.file-name {
  color: #dce7fb;
  font-size: 0.95rem;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hidden-file-input {
  display: none;
}

.clean-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 18px;
  color: #e8f1ff;
  font-size: 0.95rem;
}

.clean-toggle input {
  width: 16px;
  height: 16px;
  accent-color: #4f8cff;
}

.field-error {
  margin-top: 10px;
  color: #ffb6b6;
  font-size: 0.92rem;
}

.modal-footer {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 20px;
}

.progress-wrapper {
  margin-top: 14px;
}

.progress-bar-bg {
  width: 100%;
  height: 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #4f8cff, #68e0cf);
}

.progress-text {
  margin-top: 10px;
  color: #cfe0ff;
}

.logs-container {
  margin-top: 14px;
  max-height: 220px;
  overflow: auto;
  padding: 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
  font-size: 0.92rem;
}

.log-item {
  padding: 3px 0;
  color: #dce7fb;
}
</style>
